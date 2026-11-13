from __future__ import annotations

from typing import Any

from agent_harness.core.tools import Tool, tool

from .config import PresentationConfig
from .service import PresentationService
from .result_schemas import RESULT_SCHEMAS, render_result
from .tool_schemas import (
    ExportEditablePptxInput,
    GetAssetInput,
    GetEvidenceInput,
    GetTaskStateInput,
    GetThemeInput,
    InspectHtmlLayoutInput,
    InspectImageInput,
    RenderHtmlSlideInput,
    RenderPptxInput,
    ReviewSlideInput,
    SaveAssetMappingInput,
    SaveBriefInput,
    SaveOutlineInput,
    SaveSlideBindingInput,
    SaveSlidePlanInput,
    SaveThemeInput,
    ValidateDeliveryInput,
    ValidateExportInput,
    QueryAssetsInput,
    GetDocumentOverviewInput,
    GetPaperContextInput,
)


def _result(value: dict[str, Any]) -> dict[str, Any]:
    """Compatibility helper: normalization/rendering belong to Harness now."""
    return value


def make_presentation_tools(config: PresentationConfig) -> list[Tool]:
    """Expose presentation domain operations through the existing Harness protocol."""

    service = PresentationService(config)

    @tool(name="get_task_state", args_schema=GetTaskStateInput)
    def get_task_state_tool(task_id: str, include_history: bool = False, slide_id: str | None = None, detail_sections: list[str] | None = None, view: str = 'full') -> dict[str, Any]:
        """只读状态；恢复优先view=progress查看版本和待办，查具体问题再按slide_id/detail_sections读取原文。"""
        return _result(service.get_task_state(task_id, include_history=include_history,slide_id=slide_id,detail_sections=detail_sections,view=view))

    @tool(name="get_evidence", args_schema=GetEvidenceInput)
    def get_evidence_tool(
        manifest_path: str,
        evidence_ids: list[str],
        page_numbers: list[int],
        query: str = "",
        max_chars: int = 12000,
        offset: int = 0,
        text_offset: int = 0,
    ) -> dict[str, Any]:
        """按稳定 ID、来源页或关键词读取 PDF 资产清单中的文本证据；只读且返回有界摘录。"""
        return _result(
            service.get_evidence(
                manifest_path,
                evidence_ids=evidence_ids,
                page_numbers=page_numbers,
                query=query,
                max_chars=max_chars,
                offset=offset,
                text_offset=text_offset,
            )
        )

    @tool(name="get_asset", args_schema=GetAssetInput)
    def get_asset_tool(
        manifest_path: str,
        asset_id: str,
        expected_version: int | None = None,
        include_text: bool = True,
        include_raw: bool = False,
    ) -> dict[str, Any]:
        """按 PDF manifest 的稳定 asset_id 和版本读取资产元数据；返回路径不代表已完成视觉检查。"""
        return _result(
            service.get_asset(
                manifest_path,
                asset_id,
                expected_version=expected_version,
                include_text=include_text,
                include_raw=include_raw,
            )
        )

    @tool(name="get_theme", args_schema=GetThemeInput)
    def get_theme_tool(task_id: str) -> dict[str, Any]:
        """只读任务当前 ThemeSpec；尚未保存主题时返回明确标记的内置默认值。"""
        return _result(service.get_theme(task_id))

    @tool(name="inspect_image", args_schema=InspectImageInput)
    def inspect_image_tool(
        image_path: str = "",
        manifest_path: str = "",
        asset_id: str = "",
        expected_version: int | None = None,
        prompt: str = "描述图像的可见内容、可读文字、裁剪完整性和清晰度；不要猜测不可见信息。",
        task_id: str = "",
        table_cells: list[dict] | None = None,
        table_header_rows: int = 0,
    ) -> dict[str, Any]:
        """将真实图像交给配置的独立视觉模型；table_cells按需核实指定单元格，保存派生证据，不改原HTML。"""
        return _result(
            service.inspect_image(
                image_path=image_path,
                manifest_path=manifest_path,
                asset_id=asset_id,
                expected_version=expected_version,
                prompt=prompt,
                task_id=task_id,
                table_cells=table_cells,
                table_header_rows=table_header_rows,
            )
        )

    @tool(name="save_brief", args_schema=SaveBriefInput)
    def save_brief_tool(
        task_id: str,
        user_goal: str,
        audience: str = "",
        language: str = "zh-CN",
        target_slide_count: int | None = None,
        delivery_requirements: list[str] | None = None,
        source_manifest_paths: list[str] | None = None,
        expected_task_revision: int | None = None,
    ) -> dict[str, Any]:
        """版本化保存用户目标与交付要求；相同内容幂等复用，旧 revision 写入会被拒绝。"""
        payload = {
            "user_goal": user_goal,
            "audience": audience,
            "language": language,
            "target_slide_count": target_slide_count,
            "delivery_requirements": delivery_requirements or [],
            "source_manifest_paths": source_manifest_paths or [],
        }
        return _result(
            service.save_brief(task_id, payload, expected_revision=expected_task_revision)
        )

    @tool(name="save_theme", args_schema=SaveThemeInput)
    def save_theme_tool(
        task_id: str, theme: dict[str, Any], expected_task_revision: int | None = None
    ) -> dict[str, Any]:
        """版本化保存 ThemeSpec；主题变化会使相关页面旧检查与导出结论过期。"""
        return _result(service.save_theme(task_id, theme, expected_revision=expected_task_revision))

    @tool(name="save_outline", args_schema=SaveOutlineInput)
    def save_outline_tool(
        task_id: str,
        title: str,
        slides: list[dict[str, Any]],
        narrative: str = "",
        expected_task_revision: int | None = None,
    ) -> dict[str, Any]:
        """版本化保存整套大纲；它不要求所有页面计划或 HTML 同时完成。"""
        return _result(
            service.save_outline(
                task_id,
                {"title": title, "narrative": narrative, "slides": slides},
                expected_revision=expected_task_revision,
            )
        )

    @tool(name="save_slide_plan", args_schema=SaveSlidePlanInput)
    def save_slide_plan_tool(
        task_id: str,
        slide_id: str,
        goal: str,
        content_markdown: str,
        layout_intent: str = "",
        asset_refs: list[dict[str, Any]] | None = None,
        evidence_refs: list[dict[str, Any]] | None = None,
        theme_version: int | None = None,
        expected_task_revision: int | None = None,
    ) -> dict[str, Any]:
        """保存一页目标、Markdown、资产/证据/主题引用；引用与版本在写入前校验。"""
        payload = {
            "goal": goal,
            "content_markdown": content_markdown,
            "layout_intent": layout_intent,
            "asset_refs": asset_refs or [],
            "evidence_refs": evidence_refs or [],
            "theme_version": theme_version,
        }
        return _result(
            service.save_slide_plan(
                task_id, slide_id, payload, expected_revision=expected_task_revision
            )
        )

    @tool(name="save_asset_mapping", args_schema=SaveAssetMappingInput)
    def save_asset_mapping_tool(
        task_id: str,
        mapping_id: str,
        asset_ref: dict[str, Any],
        alias: str = "",
        purpose: str = "evidence",
        notes: str = "",
        expected_task_revision: int | None = None,
    ) -> dict[str, Any]:
        """保存 PDF 资产在 PPT 任务中的别名和用途；不修改 PDF 内部图注或编号配对。"""
        return _result(
            service.save_asset_mapping(
                task_id,
                mapping_id,
                {"asset_ref": asset_ref, "alias": alias, "purpose": purpose, "notes": notes},
                expected_revision=expected_task_revision,
            )
        )

    @tool(name="save_slide_binding", args_schema=SaveSlideBindingInput)
    def save_slide_binding_tool(
        task_id: str,
        slide_id: str,
        html_path: str,
        elements: list[dict[str, Any]],
        expected_plan_version: int | None = None,
        expected_task_revision: int | None = None,
        check_layout: bool = False,
    ) -> dict[str, Any]:
        """版本化保存HTML和来源绑定；check_layout=true合并本地渲染与程序检查，按closeout恢复；不代表模型审核通过。"""
        return _result(
            service.save_slide_binding(
                task_id,
                slide_id,
                html_path,
                elements,
                expected_plan_version=expected_plan_version,
                expected_revision=expected_task_revision,
                check_layout=check_layout,
            )
        )

    @tool(name="render_html_slide", args_schema=RenderHtmlSlideInput)
    def render_html_slide_tool(
        task_id: str,
        slide_id: str,
        html_version: int | None = None,
        force: bool = False,
    ) -> dict[str, Any]:
        """用真实 Chromium 渲染已绑定 HTML，保存 PNG 与 DOM/资源诊断；不等于页面评审通过。"""
        return _result(
            service.render_html_slide(task_id, slide_id, html_version=html_version, force=force)
        )

    @tool(name="inspect_html_layout", args_schema=InspectHtmlLayoutInput)
    def inspect_html_layout_tool(
        task_id: str,
        slide_id: str,
        html_version: int | None = None,
        minimum_font_px: int = 18,
        force_render: bool = False,
    ) -> dict[str, Any]:
        """程序检查实际 DOM 的资源加载、溢出、越界、潜在遮挡和字号；报告绑定 HTML 版本。"""
        return _result(
            service.inspect_html_layout(
                task_id,
                slide_id,
                html_version=html_version,
                minimum_font_px=minimum_font_px,
                force_render=force_render,
            )
        )

    @tool(name="review_slide", args_schema=ReviewSlideInput)
    def review_slide_tool(
        task_id: str,
        slide_id: str,
        html_version: int | None = None,
        scope: str = "all",
        force: bool = False,
    ) -> dict[str, Any]:
        """自动复用/完成渲染与程序检查，独立保存Qwen内容和豆包视觉报告。区分错误、缺证和偏好；两维当前通过才可交付，无须先重复调用render/inspect。"""
        return _result(
            service.review_slide(
                task_id, slide_id, html_version=html_version, scope=scope, force=force
            )
        )

    @tool(name="export_editable_pptx", args_schema=ExportEditablePptxInput)
    def export_editable_pptx_tool(
        task_id: str,
        slide_ids: list[str],
        output_path: str = "",
        expected_task_revision: int | None = None,
    ) -> dict[str, Any]:
        """把受支持 HTML 元素导出为独立文字、图片和简单形状对象，并保存对象映射与降级清单。"""
        return _result(
            service.export_editable_pptx(
                task_id,
                slide_ids=slide_ids,
                output_path=output_path,
                expected_revision=expected_task_revision,
            )
        )

    @tool(name="render_pptx", args_schema=RenderPptxInput)
    def render_pptx_tool(task_id: str, pptx_path: str = "", force: bool = False) -> dict[str, Any]:
        """使用 Microsoft PowerPoint 实际打开并导出每页 PNG；不是 HTML 预览的别名。"""
        return _result(service.render_pptx(task_id, pptx_path=pptx_path, force=force))

    @tool(name="validate_export", args_schema=ValidateExportInput)
    def validate_export_tool(
        task_id: str,
        pptx_path: str = "",
        require_editable_text: bool = True,
        require_independent_images: bool = True,
        compare_rendered_previews: bool = True,
    ) -> dict[str, Any]:
        """检查 PPTX 对象结构，并让豆包分批对照 HTML 与 PowerPoint 的真实渲染图。"""
        return _result(
            service.validate_export(
                task_id,
                pptx_path=pptx_path,
                require_editable_text=require_editable_text,
                require_independent_images=require_independent_images,
                compare_rendered_previews=compare_rendered_previews,
            )
        )

    @tool(name="validate_delivery", args_schema=ValidateDeliveryInput)
    def validate_delivery_tool(
        task_id: str,
        required_slide_ids: list[str],
        require_current_reviews: bool = True,
        require_export_validation: bool = True,
        allow_unresolved_warnings: bool = True,
    ) -> dict[str, Any]:
        """汇总检查页面、报告、版本和导出验证；只有当前必需范围满足要求才记录任务完成。"""
        return _result(
            service.validate_delivery(
                task_id,
                required_slide_ids=required_slide_ids,
                require_current_reviews=require_current_reviews,
                require_export_validation=require_export_validation,
                allow_unresolved_warnings=allow_unresolved_warnings,
            )
        )

    @tool(name='get_evidence_bundle',args_schema=GetEvidenceInput)
    def get_evidence_bundle_tool(manifest_path: str, evidence_ids: list[str], page_numbers: list[int],
                                 query: str='', max_chars: int=12000, offset: int=0, text_offset: int=0) -> dict[str,Any]:
        """只读批量证据查询；与 get_evidence 共用实现，支持 next_cursor 续读，不内部调用模型。"""
        return service.get_evidence_bundle(manifest_path,evidence_ids=evidence_ids,page_numbers=page_numbers,
                                          query=query,max_chars=max_chars,offset=offset,text_offset=text_offset)

    @tool(name='query_assets',args_schema=QueryAssetsInput)
    def query_assets_tool(manifest_path: str, page_numbers: list[int],asset_types: list[str],
                          query: str='',offset: int=0,limit: int=30) -> dict[str,Any]:
        """按页、类型、关键词读取有界资产目录、描述、尺寸、版本和审核引用；不返回全部正文。"""
        return service.query_assets(manifest_path,page_numbers=page_numbers,asset_types=asset_types,
                                     query=query,offset=offset,limit=limit)

    @tool(name='get_document_overview',args_schema=GetDocumentOverviewInput)
    def get_document_overview_tool(manifest_path: str) -> dict[str,Any]:
        """只读论文章节线索、逐页资产计数与图表 ID 索引；不生成理解结论，不重复加载全文。"""
        return service.get_document_overview(manifest_path)

    @tool(name='get_paper_context',args_schema=GetPaperContextInput)
    def get_paper_context_tool(manifest_path: str,segment_index: int=0,input_budget_tokens: int=80000) -> dict[str,Any]:
        """只读程序组装的逐页原始资料段，含正文/图表文本、现有描述、几何、来源版本与覆盖。无模型总结；本工具返回完整本段，不需再读result_ref拼同一段。"""
        return service.get_paper_context(manifest_path,segment_index=segment_index,input_budget_tokens=input_budget_tokens)

    registered = [
        get_task_state_tool,
        get_evidence_tool,
        get_asset_tool,
        get_theme_tool,
        inspect_image_tool,
        save_brief_tool,
        save_theme_tool,
        save_outline_tool,
        save_slide_plan_tool,
        save_asset_mapping_tool,
        save_slide_binding_tool,
        render_html_slide_tool,
        inspect_html_layout_tool,
        review_slide_tool,
        export_editable_pptx_tool,
        render_pptx_tool,
        validate_export_tool,
        validate_delivery_tool,
        get_evidence_bundle_tool,
        query_assets_tool,
        get_document_overview_tool,
        get_paper_context_tool,
    ]
    for item in registered:
        item.result_schema=RESULT_SCHEMAS[item.name]
        item.render_result=render_result
        item.configure_result_store(str(service.root/'.tool-results'))
    from .markdown import MarkdownInput, MarkdownResult, read_markdown
    import json
    @tool(name='get_paper_markdown', args_schema=MarkdownInput, result_schema=MarkdownResult,
          render_result=lambda v: json.dumps(v.model_dump(mode='json'), ensure_ascii=False))
    def markdown_tool(manifest_path: str, offset: int=0, max_chars: int=24000, pdf_pages: list[int] | None=None):
        """按字符范围读原始完整 Markdown，或以 pdf_pages=[1,2] 读取重建的物理页 Markdown。"""
        return read_markdown(manifest_path, offset=offset, max_chars=max_chars, pdf_pages=pdf_pages)
    markdown_tool.configure_result_store(str(service.root/'.tool-results'))
    registered.append(markdown_tool)
    return registered
