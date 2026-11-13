from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from agent_harness.core.events import TOOL_RESULT, Event
from agent_harness.core.messages import ToolCall, ToolMessage
from agent_harness.core.toolkit import make_coding_tools
from agent_harness.core.tools import run_tool_calls, tool
from agent_harness.runtime.session import Session


class Item(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    kind: str
    score: int = Field(ge=0)


class DemoResult(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    status: Literal["ok"]
    items: list[Item]
    report_path: str = ""


def _structured_tool(value, *, renderer=None):
    @tool(result_schema=DemoResult, render_result=renderer)
    def produce() -> dict:
        """Produce a structured test value."""

        return value

    return produce


def test_structured_result_is_validated_persisted_and_not_character_sliced(tmp_path: Path):
    value = {
        "status": "ok",
        "items": [{"kind": f"item-{index}", "score": index} for index in range(800)],
    }
    produce = _structured_tool(
        value,
        renderer=lambda result: json.dumps(
            {"status": result.status, "item_count": len(result.items)}, ensure_ascii=False
        ),
    )
    produce.max_result_chars = 10
    produce.configure_result_store(str(tmp_path / ".tool-results"), reference_root=str(tmp_path))

    message = run_tool_calls(
        [ToolCall("produce", {}, id="long-result")], {"produce": produce}, parallel=False
    )[0]

    assert message.is_error is False
    assert '"item_count": 800' in message.content
    assert message.result_ref == ".tool-results/produce/long-result.json"
    assert json.loads(message.content)["result_ref"] == message.result_ref
    stored = json.loads((tmp_path / message.result_ref).read_text(encoding="utf-8"))
    assert len(stored["value"]["items"]) == 800
    assert stored["result_schema"] == "DemoResult"


def test_programmatic_call_accepts_pydantic_and_keeps_rendering_detached():
    canonical_model = DemoResult(status="ok", items=[Item(kind="original", score=1)])

    def mutating_renderer(result: DemoResult) -> str:
        result.items[0].score = 99
        return "summary"

    produce = _structured_tool(canonical_model, renderer=mutating_renderer)
    outcome = produce.invoke_result({})

    assert outcome.content == "summary"
    assert outcome.value == {
        "status": "ok",
        "items": [{"kind": "original", "score": 1}],
        "report_path": "",
    }


def test_output_validation_reports_nested_field_and_preserves_artifact_ref(tmp_path: Path):
    report = tmp_path / "already-written.json"
    report.write_text("{}", encoding="utf-8")
    produce = _structured_tool(
        {
            "status": "ok",
            "items": [{"kind": "bad", "score": "not-an-integer"}],
            "report_path": str(report),
        }
    )

    message = run_tool_calls(
        [ToolCall("produce", {}, id="invalid-output")], {"produce": produce}, parallel=False
    )[0]
    payload = json.loads(message.content)

    assert message.is_error is True
    assert payload["error_code"] == "OUTPUT_VALIDATION_FAILED"
    assert payload["field_errors"][0]["field"] == "items.0.score"
    assert str(report) in payload["artifact_refs"]
    assert payload["retryable"] is False


def test_output_validation_locates_missing_field_and_illegal_enum():
    missing = _structured_tool({"items": []})
    illegal = _structured_tool({"status": "failed", "items": []})

    missing_message = run_tool_calls(
        [ToolCall("produce", {}, id="missing-field")], {"produce": missing}, parallel=False
    )[0]
    illegal_message = run_tool_calls(
        [ToolCall("produce", {}, id="illegal-enum")], {"produce": illegal}, parallel=False
    )[0]

    missing_payload = json.loads(missing_message.content)
    illegal_payload = json.loads(illegal_message.content)
    assert missing_payload["field_errors"][0]["field"] == "status"
    assert illegal_payload["field_errors"][0]["field"] == "status"
    assert illegal_payload["field_errors"][0]["type"] == "literal_error"


def test_render_failure_keeps_canonical_result_reference(tmp_path: Path):
    def fail_render(_result: BaseModel) -> str:
        raise RuntimeError("summary template broke")

    produce = _structured_tool({"status": "ok", "items": []}, renderer=fail_render)
    produce.configure_result_store(str(tmp_path / "results"), reference_root=str(tmp_path))
    message = run_tool_calls(
        [ToolCall("produce", {}, id="render-failure")], {"produce": produce}, parallel=False
    )[0]
    payload = json.loads(message.content)

    assert payload["error_code"] == "RESULT_RENDER_FAILED"
    assert message.result_ref == "results/produce/render-failure.json"
    assert (tmp_path / message.result_ref).is_file()


def test_persistence_failure_is_distinct_and_warns_about_side_effects(tmp_path: Path):
    blocked = tmp_path / "not-a-directory"
    blocked.write_text("occupied", encoding="utf-8")
    artifact = tmp_path / "business-output.json"
    artifact.write_text("{}", encoding="utf-8")
    produce = _structured_tool({"status": "ok", "items": [], "report_path": str(artifact)})
    produce.configure_result_store(str(blocked), reference_root=str(tmp_path))
    message = run_tool_calls(
        [ToolCall("produce", {}, id="persist-failure")], {"produce": produce}, parallel=False
    )[0]
    payload = json.loads(message.content)

    assert payload["error_code"] == "RESULT_PERSIST_FAILED"
    assert str(artifact) in payload["artifact_refs"]
    assert "可能已产生文件或修改" in payload["side_effect_notice"]


def test_tool_result_reference_survives_event_and_session_replay(tmp_path: Path):
    session = Session(str(tmp_path / "session.jsonl"), "session")
    original = ToolMessage(
        content='{"status":"ok"}',
        tool_call_id="call-1",
        name="produce",
        result_ref=".tool-results/produce/call-1.json",
        result_meta={"result_schema": "DemoResult", "artifact_refs": ["report.json"]},
    )
    session.append(Event(TOOL_RESULT, {"message": original}))

    restored = session.messages()[0]
    assert isinstance(restored, ToolMessage)
    assert restored.result_ref == original.result_ref
    assert restored.result_meta == original.result_meta


def test_legacy_text_tool_remains_compatible():
    @tool
    def echo(value: str) -> str:
        """Echo text."""

        return value

    assert echo.invoke({"value": "hello"}) == "hello"


def test_long_command_output_spills_to_readable_workspace_reference(tmp_path: Path):
    tools = {
        item.name: item
        for item in make_coding_tools(str(tmp_path), max_output_chars=80, enable_bash=True)
    }
    command = f'"{sys.executable}" -c "print(\'x\' * 500)"'
    message = run_tool_calls(
        [ToolCall("bash", {"command": command}, id="long-command")],
        tools,
        parallel=False,
    )[0]

    assert message.is_error is False
    marker = "result_ref="
    assert marker in message.content
    result_ref = message.content.split(marker, 1)[1].split("；", 1)[0]
    assert (tmp_path / result_ref).read_text(encoding="utf-8").strip() == "x" * 500
