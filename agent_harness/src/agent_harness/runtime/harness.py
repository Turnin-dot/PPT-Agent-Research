"""Harness 门面 —— 把内核与控制面组装成一个可运行的 Agent 应用（第 9-11 章）。

到这里为止，每个部件都是独立可用的；``Harness`` 只做**组装**，不再引入新机制：

    模型 + 工具族(工作区) + 技能 + MCP + 子代理     ← 能力面
    权限策略 → gate ← 钩子                          ← 控制面（编译成一个 gate）
    上下文管理（记忆文件 + 预算 + 压缩）              ← 上下文面
    会话存储（事件日志，record 透明落盘）             ← 持久化面

对照真实世界：这个类相当于 Claude Agent SDK 的 ``query()`` 入口 /
OpenAI Agents SDK 的 ``Runner``——产品（CLI/IDE/服务）都从这一个门面进出，
绝不绕过它直连模型（否则权限与审计就成了摆设）。
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from agent_harness.core import events as ev
from agent_harness.core.context import ContextManager
from agent_harness.core.events import Event
from agent_harness.core.loop import Agent
from agent_harness.core.models import BaseChatModel, get_model, init_chat_model
from agent_harness.core.toolkit import make_coding_tools
from agent_harness.core.tools import Tool

from .hooks import STOP, USER_PROMPT_SUBMIT, HookManager
from .mcp import MCPServerStdio
from .permissions import Approver, PermissionPolicy, PermissionRule
from .session import Session, SessionStore
from .skills import load_skills, make_skill_tool, skills_section
from .subagents import SubagentDef, make_task_tool

DEFAULT_SYSTEM_PROMPT = """\
你是一个严谨的任务型 Agent，在受限工作区内根据用户目标自主推进。
- 行动前读取必要的现状和证据，不臆测文件内容或工具结果。
- 根据当前上下文选择、跳过、重复或返回某项活动，不假设固定工作流。
- 具体操作通过工具完成；重要修改后读取结果并决定是否继续检查。
- 工具失败或被拒绝时不要机械重试，应调整方案或说明需要的输入。
- 区分结束当前回答与完成整个任务；回答简洁，默认使用中文。"""


@dataclass
class HarnessConfig:
    model: BaseChatModel | str | None = None  # None → 读 PPT_AGENT_MODEL
    workspace: str = "./workspace"
    system_prompt: str = DEFAULT_SYSTEM_PROMPT
    permission_mode: str = "ask"
    rules: Sequence[PermissionRule] = ()
    tool_risk: Mapping[str, str] = field(default_factory=dict)
    approver: Approver | None = None
    skills_dir: str | None = None
    mcp_servers: Sequence[MCPServerStdio] = ()  # 未 start 的实例
    subagents: Sequence[SubagentDef] = ()
    extra_tools: Sequence[Tool] = ()
    serial_tools: Sequence[str] = ()
    session_root: str = ".ppt-agent/sessions"
    max_turns: int = 40
    max_context_tokens: int = 60_000
    enable_bash: bool = True


class Harness:
    def __init__(self, cfg: HarnessConfig) -> None:
        self.cfg = cfg
        # ① 模型
        if isinstance(cfg.model, str):
            self.model: BaseChatModel = init_chat_model(cfg.model)
        else:
            self.model = cfg.model or get_model()
        # ② 控制面：权限 + 钩子 → 一个 gate
        self.policy = PermissionPolicy(
            mode=cfg.permission_mode, rules=list(cfg.rules), approver=cfg.approver
        )
        self.policy.risk.update(cfg.tool_risk)
        self.hooks = HookManager()
        self.gate = self.hooks.as_gate(self.policy.as_gate())
        # ③ 能力面：工作区工具族 + 技能 + MCP + 子代理
        self.tools: list[Tool] = make_coding_tools(
            cfg.workspace, enable_bash=cfg.enable_bash
        ) + list(cfg.extra_tools)
        self.skills = load_skills(cfg.skills_dir) if cfg.skills_dir else []
        if self.skills:
            self.tools.append(make_skill_tool(self.skills))
        self._mcp: list[MCPServerStdio] = []
        for server in cfg.mcp_servers:
            server.start()
            self._mcp.append(server)
            self.tools += server.as_tools()
        if cfg.subagents:
            self.tools.append(make_task_tool(list(cfg.subagents), self.model, gate=self.gate))
        serial_names = set(cfg.serial_tools)
        result_store = Path(cfg.workspace).resolve() / ".tool-results"
        for registered_tool in self.tools:
            registered_tool.configure_result_store(
                str(result_store), reference_root=str(Path(cfg.workspace).resolve())
            )
            if registered_tool.name in serial_names:
                registered_tool.parallel_safe = False
        # ④ 上下文面：预算 + 项目记忆 + 技能清单（第一级披露）
        self.context = ContextManager(
            max_context_tokens=cfg.max_context_tokens,
            memory_cwd=cfg.workspace,
            extra_context=skills_section(self.skills),
        )
        # ⑤ 持久化面
        self.sessions = SessionStore(cfg.session_root)

    # ---- 主入口 ----

    def run(self, prompt: str, session_id: str | None = None) -> Iterator[Event]:
        """执行一次 run：恢复(或新建)会话 → 钩子 → 内核循环 → 透明落盘。"""
        session = self.sessions.open(session_id) if session_id else self.sessions.create()
        self.last_session: Session = session
        prior = session.messages()  # 事件日志重放出历史 → 天然的多轮记忆

        r = self.hooks.fire(USER_PROMPT_SUBMIT, {"prompt": prompt})
        if r.block:
            yield Event(ev.ERROR, {"error": f"输入被钩子拒绝: {r.reason}"})
            return
        if r.add_context:
            prompt = prompt + "\n\n[hook 注入]\n" + r.add_context

        self.agent = Agent(
            model=self.model,
            tools=self.tools,
            system_prompt=self.cfg.system_prompt,
            max_turns=self.cfg.max_turns,
            context=self.context,
            gate=self.gate,
            recover_context=getattr(session, "needs_compaction_recovery", False),
        )
        for e in session.record(self.agent.run(prompt, prior_messages=prior)):
            yield e
            if e.type == ev.RUN_END:
                self.hooks.fire(STOP, {"result": e.data})

    def close(self) -> None:
        for s in self._mcp:
            s.close()
