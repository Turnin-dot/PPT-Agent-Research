from __future__ import annotations

import json

from agent_harness.core.context import ContextManager, _render_transcript
from agent_harness.core.messages import AIMessage, HumanMessage, ToolMessage
from agent_harness.core.models import FakeModel


def test_compaction_pins_user_identifiers_and_summarizes_evidence_payload() -> None:
    records = [
        {
            "evidence_id": f"text-p{i:04d}-001",
            "type": "text",
            "source_page": i,
            "version": 1,
            "text": "large evidence body " * 200,
        }
        for i in range(1, 16)
    ]
    tool = ToolMessage(
        name="get_evidence",
        tool_call_id="call-1",
        content=json.dumps(
            {
                "execution_status": "succeeded",
                "manifest_revision": 5,
                "returned_count": 15,
                "records": records,
            }
        ),
    )
    transcript = _render_transcript([tool])
    assert "text-p0015-001" in transcript
    assert "large evidence body" not in transcript

    model = FakeModel([AIMessage(content="已读 1-15 页，下一步保存 outline。")])
    messages = [
        HumanMessage(
            content=(
                "制作整套 PPT。task_id=cra-bpnet-full-autonomous-doubao-run01; "
                "manifest=D:/assets/manifest.json"
            )
        ),
        AIMessage(content="", tool_calls=[]),
        tool,
        HumanMessage(content="继续同一任务，不要全量复核 PDF。"),
        AIMessage(content="recent-1"),
        AIMessage(content="recent-2"),
    ]
    compacted = ContextManager(keep_recent=2).compact(messages, model)
    assert "cra-bpnet-full-autonomous-doubao-run01" in compacted[0].content
    assert "不要全量复核 PDF" in compacted[0].content
    assert "已读 1-15 页" in compacted[0].content
