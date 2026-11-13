"""Validated, model-facing argument contracts for PDF asset tools."""

from __future__ import annotations

import json
from enum import Enum
from typing import Annotated, Any

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    field_validator,
    model_validator,
)

NonEmptyPath = Annotated[
    str,
    Field(min_length=1, description="本机绝对路径或当前工作区可解析路径。"),
]
AssetId = Annotated[
    str,
    Field(min_length=1, description="当前 manifest 中稳定的 asset_id；不要使用文件名代替。"),
]
PageNumber = Annotated[
    StrictInt,
    Field(ge=1, description="PDF 页码，1-based；第一页填写 1。"),
]
MinerUPageIndex = Annotated[
    StrictInt,
    Field(ge=0, description="MinerU 解析页索引，0-based；第一页填写 0。"),
]
BBox = Annotated[
    list[float],
    Field(
        min_length=4,
        max_length=4,
        description="裁剪框 [x0,y0,x1,y1]；原点在左上，x1>x0 且 y1>y0。",
    ),
]


class CoordinateSpace(str, Enum):
    PDF_POINTS = "pdf_points"
    MINERU_NORMALIZED = "mineru_normalized_0_1000"


class AssetType(str, Enum):
    IMAGE = "image"
    TABLE = "table"
    EQUATION = "equation"
    TEXT = "text"


class RecognitionKind(str, Enum):
    TEXT = "text"
    TABLE = "table"
    EQUATION = "equation"


class IssueType(str, Enum):
    OMISSION = "omission"
    CROP = "crop"
    MAPPING = "mapping"
    TEXT = "text"
    TABLE = "table"
    EQUATION = "equation"
    UNCERTAIN = "uncertain"
    OTHER = "other"


class PdfToolInput(BaseModel):
    model_config = ConfigDict(extra="forbid", use_enum_values=True)


def _legacy_json_list(data: Any, *, old: str, new: str) -> Any:
    if not isinstance(data, dict) or old not in data:
        return data
    converted = dict(data)
    if new in converted:
        raise ValueError(f"不能同时提供 {new} 与旧字段 {old}")
    raw = converted.pop(old)
    if not isinstance(raw, str):
        raise ValueError(f"旧字段 {old} 必须是 JSON 数组字符串")
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"旧字段 {old} 不是合法 JSON: {exc.msg}") from exc
    if not isinstance(value, list):
        raise ValueError(f"旧字段 {old} 必须表示数组")
    converted[new] = value
    return converted


class ParsePdfInput(PdfToolInput):
    pdf_path: NonEmptyPath = Field(description="待解析的源 PDF 路径。")
    vlm_result_dir: str = Field(default='', description='可选离线VLM缓存目录，仅匹配公式/表格机器表示；不运行VLM解析，缺失或歧义时保留Pipeline。')
    result_dir: str = Field(
        default="",
        description="可选的既有 MinerU auto 结果目录；留空时运行本地 MinerU。",
    )
    force: StrictBool = Field(
        default=False, description="是否忽略同源同范围 manifest 缓存并重新解析。"
    )
    page_start: MinerUPageIndex | None = Field(
        default=None, description="可选解析起始页，0-based，且必须与 page_end 形成合法闭区间。"
    )
    page_end: MinerUPageIndex | None = Field(
        default=None, description="可选解析结束页，0-based、包含该页；不能小于 page_start。"
    )
    allow_unverified_reuse: StrictBool = Field(
        default=False,
        description="仅在用户明确接受来源 hash 无法验证或不一致时复用外部 MinerU 结果。",
    )

    @field_validator("page_start", "page_end", mode="before")
    @classmethod
    def accept_legacy_minus_one(cls, value: Any) -> Any:
        return None if value == -1 else value

    @model_validator(mode="after")
    def validate_range(self) -> ParsePdfInput:
        if self.page_end is not None and self.page_start is None:
            raise ValueError("提供 page_end 时必须同时提供 page_start")
        if self.page_start is not None and self.page_end is not None:
            if self.page_end < self.page_start:
                raise ValueError("page_end 不能小于 page_start")
        return self


class ViewPdfPageInput(PdfToolInput):
    pdf_path: NonEmptyPath = Field(description="源 PDF 路径。")
    page_number: PageNumber
    output_dir: str = Field(default="", description="可选页图输出目录；留空使用资产工作区。")
    describe: StrictBool = Field(
        default=False,
        description="是否把实际页图发送给内部视觉模型生成说明；false 只渲染，不等于视觉检查。",
    )


class ReviewPdfAssetsInput(PdfToolInput):
    manifest_path: NonEmptyPath = Field(description="parse_pdf 返回的 manifest_path。")
    asset_ids: list[AssetId] = Field(
        default_factory=list,
        description="可选资产范围；空列表表示不按资产 ID 限定。",
    )
    page_numbers: list[PageNumber] = Field(
        default_factory=list,
        description="可选核对页码（1-based）；空列表表示不按页限定。两个范围均空时核对整份 manifest。",
    )

    @model_validator(mode="before")
    @classmethod
    def accept_legacy_fields(cls, data: Any) -> Any:
        data = _legacy_json_list(data, old="asset_ids_json", new="asset_ids")
        return _legacy_json_list(data, old="page_numbers_json", new="page_numbers")

    @field_validator("asset_ids", "page_numbers")
    @classmethod
    def remove_duplicates(cls, value: list[Any]) -> list[Any]:
        return list(dict.fromkeys(value))


class CropPdfAssetInput(PdfToolInput):
    manifest_path: NonEmptyPath = Field(description="当前资产清单路径。")
    page_number: PageNumber
    bbox: BBox
    asset_id: str = Field(
        default="",
        description="要更新的现有 asset_id；留空表示创建新的手工派生资产。",
    )
    asset_type: AssetType = Field(default=AssetType.IMAGE, description="新建资产时的内容类型。")
    coordinate_space: CoordinateSpace = Field(
        default=CoordinateSpace.PDF_POINTS,
        description="bbox 坐标系：PDF points 或 MinerU 0..1000 归一化坐标。",
    )

    @model_validator(mode="before")
    @classmethod
    def accept_legacy_bbox(cls, data: Any) -> Any:
        return _legacy_json_list(data, old="bbox_json", new="bbox")

    @field_validator("bbox")
    @classmethod
    def validate_bbox(cls, value: list[float]) -> list[float]:
        x0, y0, x1, y1 = value
        if x0 < 0 or y0 < 0 or x1 <= x0 or y1 <= y0:
            raise ValueError("bbox 必须满足 x0>=0、y0>=0、x1>x0、y1>y0")
        return value

    @model_validator(mode="after")
    def validate_normalized_range(self) -> CropPdfAssetInput:
        if self.coordinate_space == CoordinateSpace.MINERU_NORMALIZED and max(self.bbox) > 1000:
            raise ValueError("MinerU 归一化 bbox 的坐标必须位于 0..1000")
        return self


class UpdateAssetMappingInput(PdfToolInput):
    manifest_path: NonEmptyPath = Field(description="当前资产清单路径。")
    asset_id: AssetId
    caption: str = Field(description="依据原页确认后的完整图注；允许空字符串表示清除错误图注。")
    figure_number: str = Field(default="", description="图、表或公式编号，例如 Figure 3 或 Table II。")


class RegisterPdfAssetIssueInput(PdfToolInput):
    manifest_path: NonEmptyPath = Field(description="当前资产清单路径。")
    page_number: PageNumber
    issue_type: IssueType = Field(description="问题类别。")
    description: Annotated[
        str,
        Field(min_length=3, description="具体说明缺失、疑点、证据和无法继续的原因。"),
    ]
    asset_id: str = Field(default="", description="可选关联 asset_id；漏提取且尚无对象时留空。")


class ReRecognizePdfRegionInput(PdfToolInput):
    manifest_path: NonEmptyPath = Field(description="当前资产清单路径。")
    page_number: PageNumber
    bbox: BBox
    recognition_kind: RecognitionKind = Field(description="待重新识别的内容类型。")
    asset_id: str = Field(default="", description="可选现有 asset_id；留空时创建对应类型的新资产。")

    @model_validator(mode="before")
    @classmethod
    def accept_legacy_bbox(cls, data: Any) -> Any:
        return _legacy_json_list(data, old="bbox_json", new="bbox")

    @field_validator("bbox")
    @classmethod
    def validate_bbox(cls, value: list[float]) -> list[float]:
        x0, y0, x1, y1 = value
        if x0 < 0 or y0 < 0 or x1 <= x0 or y1 <= y0:
            raise ValueError("bbox 必须满足 x0>=0、y0>=0、x1>x0、y1>y0")
        return value


class ValidatePdfAssetManifestInput(PdfToolInput):
    manifest_path: NonEmptyPath = Field(description="要检查的 manifest.json 路径。")
    check_source_hash: StrictBool = Field(
        default=True, description="是否重新计算源 PDF hash 并与 manifest 比较。"
    )
    check_asset_files: StrictBool = Field(
        default=True, description="是否检查所有已登记非空资产路径实际存在。"
    )
    page_numbers: list[PageNumber] = Field(default_factory=list,
        description="可选的 1-based 页面列表；返回这些页的有序正文、公式原文与图表描述/尺寸/核对状态。空列表只检查清单。")


class PreparePdfAssetsInput(PdfToolInput):
    pdf_path: NonEmptyPath = Field(description="待准备资产的源 PDF 路径。")
    result_dir: str = Field(default="", description="可选既有 MinerU auto 结果目录。")
    page_numbers: list[PageNumber] = Field(
        default_factory=list,
        description="本次视觉核对页码（1-based）；空列表表示正式核对整份 PDF。",
    )
    auto_repair: StrictBool = Field(
        default=False,
        description="是否在边界内自动执行报告明确建议的安全重裁剪；不会自动修复所有问题。",
    )
    allow_unverified_reuse: StrictBool = Field(
        default=False, description="是否显式允许复用无法通过源 hash 验证的 MinerU 结果。"
    )

    @model_validator(mode="before")
    @classmethod
    def accept_legacy_pages(cls, data: Any) -> Any:
        return _legacy_json_list(data, old="page_numbers_json", new="page_numbers")

    @field_validator("page_numbers")
    @classmethod
    def remove_duplicates(cls, value: list[int]) -> list[int]:
        return list(dict.fromkeys(value))
