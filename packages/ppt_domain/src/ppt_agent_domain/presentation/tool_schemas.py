"""Pydantic contracts exposed to the main Agent for PPT production tools."""

from __future__ import annotations

from enum import Enum
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    field_validator,
    model_validator,
)
from ..pdf_assets.reliability import CellTarget

TaskId = Annotated[str, Field(min_length=1, max_length=128, description="稳定 task_id。")]
SlideId = Annotated[
    str, Field(min_length=1, max_length=128, description="稳定 slide_id，如 slide-03。")
]
NonEmptyPath = Annotated[str, Field(min_length=1, description="本机绝对路径或工具可解析路径。")]
ExpectedRevision = Annotated[
    StrictInt | None,
    Field(default=None, ge=0, description="可选乐观锁；必须等于当前 task revision。"),
]


class StrictInput(BaseModel):
    model_config = ConfigDict(extra="forbid", use_enum_values=True)


class ReviewScope(str, Enum):
    ALL = "all"
    CONTENT = "content"
    FACTS = "facts"
    VISUAL = "visual"
    LAYOUT = "layout"


class AssetPurpose(str, Enum):
    EVIDENCE = "evidence"
    ILLUSTRATION = "illustration"
    DECORATION = "decoration"
    BACKGROUND = "background"


class ObjectRef(StrictInput):
    object_id: Annotated[str, Field(min_length=1, description="稳定对象 ID。")]
    version: Annotated[StrictInt, Field(ge=1, description="引用的对象版本。")]
    manifest_path: NonEmptyPath | None = Field(
        default=None, description="PDF 资产引用时填写其 manifest.json。"
    )


class SlideElementBinding(StrictInput):
    element_id: Annotated[
        str,
        Field(min_length=1, description="HTML 中唯一元素 ID；导出对象映射以此为键。"),
    ]
    role: Annotated[str, Field(min_length=1, description="元素职责，如 title、figure、caption。")]
    asset_refs: list[ObjectRef] = Field(default_factory=list, description="该元素使用的资产引用。")
    evidence_refs: list[ObjectRef] = Field(
        default_factory=list, description="该元素支持的证据引用。"
    )
    generated_decoration: StrictBool = Field(
        default=False, description="是否为生成装饰；为 true 时不能当作论文证据。"
    )


class ThemeSpec(StrictInput):
    name: str = Field(default="CRA Research", min_length=1)
    width_px: Annotated[StrictInt, Field(default=1600, ge=640, le=4096)]
    height_px: Annotated[StrictInt, Field(default=900, ge=360, le=2304)]
    heading_font: str = Field(default="Microsoft YaHei", min_length=1)
    body_font: str = Field(default="Microsoft YaHei", min_length=1)
    background: str = Field(default="#F6F4EF", pattern=r"^#[0-9A-Fa-f]{6}$")
    foreground: str = Field(default="#17324D", pattern=r"^#[0-9A-Fa-f]{6}$")
    accent: str = Field(default="#C75B39", pattern=r"^#[0-9A-Fa-f]{6}$")
    muted: str = Field(default="#68747F", pattern=r"^#[0-9A-Fa-f]{6}$")
    notes: str = Field(default="")


class GetTaskStateInput(StrictInput):
    task_id: TaskId
    view: Literal['full','progress'] = Field(default='full', description='progress只读当前版本、审核状态和pending_actions，不返回HTML/历史/报告正文；需要具体内容时用full及detail_sections。')
    include_history: StrictBool = Field(default=False, description="是否包含完整 change_log。")
    slide_id: SlideId | None = Field(default=None, description="按需只读一页的当前计划、绑定、HTML和审核原始内容；省略时仅返回现有全局索引，不展开全部页面。")
    detail_sections: list[Literal['plan','binding','html','reports']] | None = Field(default=None, description="指定slide_id后按需选择所需部分；省略时取该页全部部分。避免为一个字段分页读取整份状态JSON。")


class GetEvidenceInput(StrictInput):
    manifest_path: NonEmptyPath
    evidence_ids: list[str] = Field(
        default_factory=list, description="PDF manifest 中的稳定资产 ID。"
    )
    page_numbers: list[Annotated[StrictInt, Field(ge=1)]] = Field(
        default_factory=list, description="可选来源页范围，1-based。"
    )
    query: str = Field(default="", description="可选关键词；匹配所选资产的正文、图注、表格及语义/结构描述。过期描述只定位候选，不能作当前证据。")
    max_chars: Annotated[StrictInt, Field(default=12000, ge=500, le=50000)]
    offset: Annotated[StrictInt, Field(default=0, ge=0, description="匹配记录索引；继续读取时使用 next_cursor.offset。")]
    text_offset: Annotated[StrictInt, Field(default=0, ge=0, description="首条记录字符偏移；超长单条内容可继续读取。")]


class GetAssetInput(StrictInput):
    manifest_path: NonEmptyPath
    asset_id: Annotated[str, Field(min_length=1, description="PDF manifest 中的 asset_id。")]
    expected_version: Annotated[StrictInt | None, Field(default=None, ge=1)]
    include_text: StrictBool = Field(default=True)
    include_raw: StrictBool = Field(default=False,description="是否把原始资产记录放入完整规范结果；通常不需要，避免重复正文。")


class QueryAssetsInput(StrictInput):
    manifest_path: NonEmptyPath
    page_numbers: list[Annotated[StrictInt,Field(ge=1)]] = Field(default_factory=list)
    asset_types: list[Annotated[str,Field(pattern='^(text|image|table|equation)$')]] = Field(default_factory=list)
    query: str = Field(default='',description="匹配正文、图注、表格及图像描述；过期描述仅定位候选，不作为当前证据。")
    offset: Annotated[StrictInt,Field(default=0,ge=0)]
    limit: Annotated[StrictInt,Field(default=30,ge=1,le=100)]


class GetDocumentOverviewInput(StrictInput):
    manifest_path: NonEmptyPath


class GetPaperContextInput(StrictInput):
    manifest_path: NonEmptyPath
    segment_index: Annotated[StrictInt,Field(default=0,ge=0,description='资料分段索引，0-based；不是PDF页码。')]
    input_budget_tokens: Annotated[StrictInt,Field(default=80000,ge=512,le=200000,
        description='单段原始资料的本地估算预算，不是服务商额度；调用方另留工具/提示词/输出空间。读取后续段时保持相同值。')]


class GetThemeInput(StrictInput):
    task_id: TaskId


class InspectImageInput(StrictInput):
    image_path: str = Field(default="", description="直接检查的本地图像；与 manifest 资产二选一。")
    manifest_path: str = Field(default="", description="PDF asset manifest 路径。")
    asset_id: str = Field(default="", description="配合 manifest_path 定位图像资产。")
    expected_version: Annotated[StrictInt | None, Field(default=None, ge=1)]
    prompt: str = Field(
        default="描述图像的可见内容、可读文字、裁剪完整性和清晰度；不要猜测不可见信息。",
        min_length=3,
    )
    task_id: str = Field(default="", description="可选；填写后把完整检查报告保存到该任务。")
    table_cells: list[CellTarget] = Field(default_factory=list,max_length=100,
        description='可选：仅核实这些表格单元格并保存独立证据记录，不覆盖原HTML；必须使用manifest资产。')
    table_header_rows: Annotated[StrictInt,Field(ge=0,le=10)] = Field(default=0,
        description='原HTML表头行数，目标row从其后的第一条数据行开始计数；不自动猜测。')

    @model_validator(mode="after")
    def validate_source(self) -> "InspectImageInput":
        direct = bool(self.image_path)
        asset = bool(self.manifest_path and self.asset_id)
        if direct == asset:
            raise ValueError("必须且只能提供 image_path，或 manifest_path + asset_id")
        if self.table_cells and not asset:
            raise ValueError('table_cells requires manifest_path + asset_id')
        if len({(c.row,c.column) for c in self.table_cells})!=len(self.table_cells):
            raise ValueError('table_cells contains duplicate coordinates')
        return self


class SaveBriefInput(StrictInput):
    task_id: TaskId
    user_goal: Annotated[str, Field(min_length=3, description="用户当前目标。")]
    audience: str = Field(default="")
    language: str = Field(default="zh-CN")
    target_slide_count: Annotated[StrictInt | None, Field(default=None, ge=1, le=100)]
    delivery_requirements: list[str] = Field(default_factory=list)
    source_manifest_paths: list[str] = Field(default_factory=list)
    expected_task_revision: ExpectedRevision = None


class SaveThemeInput(StrictInput):
    task_id: TaskId
    theme: ThemeSpec
    expected_task_revision: ExpectedRevision = None


class OutlineItem(StrictInput):
    slide_id: SlideId
    title: Annotated[str, Field(min_length=1)]
    purpose: Annotated[str, Field(min_length=1)]


class SaveOutlineInput(StrictInput):
    task_id: TaskId
    title: Annotated[str, Field(min_length=1)]
    narrative: str = Field(default="")
    slides: Annotated[list[OutlineItem], Field(min_length=1)]
    expected_task_revision: ExpectedRevision = None

    @field_validator("slides")
    @classmethod
    def unique_slides(cls, value: list[OutlineItem]) -> list[OutlineItem]:
        ids = [item.slide_id for item in value]
        if len(ids) != len(set(ids)):
            raise ValueError("outline slide_id 必须唯一")
        return value


class SaveSlidePlanInput(StrictInput):
    task_id: TaskId
    slide_id: SlideId
    goal: Annotated[str, Field(min_length=3)]
    content_markdown: Annotated[str, Field(min_length=1)]
    layout_intent: str = Field(default="")
    asset_refs: list[ObjectRef] = Field(default_factory=list)
    evidence_refs: list[ObjectRef] = Field(default_factory=list)
    theme_version: Annotated[StrictInt | None, Field(default=None, ge=1)]
    expected_task_revision: ExpectedRevision = None


class SaveAssetMappingInput(StrictInput):
    task_id: TaskId
    mapping_id: Annotated[str, Field(min_length=1, max_length=128)]
    asset_ref: ObjectRef
    alias: str = Field(default="")
    purpose: AssetPurpose = Field(default=AssetPurpose.EVIDENCE)
    notes: str = Field(default="")
    expected_task_revision: ExpectedRevision = None


class SaveSlideBindingInput(StrictInput):
    task_id: TaskId
    slide_id: SlideId
    html_path: NonEmptyPath
    elements: Annotated[list[SlideElementBinding], Field(min_length=1)]
    expected_plan_version: Annotated[StrictInt | None, Field(default=None, ge=1)]
    expected_task_revision: ExpectedRevision = None
    check_layout: StrictBool = Field(default=False, description='true时保存绑定后由程序完成渲染和布局检查；失败保留已保存版本，重复调用可恢复。不会调用模型或代替审核。')

    @field_validator("elements")
    @classmethod
    def unique_elements(cls, value: list[SlideElementBinding]) -> list[SlideElementBinding]:
        ids = [item.element_id for item in value]
        if len(ids) != len(set(ids)):
            raise ValueError("binding element_id 必须唯一")
        return value


class RenderHtmlSlideInput(StrictInput):
    task_id: TaskId
    slide_id: SlideId
    html_version: Annotated[StrictInt | None, Field(default=None, ge=1)]
    force: StrictBool = Field(default=False)


class InspectHtmlLayoutInput(StrictInput):
    task_id: TaskId
    slide_id: SlideId
    html_version: Annotated[StrictInt | None, Field(default=None, ge=1)]
    minimum_font_px: Annotated[StrictInt, Field(default=18, ge=8, le=72)]
    force_render: StrictBool = Field(default=False)


class ReviewSlideInput(StrictInput):
    task_id: TaskId
    slide_id: SlideId
    html_version: Annotated[StrictInt | None, Field(default=None, ge=1)]
    scope: ReviewScope = Field(default=ReviewScope.ALL)
    force: StrictBool = Field(default=False)


class ExportEditablePptxInput(StrictInput):
    task_id: TaskId
    slide_ids: list[SlideId] = Field(
        default_factory=list, description="空列表表示按 outline/current plans。"
    )
    output_path: str = Field(default="", description="可选输出 .pptx；留空写入任务 exports 目录。")
    expected_task_revision: ExpectedRevision = None


class RenderPptxInput(StrictInput):
    task_id: TaskId
    pptx_path: str = Field(default="", description="留空时使用任务最新导出。")
    force: StrictBool = Field(default=False)


class ValidateExportInput(StrictInput):
    task_id: TaskId
    pptx_path: str = Field(default="", description="留空时使用任务最新导出。")
    require_editable_text: StrictBool = Field(default=True)
    require_independent_images: StrictBool = Field(default=True)
    compare_rendered_previews: StrictBool = Field(default=True)


class ValidateDeliveryInput(StrictInput):
    task_id: TaskId
    required_slide_ids: list[SlideId] = Field(default_factory=list)
    require_current_reviews: StrictBool = Field(default=True)
    require_export_validation: StrictBool = Field(default=True)
    allow_unresolved_warnings: StrictBool = Field(default=True)
