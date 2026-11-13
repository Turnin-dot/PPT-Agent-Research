from __future__ import annotations

from pathlib import Path
import json
import pytest

from agent_harness.core import FakeModel, ToolCall
from agent_harness.core.messages import ToolMessage
from ppt_agent_api.services import PPT_AGENT_SYSTEM_PROMPT, build_ppt_agent_harness
from ppt_agent_domain.pdf_assets import PdfAssetConfig

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def test_project_harness_loads_prompt_skill_and_pdf_tools(tmp_path: Path):
    model = FakeModel(
        [
            [ToolCall("read_skill", {"name": "pdf-asset-preparation"})],
            "skill loaded",
        ]
    )
    harness = build_ppt_agent_harness(
        workspace=tmp_path,
        project_root=PROJECT_ROOT,
        model=model,
        pdf_asset_config=PdfAssetConfig(
            workspace=tmp_path / "pdf_assets", model_factory=lambda: FakeModel()
        ),
    )
    list(harness.run("准备一篇论文 PDF 的资产"))
    names = {tool.name for tool in harness.tools}
    assert "read_skill" in names
    assert "prepare_pdf_assets" in names
    assert "validate_pdf_asset_manifest" in names
    assert "save_slide_plan" in names
    assert "render_html_slide" in names
    assert "export_editable_pptx" in names
    assert "validate_delivery" in names
    by_name = {tool.name: tool for tool in harness.tools}
    assert by_name["get_task_state"].parallel_safe is True
    assert by_name["inspect_image"].parallel_safe is True
    assert by_name["inspect_html_layout"].parallel_safe is False
    assert by_name["review_slide"].parallel_safe is False
    assert "可用技能" in model.calls[0][0].content
    assert "pdf-asset-preparation" in model.calls[0][0].content
    assert "ppt-production" in model.calls[0][0].content
    assert PPT_AGENT_SYSTEM_PROMPT.strip() in model.calls[0][0].content
    assert harness.context.max_context_tokens == 120_000
    results = [message for message in harness.agent.last_messages if isinstance(message, ToolMessage)]
    assert results and "PDF 资产准备决策指南" in results[0].content
    harness.close()


def test_production_profile_reduces_schemas_without_removing_review_or_delivery_guards(tmp_path):
    full=build_ppt_agent_harness(workspace=tmp_path/'full',project_root=PROJECT_ROOT,model=FakeModel())
    production=build_ppt_agent_harness(workspace=tmp_path/'production',project_root=PROJECT_ROOT,model=FakeModel(),tool_profile='production')
    try:
        names={t.name for t in production.tools}
        assert {'read_skill','get_task_state','get_asset','get_evidence','get_paper_markdown',
                'save_slide_binding','review_slide','render_html_slide','inspect_html_layout',
                'export_editable_pptx','render_pptx','validate_export','validate_delivery','view_pdf_page'}<=names
        assert not names & {'parse_pdf','prepare_pdf_assets','crop_pdf_asset','save_slide_plan','save_outline','save_brief'}
        assert names < {t.name for t in full.tools}
        size=lambda h:len(json.dumps([dict(name=t.name,description=t.description,parameters=t.parameters) for t in h.tools],ensure_ascii=False).encode('utf8'))
        assert size(production)<size(full)
        assert 'tool_profile=production' in production.cfg.system_prompt
        by_name={t.name:t for t in production.tools}
        assert not by_name['save_slide_binding'].parallel_safe and not by_name['review_slide'].parallel_safe
        assert by_name['get_task_state'].parallel_safe
    finally:
        full.close();production.close()
    with pytest.raises(ValueError,match='tool_profile'):
        build_ppt_agent_harness(workspace=tmp_path/'invalid',model=FakeModel(),tool_profile='invented')
