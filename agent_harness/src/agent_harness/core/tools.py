"""Harness-native tool definitions, validation, execution and result projection.

Input schemas are model-facing. Optional result schemas are internal runtime
contracts: a structured tool returns one canonical business value, the runtime
validates and persists it, and ``render_result`` projects a bounded summary for
the model. Legacy text tools remain supported without a result schema.
"""

from __future__ import annotations

import inspect
import json
import os
import re
import tempfile
import uuid
import time
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, get_type_hints

from pydantic import BaseModel, ValidationError

from .messages import ToolCall, ToolMessage

_PY_TO_JSON = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
    list: "array",
    dict: "object",
}


def _build_parameters(func: Callable) -> dict[str, Any]:
    """Build a small JSON Schema for legacy tools without a Pydantic model."""
    sig = inspect.signature(func)
    try:
        hints = get_type_hints(func)
    except Exception:
        hints = {}
    properties: dict[str, Any] = {}
    required: list[str] = []
    for pname, param in sig.parameters.items():
        if pname in ("self", "cls"):
            continue
        json_type = _PY_TO_JSON.get(hints.get(pname, str), "string")
        properties[pname] = {"type": json_type}
        if param.default is inspect.Parameter.empty:
            required.append(pname)
    return {"type": "object", "properties": properties, "required": required}


def _validation_details(error: ValidationError) -> list[dict[str, str]]:
    details: list[dict[str, str]] = []
    for item in error.errors(include_url=False):
        location = ".".join(str(part) for part in item.get("loc", ())) or "result"
        details.append(
            {
                "field": location,
                "reason": str(item.get("msg", "invalid value")),
                "type": str(item.get("type", "validation_error")),
            }
        )
    return details


def _extract_artifact_refs(value: Any) -> list[str]:
    """Best-effort paths retained when validation fails after side effects."""
    refs: list[str] = []

    def visit(candidate: Any, key: str = "") -> None:
        if isinstance(candidate, BaseModel):
            visit(candidate.model_dump(mode="python"), key)
        elif isinstance(candidate, dict):
            for child_key, child in candidate.items():
                visit(child, str(child_key))
        elif isinstance(candidate, (list, tuple)):
            for child in candidate:
                visit(child, key)
        elif (
            isinstance(candidate, str)
            and candidate
            and (
                key == "path"
                or key.endswith("_path")
                or key.endswith("_ref")
                or key in {"manifest", "report", "result_ref"}
            )
        ):
            refs.append(candidate)

    visit(value)
    return list(dict.fromkeys(refs))[:50]


class ToolInputValidationError(ValueError):
    """A model-correctable tool argument error with stable field details."""

    def __init__(self, tool_name: str, error: ValidationError) -> None:
        self.field_errors = _validation_details(error)
        lines = [f"- {item['field']}: {item['reason']}" for item in self.field_errors]
        super().__init__(
            f"工具 {tool_name!r} 的参数未通过校验。请根据工具 Schema 修正后再调用：\n"
            + "\n".join(lines)
        )


class ToolOutputValidationError(ValueError):
    """A tool body returned a value that violates its declared result schema."""

    def __init__(self, tool_name: str, error: ValidationError, raw_result: Any) -> None:
        self.field_errors = _validation_details(error)
        self.artifact_refs = _extract_artifact_refs(raw_result)
        lines = [f"- {item['field']}: {item['reason']}" for item in self.field_errors]
        super().__init__(
            f"工具 {tool_name!r} 的业务结果未通过输出 Schema 校验：\n" + "\n".join(lines)
        )


class ToolResultPersistenceError(RuntimeError):
    """A canonical result could not be written to the configured result store."""

    def __init__(self, tool_name: str, cause: Exception, value: Any) -> None:
        self.artifact_refs = _extract_artifact_refs(value)
        super().__init__(f"工具 {tool_name!r} 的完整结果保存失败: {type(cause).__name__}: {cause}")


class ToolResultRenderError(RuntimeError):
    """A canonical result was valid but its model-facing projection failed."""

    def __init__(self, tool_name: str, cause: Exception, result_ref: str) -> None:
        self.result_ref = result_ref
        super().__init__(f"工具 {tool_name!r} 的结果摘要生成失败: {type(cause).__name__}: {cause}")


@dataclass(frozen=True)
class ToolInvocationResult:
    """Validated canonical value plus its model-facing projection and durable ref."""

    content: str
    value: Any = None
    result_ref: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


RenderResult = Callable[[BaseModel], str]


def _attach_result_reference(content: str, result_ref: str) -> str:
    """Add a readable ref without turning a JSON-object summary into invalid JSON."""
    try:
        rendered = json.loads(content)
    except json.JSONDecodeError:
        rendered = None
    if isinstance(rendered, dict):
        rendered["result_ref"] = result_ref
        rendered["result_ref_hint"] = (
            "Use read_file(path=result_ref, offset=..., limit=...) for the canonical result."
        )
        return json.dumps(rendered, ensure_ascii=False, indent=2)
    return (
        f"{content}\n\n[完整规范结果] result_ref={result_ref}；"
        "可使用 read_file(path=result_ref, offset=..., limit=...) 分页读取。"
    )


@dataclass
class Tool:
    """A model-callable tool with optional Pydantic input and output contracts."""

    name: str
    description: str
    parameters: dict[str, Any]
    func: Callable
    args_schema: type[BaseModel] | None = None
    result_schema: type[BaseModel] | None = None
    render_result: RenderResult | None = None
    parallel_safe: bool = True
    # Source-compatible constructor field. Global character slicing is no
    # longer performed; producers own semantic bounds and spill behavior.
    max_result_chars: int | None = None
    result_store_root: str | None = None
    result_reference_root: str | None = None

    def configure_result_store(self, root: str, *, reference_root: str | None = None) -> None:
        """Configure durable storage for canonical structured results."""
        self.result_store_root = str(Path(root).resolve())
        self.result_reference_root = str(Path(reference_root).resolve()) if reference_root else None

    def _persist_result(self, canonical: Any, call_id: str) -> str:
        if self.result_store_root is None:
            return ""
        tool_dir = Path(self.result_store_root) / re.sub(r"[^0-9A-Za-z._-]+", "-", self.name)
        safe_call_id = (
            re.sub(r"[^0-9A-Za-z._-]+", "-", call_id).strip("-_") or uuid.uuid4().hex[:12]
        )
        target = tool_dir / f"{safe_call_id}.json"
        payload = {
            "schema_version": "tool-result/v1",
            "tool_name": self.name,
            "call_id": call_id or safe_call_id,
            "result_schema": self.result_schema.__name__ if self.result_schema else "",
            "value": canonical,
        }
        temp_name = ""
        try:
            tool_dir.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                "w", encoding="utf-8", delete=False, dir=tool_dir, suffix=".tmp"
            ) as stream:
                temp_name = stream.name
                json.dump(payload, stream, ensure_ascii=False, indent=2, allow_nan=False)
                stream.write("\n")
            os.replace(temp_name, target)
        except Exception as exc:
            if temp_name:
                try:
                    os.unlink(temp_name)
                except OSError:
                    pass
            raise ToolResultPersistenceError(self.name, exc, canonical) from exc
        if self.result_reference_root:
            try:
                return target.relative_to(Path(self.result_reference_root)).as_posix()
            except ValueError:
                pass
        return str(target.resolve())

    def invoke_result(self, args: dict[str, Any], *, call_id: str = "") -> ToolInvocationResult:
        """Validate input, execute, normalize output, persist it, then render it."""
        normalized = args
        if self.args_schema is not None:
            try:
                normalized = self.args_schema.model_validate(args).model_dump()
            except ValidationError as exc:
                raise ToolInputValidationError(self.name, exc) from exc

        raw_result = self.func(**normalized)
        if self.result_schema is None:
            # Compatibility path for existing text tools. Structured domain
            # tools should declare result_schema instead of relying on repr/str.
            return ToolInvocationResult(content=str(raw_result), value=raw_result)

        try:
            validated = self.result_schema.model_validate(raw_result)
        except ValidationError as exc:
            raise ToolOutputValidationError(self.name, exc, raw_result) from exc

        # JSON mode applies declared serializers and produces a detached,
        # lossless representation suitable for reports, events and callers.
        canonical = validated.model_dump(mode="json")
        try:
            canonical = json.loads(json.dumps(canonical, ensure_ascii=False, allow_nan=False))
        except (TypeError, ValueError) as exc:
            raise ToolResultPersistenceError(self.name, exc, canonical) from exc

        result_ref = self._persist_result(canonical, call_id)
        render_copy = self.result_schema.model_validate(canonical)
        try:
            content = (
                self.render_result(render_copy)
                if self.render_result is not None
                else json.dumps(canonical, ensure_ascii=False, indent=2)
            )
            if not isinstance(content, str):
                raise TypeError("render_result must return str")
        except Exception as exc:
            raise ToolResultRenderError(self.name, exc, result_ref) from exc

        if result_ref:
            content = _attach_result_reference(content, result_ref)
        metadata = {
            "result_schema": self.result_schema.__name__,
            "artifact_refs": _extract_artifact_refs(canonical),
        }
        return ToolInvocationResult(
            content=content,
            value=canonical,
            result_ref=result_ref,
            metadata=metadata,
        )

    def invoke(self, args: dict[str, Any]) -> str:
        """Backward-compatible convenience entry returning model-facing content."""
        return self.invoke_result(args).content


def tool(
    func: Callable | None = None,
    *,
    name: str | None = None,
    max_result_chars: int | None = None,
    args_schema: type[BaseModel] | None = None,
    result_schema: type[BaseModel] | None = None,
    render_result: RenderResult | None = None,
    parallel_safe: bool = True,
):
    """Decorate a function as a Harness tool.

    ``parameters`` comes only from the input schema and remains the ordinary
    provider-facing tool declaration. ``result_schema`` is internal and is
    enforced after execution but before a success ToolMessage is emitted.
    """

    def wrap(f: Callable) -> Tool:
        return Tool(
            name=name or f.__name__,
            description=(f.__doc__ or "").strip(),
            parameters=(args_schema.model_json_schema() if args_schema else _build_parameters(f)),
            func=f,
            args_schema=args_schema,
            result_schema=result_schema,
            render_result=render_result,
            parallel_safe=parallel_safe,
            max_result_chars=max_result_chars,
        )

    return wrap(func) if func is not None else wrap


Gate = Callable[[ToolCall], None | str | ToolCall]


def _failure_message(
    code: str,
    message: str,
    *,
    field_errors: list[dict[str, str]] | None = None,
    artifact_refs: list[str] | None = None,
    result_ref: str = "",
    retryable: bool,
    suggestion: str,
) -> tuple[str, dict[str, Any]]:
    payload: dict[str, Any] = {
        "error_code": code,
        "message": message,
        "retryable": retryable,
        "suggestion": suggestion,
    }
    if field_errors:
        payload["field_errors"] = field_errors
    refs = list(artifact_refs or [])
    if result_ref:
        refs.insert(0, result_ref)
    if refs:
        payload["artifact_refs"] = list(dict.fromkeys(refs))
        payload["side_effect_notice"] = (
            "工具可能已产生文件或修改；先检查这些引用，不要自动原样重试。"
        )
    return json.dumps(payload, ensure_ascii=False, indent=2), payload


def _error_tool_message(call: ToolCall, code: str, message: str, **kwargs: Any) -> ToolMessage:
    content, payload = _failure_message(code, message, **kwargs)
    return ToolMessage(
        content=content,
        tool_call_id=call.id,
        name=call.name,
        is_error=True,
        result_ref=str((payload.get("artifact_refs") or [""])[0]),  #????
        result_meta={"error": payload},
    )


def _execute_one_impl(
    call: ToolCall,
    tools_by_name: dict[str, Tool],
    gate: Gate | None,
) -> ToolMessage:
    """Execute one call; every failure becomes a structured ToolMessage."""
    if gate is not None:
        try:
            verdict = gate(call)
        except Exception as exc:
            verdict = f"权限检查失败: {type(exc).__name__}: {exc}"
        if isinstance(verdict, str):
            return _error_tool_message(
                call,
                "PERMISSION_DENIED",
                verdict,
                retryable=False,
                suggestion="调整请求范围或取得授权后再调用。",
            )
        if isinstance(verdict, ToolCall):
            call = verdict

    registered = tools_by_name.get(call.name)
    if registered is None:
        return _error_tool_message(
            call,
            "UNKNOWN_TOOL",
            f"不存在名为 {call.name!r} 的工具",
            retryable=True,
            suggestion="检查当前工具清单并改用已注册名称。",
        )
    argument_error=call.args.get('__harness_argument_error__')
    if isinstance(argument_error,dict):
        return _error_tool_message(call,'INVALID_TOOL_ARGUMENTS_JSON',
            '模型返回的工具参数不是合法JSON对象：'+str(argument_error.get('reason','unknown')),
            retryable=True,suggestion='根据上一条工具调用中保留的 raw_arguments 重新输出完整、正确转义的JSON；内容过长时分次提交，不要原样重复。')
    try:
        outcome = registered.invoke_result(call.args, call_id=call.id)
        return ToolMessage(
            content=outcome.content,
            tool_call_id=call.id,
            name=call.name,
            result_ref=outcome.result_ref,
            result_meta=outcome.metadata,
        )
    except ToolInputValidationError as exc:
        return _error_tool_message(
            call,
            "INPUT_VALIDATION_FAILED",
            str(exc),
            field_errors=exc.field_errors,
            retryable=True,
            suggestion="根据 field_errors 和模型可见输入 Schema 修正参数。",
        )
    except ToolOutputValidationError as exc:
        return _error_tool_message(
            call,
            "OUTPUT_VALIDATION_FAILED",
            str(exc),
            field_errors=exc.field_errors,
            artifact_refs=exc.artifact_refs,
            retryable=False,
            suggestion="保留已有产物并检查工具实现或协议；不要对写操作自动原样重试。",
        )
    except ToolResultPersistenceError as exc:
        return _error_tool_message(
            call,
            "RESULT_PERSIST_FAILED",
            str(exc),
            artifact_refs=exc.artifact_refs,
            retryable=False,
            suggestion="检查结果目录权限和磁盘状态；写操作可能已经发生。",
        )
    except ToolResultRenderError as exc:
        return _error_tool_message(
            call,
            "RESULT_RENDER_FAILED",
            str(exc),
            result_ref=exc.result_ref,
            retryable=False,
            suggestion="通过 result_ref 检查规范结果并修复摘要渲染器。",
        )
    except TimeoutError as exc:
        return _error_tool_message(
            call,
            "TOOL_TIMEOUT",
            f"{type(exc).__name__}: {exc}",
            retryable=True,
            suggestion="缩小处理范围或稍后有限重试；不要重复提交已知超大输入。",
        )
    except (ValueError, TypeError, FileNotFoundError, PermissionError) as exc:
        return _error_tool_message(
            call,
            "INVALID_ARGUMENT_OR_OBJECT",
            f"{type(exc).__name__}: {exc}",
            retryable=True,
            suggestion="核对错误字段、对象引用、版本和文件范围后修正调用。",
        )
    except Exception as exc:
        return _error_tool_message(
            call,
            "EXECUTION_FAILED",
            f"{type(exc).__name__}: {exc}",
            retryable=False,
            suggestion="保留已完成成果，依据错误原因决定是否缩小范围或请求输入。",
        )


def _execute_one(call, tools_by_name, gate):
    from .metering import capture_model_calls
    started=time.perf_counter()
    with capture_model_calls() as calls:
        result=_execute_one_impl(call,tools_by_name,gate)
    result.result_meta['metrics']={
        'elapsed_seconds':time.perf_counter()-started,'attempt_count':1,
        'failed':result.is_error,'internal_model_calls':calls,
    }
    return result


def run_tool_calls(
    calls: Sequence[ToolCall],
    tools_by_name: dict[str, Tool],
    *,
    gate: Gate | None = None,
    parallel: bool = True,
    max_workers: int = 8,
) -> list[ToolMessage]:
    """Execute calls in request order, respecting per-tool serial barriers."""
    if len(calls) <= 1 or not parallel:
        return [_execute_one(c, tools_by_name, gate) for c in calls]

    results: list[ToolMessage] = []
    safe_batch: list[ToolCall] = []

    def flush_safe_batch() -> None:
        if not safe_batch:
            return
        with ThreadPoolExecutor(max_workers=min(max_workers, len(safe_batch))) as pool:
            futures = [pool.submit(_execute_one, call, tools_by_name, gate) for call in safe_batch]
            results.extend(future.result() for future in futures)
        safe_batch.clear()

    for call in calls:
        registered = tools_by_name.get(call.name)
        if registered is not None and registered.parallel_safe:
            safe_batch.append(call)
            continue
        flush_safe_batch()
        results.append(_execute_one(call, tools_by_name, gate))
    flush_safe_batch()
    return results
