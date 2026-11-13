"""Internal output contracts. Extensions survive; core status/ref types are strict."""
from __future__ import annotations

import json
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, model_validator
from .paper_context import PaperContextResult
from ..pdf_assets.reliability import TableVerification, EvidenceQuality

Revision=Annotated[StrictInt,Field(ge=1)]


class Result(BaseModel):
    # Prototype report diagnostics grow independently; preserve such fields in
    # canonical results, while refusing coercion of IDs, versions and verdicts.
    model_config=ConfigDict(extra='allow',strict=True)
    execution_status: Literal['succeeded']


class Ref(BaseModel):
    model_config=ConfigDict(extra='allow',strict=True)
    object_id: str
    version: Revision
    path: str


class EvidenceRecord(BaseModel):
    model_config=ConfigDict(extra='allow',strict=True)
    evidence_id: str
    version: Revision
    source_page: Revision
    type: str
    text: str
    path: str
    source_pages: list[Revision] | None = None
    reliability: EvidenceQuality | None = None


class GetEvidenceResult(Result):
    read_only: StrictBool
    manifest_path: str
    manifest_revision: Revision
    records: list[EvidenceRecord]
    returned_count: Annotated[StrictInt,Field(ge=0)]
    matched_count: Annotated[StrictInt,Field(ge=0)]
    truncated: StrictBool
    next_cursor: dict[str,StrictInt] | None
    query: str

    @model_validator(mode='after')
    def counts(self):
        if self.returned_count!=len(self.records) or self.truncated!=(self.next_cursor is not None):
            raise ValueError('record count / continuation cursor inconsistent')
        return self


class Asset(BaseModel):
    model_config=ConfigDict(extra='allow',strict=True)
    asset_id: str
    version: Revision
    source_page: Revision
    type: str
    path: str
    captions: list[str]
    review_status: str
    description_status: str
    pixel_width: Annotated[StrictInt,Field(gt=0)] | None = None
    pixel_height: Annotated[StrictInt,Field(gt=0)] | None = None
    aspect_ratio: Annotated[float,Field(gt=0)] | None = None
    is_verified: StrictBool
    review: dict[str,Any]
    source_pages: list[Revision] | None = None
    reliability: EvidenceQuality | None = None


class GetAssetResult(Result):
    read_only: StrictBool
    manifest_path: str
    manifest_revision: Revision
    asset: Asset
    visual_inspection_completed: Literal[False]


class GetTaskStateResult(Result):
    task_id: str
    revision: Annotated[StrictInt,Field(ge=0)]
    task_path: str
    slide_plans: dict[str,Ref]
    slides: dict[str,dict[str,Any]]
    summary: dict[str,StrictInt]
    reference_health: dict[str,Any]


class GetThemeResult(Result):
    read_only: StrictBool
    theme: dict[str,Any]
    theme_ref: Ref | None


class UsageRecord(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    input_tokens: Annotated[StrictInt,Field(ge=0)]
    output_tokens: Annotated[StrictInt,Field(ge=0)]
    cached_tokens: Annotated[StrictInt,Field(ge=0)] | None = None
    reasoning_tokens: Annotated[StrictInt,Field(ge=0)] | None = None


class InspectImageResult(Result):
    image_path: str
    analysis: str
    internal_model: str
    model_usage: UsageRecord
    verification: TableVerification | None = None
    trace_path: str | None = None
    review_verdict: Literal['pass','needs_repair','uncertain'] | None = None


class SaveResult(Result):
    task_revision: Revision
    reused: StrictBool


class SaveBriefResult(SaveResult):
    brief_ref: Ref


class SaveThemeResult(SaveResult):
    theme_ref: Ref


class SaveOutlineResult(SaveResult):
    outline_ref: Ref


class SaveSlidePlanResult(SaveResult):
    slide_plan_ref: Ref


class SaveAssetMappingResult(SaveResult):
    asset_mapping_ref: Ref


class BindingCloseout(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    execution_status: Literal['succeeded','partial']
    html_version: Revision
    steps: dict[str,dict[str,Any]]
    failed_step: Literal['render','inspect'] | None
    error: str | None
    review_completed: Literal[False]
    progress: dict[str,Any]


class SaveSlideBindingResult(SaveResult):
    html_ref: Ref
    binding_ref: Ref
    closeout: BindingCloseout | None = None


class RenderHtmlSlideResult(SaveResult):
    preview_ref: Ref
    diagnostics: dict[str,Any]


class ReviewResult(Result):
    applicability: Literal['current','stale']
    is_verified: StrictBool
    issues: list[dict[str,Any]]
    report_path: str

    @model_validator(mode='after')
    def verified(self):
        verdict=getattr(self,'review_verdict',getattr(self,'validation_verdict',None))
        if self.is_verified and (self.applicability!='current' or verdict!='pass'):
            raise ValueError('is_verified requires a current passing report')
        return self


class InspectHtmlLayoutResult(ReviewResult):
    slide_id: str
    html_version: Revision
    review_verdict: Literal['pass','needs_revision','uncertain']
    report_version: Revision


class ReviewSlideResult(ReviewResult):
    slide_id: str
    html_version: Revision
    review_verdict: Literal['pass','needs_revision','uncertain']
    summary: str
    internal_model: str
    model_usage: UsageRecord
    attempt_count: Annotated[StrictInt,Field(ge=1)]


class ExportEditablePptxResult(Result):
    task_revision: Revision
    export: dict[str,Any]
    editable: StrictBool
    full_slide_screenshot_used: Literal[False]


class RenderPptxResult(Result):
    pptx_path: str
    pptx_sha256: str
    slides: list[dict[str,Any]]
    renderer: str
    reused: StrictBool


class ValidateExportResult(ReviewResult):
    validation_verdict: Literal['pass','needs_revision','uncertain']
    pptx_path: str
    pptx_sha256: str
    structure: dict[str,Any]


class ValidateDeliveryResult(ReviewResult):
    validation_verdict: Literal['pass','incomplete']
    task_id: str
    task_revision_checked: Annotated[StrictInt,Field(ge=0)]
    required_slide_ids: list[str]


class QueryAssetsResult(Result):
    manifest_path: str
    manifest_revision: Revision
    assets: list[Asset]
    matched_count: Annotated[StrictInt,Field(ge=0)]
    returned_count: Annotated[StrictInt,Field(ge=0)]
    next_offset: Annotated[StrictInt,Field(ge=0)] | None


class GetDocumentOverviewResult(Result):
    manifest_path: str
    manifest_revision: Revision
    page_count: Annotated[StrictInt,Field(ge=0)]
    asset_count: Annotated[StrictInt,Field(ge=0)]
    pages: list[dict[str,Any]]
    source: dict[str,Any]


RESULT_SCHEMAS={
    'get_paper_context':PaperContextResult,
    'get_task_state':GetTaskStateResult,'get_evidence':GetEvidenceResult,'get_asset':GetAssetResult,
    'get_theme':GetThemeResult,'inspect_image':InspectImageResult,'save_brief':SaveBriefResult,
    'save_theme':SaveThemeResult,'save_outline':SaveOutlineResult,'save_slide_plan':SaveSlidePlanResult,
    'save_asset_mapping':SaveAssetMappingResult,'save_slide_binding':SaveSlideBindingResult,
    'render_html_slide':RenderHtmlSlideResult,'inspect_html_layout':InspectHtmlLayoutResult,
    'review_slide':ReviewSlideResult,'export_editable_pptx':ExportEditablePptxResult,
    'render_pptx':RenderPptxResult,'validate_export':ValidateExportResult,'validate_delivery':ValidateDeliveryResult,
    'get_evidence_bundle':GetEvidenceResult,'query_assets':QueryAssetsResult,'get_document_overview':GetDocumentOverviewResult,
}


def render_result(value: BaseModel) -> str:
    """Bounded valid JSON projection, never string-slice a serialized result."""
    if isinstance(value,PaperContextResult):
        # Bounded at source segmentation; the model receives the actual page
        # material instead of another index that requires reading rich JSON.
        return json.dumps(value.model_dump(mode='json'),ensure_ascii=False,separators=(',',':'))
    data=value.model_dump(mode='json',exclude_none=True)
    if data.get('retrieval_scope') in {'single_slide','progress'}:
        # An explicitly requested page is already a bounded domain view.
        # Deliver it losslessly when modest, instead of forcing repeated reads
        # of pretty-printed artifact files. Larger views keep the normal
        # result_ref fallback; the Agent can request narrower detail_sections.
        scoped=json.dumps(dict(data,summary_only=False),ensure_ascii=False,separators=(',',':'))
        if len(scoped.encode('utf-8'))<=64000:return scoped
    def project(item,depth,string_limit,list_limit):
        if depth<0: return {'summary_omitted':True,'read_full_result':True}
        if isinstance(item,str):
            return item if len(item)<=string_limit else item[:string_limit]+'… [excerpt; full value in result_ref]'
        if isinstance(item,list):
            return [project(v,depth-1,string_limit,list_limit) for v in item[:list_limit]]
        if isinstance(item,dict):
            preferred=('asset_id','evidence_id','object_id','version','source_page','type','path','review_status',
                       'reliability','is_verified_scope','source_pages','table_footnotes','equation_numbers',
                       'is_verified','review','description_status','semantic_description','structure_description',
                       'pixel_width','pixel_height','aspect_ratio','orientation','source_ref','text','captions')
            ordered={k:item[k] for k in preferred if k in item}
            ordered.update({k:v for k,v in item.items() if k not in ordered})
            # Stable references must remain usable even when descriptions are excerpts.
            identifiers = {'path','manifest_path','report_path','pptx_path','asset_id',
                           'evidence_id','object_id','task_id','slide_id'}
            result={}
            for k,v in list(ordered.items())[:32]:
                if k=='reliability' and isinstance(v,dict):
                    # Trust boundaries must survive summary-depth reduction.
                    # Bulk verification cells remain in canonical reports.
                    keep=('states','state_basis','legacy_is_verified_scope','verified_scope',
                          'preferred_evidence','has_current_corrections','needs_visual_check')
                    result[k]={name:v[name] for name in keep if name in v}
                    result[k]['report_refs']=[{name:ref[name] for name in ('report_path','asset_version','applicability','checked_cell_count') if name in ref}
                                              for ref in v.get('report_refs',[])[:2]]
                else:
                    result[k]=v if k in identifiers and isinstance(v,str) else project(v,depth-1,string_limit,list_limit)
            return result
        return item
    # Preserve decision/status fields and exact durable object refs ahead of
    # bulk content. Full canonical data was persisted before this is invoked.
    priority=('execution_status','task_id','task_revision','revision','manifest_path','manifest_revision',
              'review_verdict','validation_verdict','applicability','is_verified','reused',
              'closeout','issue_counts','issues','dimensions','summary',
              'returned_count','matched_count','truncated','next_cursor','next_offset','reference_health',
              'brief_ref','theme_ref','outline_ref','slide_plan_ref','asset_mapping_ref','html_ref',
              'binding_ref','preview_ref','report_path','manifest_path','model_usage','attempt_count')
    if isinstance(value,ReviewSlideResult):
        # Put actionable blockers before aesthetic suggestions in the bounded
        # view. Canonical issue order/content remain unchanged in result_ref.
        data['issues']=sorted(data['issues'],key=lambda i:(not i.get('blocking',i.get('severity')=='error'),i.get('finding_type')=='optional_preference'))
    ordered={k:data[k] for k in priority if k in data}
    ordered.update({k:v for k,v in data.items() if k not in ordered})
    for depth,chars,items in [(5,360,6),(4,200,3),(3,120,2)]:
        summary=project(ordered,depth,chars,items)
        summary['summary_only']=True
        summary['collection_counts']={k:len(v) for k,v in data.items() if isinstance(v,(dict,list))}
        text=json.dumps(summary,ensure_ascii=False,indent=2)
        if len(text)<=5500: return text
    return json.dumps({'execution_status':data['execution_status'],'summary_only':True,
        'review_verdict':data.get('review_verdict',data.get('validation_verdict')),
        'report_path':data.get('report_path'),'manifest_revision':data.get('manifest_revision'),
        'task_revision':data.get('task_revision'),'collection_counts':summary['collection_counts'],
        'note':'Read result_ref for complete structured data.'},ensure_ascii=False)
