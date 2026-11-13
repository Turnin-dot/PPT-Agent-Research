from __future__ import annotations

from typing import Any

from agent_harness.core.tools import Tool, tool

from .config import PdfAssetConfig
from .result_schemas import (
    CropPdfAssetResult,
    ParsePdfResult,
    PreparePdfAssetsResult,
    RegisterPdfAssetIssueResult,
    ReRecognizePdfRegionResult,
    ReviewPdfAssetsResult,
    UpdateAssetMappingResult,
    ValidatePdfAssetManifestResult,
    ViewPdfPageResult,
    render_manifest_validation,
    render_mutation_result,
    render_page_result,
    render_parse_result,
    render_prepare_result,
    render_review_result,
)
from .service import PdfAssetService
from .tool_schemas import (
    CropPdfAssetInput,
    ParsePdfInput,
    PreparePdfAssetsInput,
    RegisterPdfAssetIssueInput,
    ReRecognizePdfRegionInput,
    ReviewPdfAssetsInput,
    UpdateAssetMappingInput,
    ValidatePdfAssetManifestInput,
    ViewPdfPageInput,
)


def make_pdf_asset_tools(config: PdfAssetConfig) -> list[Tool]:
    """Create Harness-native tools over one shared PDF asset service."""

    service = PdfAssetService(config)

    @tool(
        name="parse_pdf",
        args_schema=ParsePdfInput,
        result_schema=ParsePdfResult,
        render_result=render_parse_result,
    )
    def parse_pdf_tool(
        pdf_path: str,
        result_dir: str = "",
        force: bool = False,
        page_start: int | None = None,
        page_end: int | None = None,
        allow_unverified_reuse: bool = False,
        vlm_result_dir: str = '',
    ) -> dict[str, Any]:
        """解析或复用 PDF 的 MinerU 结果，创建带版本的候选资产清单；解析成功不等于核对通过。"""
        return service.parse_pdf(
            pdf_path,
            result_dir=result_dir,
            force=force,
            page_start=page_start,
            page_end=page_end,
            allow_unverified_reuse=allow_unverified_reuse,
            vlm_result_dir=vlm_result_dir,
        )

    @tool(
        name="view_pdf_page",
        args_schema=ViewPdfPageInput,
        result_schema=ViewPdfPageResult,
        render_result=render_page_result,
    )
    def view_pdf_page_tool(
        pdf_path: str, page_number: int, output_dir: str = "", describe: bool = False
    ) -> dict[str, Any]:
        """只读渲染一个 1-based PDF 页面；describe=true 才会把实际图像传给视觉模型。"""
        return service.view_pdf_page(
            pdf_path, page_number, output_dir=output_dir, describe=describe
        )

    @tool(
        name="review_pdf_assets",
        args_schema=ReviewPdfAssetsInput,
        result_schema=ReviewPdfAssetsResult,
        render_result=render_review_result,
    )
    def review_pdf_assets_tool(
        manifest_path: str, asset_ids: list[str], page_numbers: list[int]
    ) -> dict[str, Any]:
        """用 DeepSeek Flash 视觉核对 manifest 的完整或指定范围；空范围表示整份，工具只保存报告、不修复资产。"""
        return service.review_pdf_assets(
            manifest_path,
            asset_ids=asset_ids,
            page_numbers=page_numbers,
        )

    @tool(
        name="crop_pdf_asset",
        args_schema=CropPdfAssetInput,
        result_schema=CropPdfAssetResult,
        render_result=render_mutation_result,
    )
    def crop_pdf_asset_tool(
        manifest_path: str,
        page_number: int,
        bbox: list[float],
        asset_id: str = "",
        asset_type: str = "image",
        coordinate_space: str = "pdf_points",
    ) -> dict[str, Any]:
        """按明确坐标从原页重裁剪或新建资产；写入新版本，并使旧核对报告过期。"""
        return service.crop_asset(
            manifest_path,
            page_number,
            bbox,
            asset_id=asset_id,
            asset_type=asset_type,
            coordinate_space=coordinate_space,
        )

    @tool(
        name="update_asset_mapping",
        args_schema=UpdateAssetMappingInput,
        result_schema=UpdateAssetMappingResult,
        render_result=render_mutation_result,
    )
    def update_asset_mapping_tool(
        manifest_path: str, asset_id: str, caption: str, figure_number: str = ""
    ) -> dict[str, Any]:
        """依据原页证据更新现有资产的图注和编号配对；写入新版本并使旧报告过期。"""
        return service.update_mapping(
            manifest_path, asset_id, caption=caption, figure_number=figure_number
        )

    @tool(
        name="register_pdf_asset_issue",
        args_schema=RegisterPdfAssetIssueInput,
        result_schema=RegisterPdfAssetIssueResult,
        render_result=render_mutation_result,
    )
    def register_pdf_asset_issue_tool(
        manifest_path: str,
        page_number: int,
        issue_type: str,
        description: str,
        asset_id: str = "",
    ) -> dict[str, Any]:
        """登记缺失、疑点或无法恢复的问题；不修改现有资产，也不表示问题已修复。"""
        return service.register_issue(
            manifest_path,
            page_number,
            issue_type,
            description,
            asset_id=asset_id,
        )

    @tool(
        name="re_recognize_pdf_region",
        args_schema=ReRecognizePdfRegionInput,
        result_schema=ReRecognizePdfRegionResult,
        render_result=render_mutation_result,
    )
    def re_recognize_pdf_region_tool(
        manifest_path: str,
        page_number: int,
        bbox: list[float],
        recognition_kind: str,
        asset_id: str = "",
    ) -> dict[str, Any]:
        """裁剪指定区域并把实际图像交给 DeepSeek Flash 重识别文本、表格或公式；会写入新资产版本。"""
        return service.re_recognize_region(
            manifest_path,
            page_number,
            bbox,
            recognition_kind=recognition_kind,
            asset_id=asset_id,
        )

    @tool(
        name="validate_pdf_asset_manifest",
        args_schema=ValidatePdfAssetManifestInput,
        result_schema=ValidatePdfAssetManifestResult,
        render_result=render_manifest_validation,
    )
    def validate_pdf_asset_manifest_tool(
        manifest_path: str,
        check_source_hash: bool = True,
        check_asset_files: bool = True,
        page_numbers: list[int] | None = None,
    ) -> dict[str, Any]:
        """只读验证资产清单结构、对象引用、文件与版本适用性；不执行视觉核对。"""
        return service.validate_manifest(
            manifest_path,
            check_source_hash=check_source_hash,
            check_asset_files=check_asset_files,
            page_numbers=page_numbers,
        )

    @tool(
        name="prepare_pdf_assets",
        args_schema=PreparePdfAssetsInput,
        result_schema=PreparePdfAssetsResult,
        render_result=render_prepare_result,
    )
    def prepare_pdf_assets_tool(
        pdf_path: str,
        result_dir: str = "",
        page_numbers: list[int] | None = None,
        auto_repair: bool = False,
        allow_unverified_reuse: bool = False,
    ) -> dict[str, Any]:
        """组合执行解析、指定范围视觉核对和可选的有限安全重裁剪；保留部分成果与未解决问题。"""
        return service.prepare_pdf_assets(
            pdf_path,
            result_dir=result_dir,
            page_numbers=page_numbers or [],
            auto_repair=auto_repair,
            allow_unverified_reuse=allow_unverified_reuse,
        )

    return [
        parse_pdf_tool,
        view_pdf_page_tool,
        review_pdf_assets_tool,
        crop_pdf_asset_tool,
        update_asset_mapping_tool,
        register_pdf_asset_issue_tool,
        re_recognize_pdf_region_tool,
        validate_pdf_asset_manifest_tool,
        prepare_pdf_assets_tool,
    ]
