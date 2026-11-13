"""消息 —— Agent 的统一数据骨架（第 1 章）。

四种消息 + 一个调用结构，就是整个内核的数据底座：
- ``SystemMessage`` / ``HumanMessage`` / ``AIMessage`` / ``ToolMessage``
- ``ToolCall``：模型发出的结构化调用请求（原生工具调用协议的核心）

相较最小消息模型，这里多了两样 Harness 工程必需的能力：
- ``Usage``：每次模型调用的 token 用量。上下文压缩（第 3 章）和预算控制
  （第 6 章）都要靠它做决策——**测不到就管不了**。
- ``to_jsonable`` / ``from_jsonable``：消息的无损序列化。会话持久化（第 5 章）
  把每条消息写进 JSONL 事件日志、重启后再读回来，靠的就是这一对函数。
"""

from __future__ import annotations

import base64
import mimetypes
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


@dataclass
class ToolCall:
    """模型发出的一次工具调用请求。

    ``name`` + ``args`` 是两个独立的结构化字段，不是一段要正则解析的文本——
    这是现代 Agent 与 2023 年那批 "Thought/Action 文本协议" Agent 的分水岭。
    ``id`` 用于把工具结果配对回这次调用（模型一轮可能发多个调用）。
    """

    name: str
    args: dict[str, Any]
    id: str = field(default_factory=_new_id)


@dataclass
class Usage:
    """一次模型调用的 token 用量（provider 返回什么就记什么，记不到就是 0）。"""

    input_tokens: int = 0
    output_tokens: int = 0
    # Subsets of input/output, never add these a second time to total tokens.
    reasoning_tokens: int | None = None
    cached_tokens: int | None = None

    def __add__(self, other: Usage) -> Usage:
        def detail(name):
            a, b = getattr(self, name), getattr(other, name)
            if self.input_tokens == self.output_tokens == 0 and a is None:
                return b
            if other.input_tokens == other.output_tokens == 0 and b is None:
                return a
            return None if a is None or b is None else a + b
        return Usage(
            self.input_tokens + other.input_tokens,
            self.output_tokens + other.output_tokens,
            detail("reasoning_tokens"),
            detail("cached_tokens"),
        )


@dataclass
class ImageContent:
    """A provider-neutral inline image attached to a human message.

    ``data`` contains base64 bytes without a data-URL prefix.  Keeping images in
    the message object (instead of passing a local path to a remote provider)
    makes the visual input explicit and serializable.
    """

    data: str
    media_type: str = "image/png"
    label: str = ""
    detail: str = "auto"

    @classmethod
    def from_file(cls, path: str, *, label: str = "", detail: str = "auto") -> ImageContent:
        p = Path(path)
        media_type = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
        return cls(
            data=base64.b64encode(p.read_bytes()).decode("ascii"),
            media_type=media_type,
            label=label,
            detail=detail,
        )

    @property
    def data_url(self) -> str:
        return f"data:{self.media_type};base64,{self.data}"


@dataclass
class BaseMessage:
    content: str = ""
    id: str = field(default_factory=_new_id)

    @property
    def role(self) -> str:
        raise NotImplementedError

    def __repr__(self) -> str:
        text = self.content if len(self.content) <= 60 else self.content[:57] + "..."
        return f"{type(self).__name__}({text!r})"


@dataclass
class SystemMessage(BaseMessage):
    """系统指令。注意：在 core 包里它**不进入历史**，而是每轮由
    ContextManager 现场装配（第 3 章会讲为什么）。"""

    @property
    def role(self) -> str:
        return "system"


@dataclass
class HumanMessage(BaseMessage):
    """用户输入（也用于压缩摘要、子代理指令等"以用户身份注入"的内容）。"""

    images: list[ImageContent] = field(default_factory=list)

    @property
    def role(self) -> str:
        return "user"


@dataclass
class AIMessage(BaseMessage):
    """模型输出。``tool_calls`` 非空 = 请求调用工具；为空 = 最终回答。

    **循环要不要继续，判据只有这一个。**（贯穿全书）
    """

    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: Usage = field(default_factory=Usage)
    stop_reason: str = ""  # provider 报告的停止原因：end_turn / tool_use / max_tokens…

    @property
    def role(self) -> str:
        return "assistant"

    def __repr__(self) -> str:
        if self.tool_calls:
            calls = ", ".join(f"{c.name}({c.args})" for c in self.tool_calls)
            return f"AIMessage(tool_calls=[{calls}])"
        return super().__repr__()


@dataclass
class ToolMessage(BaseMessage):
    """工具执行结果；``tool_call_id`` 回指发起它的那次 ``ToolCall.id``。

    ``is_error`` 标记"这是一次失败的执行"——错误也是喂回模型的信息，
    而不是让循环崩掉（第 2 章：错误即消息）。
    """

    tool_call_id: str = ""
    name: str = ""
    is_error: bool = False
    # Structured values live in the result store. The transcript keeps only a
    # stable reference and bounded metadata so resume does not duplicate them.
    result_ref: str = ""
    result_meta: dict[str, Any] = field(default_factory=dict)

    @property
    def role(self) -> str:
        return "tool"


AnyMessage = BaseMessage
Messages = list[BaseMessage]

_MESSAGE_TYPES = {
    "SystemMessage": SystemMessage,
    "HumanMessage": HumanMessage,
    "AIMessage": AIMessage,
    "ToolMessage": ToolMessage,
}


def to_jsonable(obj: Any) -> Any:
    """把消息 / ToolCall / Usage 递归转成可 JSON 化的 dict（带 ``__type__`` 标记）。

    会话日志（第 5 章）逐行写 JSON，靠 ``__type__`` 在读回时还原成对象。
    """
    if isinstance(obj, BaseMessage):
        d = asdict(obj)
        d["__type__"] = type(obj).__name__
        return {k: to_jsonable(v) for k, v in d.items()}
    if isinstance(obj, (ToolCall, Usage, ImageContent)):
        return asdict(obj)
    if isinstance(obj, dict):
        return {k: to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [to_jsonable(v) for v in obj]
    return obj


def from_jsonable(obj: Any) -> Any:
    """``to_jsonable`` 的逆操作：把带 ``__type__`` 的 dict 还原成消息对象。"""
    if isinstance(obj, list):
        return [from_jsonable(x) for x in obj]
    if isinstance(obj, dict):
        t = obj.get("__type__")
        if t in _MESSAGE_TYPES:
            data = {k: from_jsonable(v) for k, v in obj.items() if k != "__type__"}
            if "tool_calls" in data:
                data["tool_calls"] = [
                    ToolCall(**tc) if isinstance(tc, dict) else tc for tc in data["tool_calls"]
                ]
            if "usage" in data and isinstance(data["usage"], dict):
                data["usage"] = Usage(**data["usage"])
            if "images" in data:
                data["images"] = [
                    ImageContent(**image) if isinstance(image, dict) else image
                    for image in data["images"]
                ]
            return _MESSAGE_TYPES[t](**data)
        return {k: from_jsonable(v) for k, v in obj.items()}
    return obj
