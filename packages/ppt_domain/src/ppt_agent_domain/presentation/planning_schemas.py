"""Versioned paper understanding and planning contracts; no lifecycle scheduling."""
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator


class Record(BaseModel):
    model_config = ConfigDict(extra='forbid')


class EvidenceRef(Record):
    object_id: str = Field(min_length=1, description='现有 Manifest 稳定资产 ID，正文也用其 asset_id。')
    version: Annotated[StrictInt, Field(ge=1)]
    source_page: Annotated[StrictInt, Field(ge=1, description='PDF 物理页码，1-based。')]


class Claim(Record):
    statement: str = Field(min_length=1, description='简明事实/归纳；数字须明确指标、数据集和测试条件。')
    claim_kind: Literal['fact', 'synthesis', 'uncertain']
    evidence_refs: list[EvidenceRef] = Field(min_length=1)


class MethodModule(Claim):
    name: str = Field(description='保留论文原始模块名。')
    related_asset_ids: list[str] = Field(description='实际相关图表的 asset_id，可为空。')


class PaperUnderstanding(Record):
    title: str
    authors: list[str]
    journal: str
    publication_year: Annotated[StrictInt, Field(ge=2000,le=2100)] | None = Field(description='可核实的出版年份；证据缺失时填null并说明不确定，禁止为满足Schema猜测。')
    research_direction: str
    task: Claim
    background: Claim
    prior_limitations: list[Claim]
    research_problem: Claim
    inputs_outputs: Claim
    method_overview: Claim
    modules: list[MethodModule]
    innovations: list[Claim]
    datasets: list[Claim]
    experiment_setup: list[Claim]
    baseline_methods: list[str]
    evaluation_metrics: list[str]
    key_results: list[Claim]
    ablations: list[Claim]
    conclusions: list[Claim]
    limitations: list[Claim]
    source_ambiguities: list[Claim] = Field(description='原文自身不一致或不能可靠确认的内容；没有时为空。')


class Section(Record):
    name: str
    slide_indices: list[Annotated[StrictInt, Field(ge=1)]]
    rationale: str


class SlidePlan(Record):
    slide_index: Annotated[StrictInt, Field(ge=1)]
    slide_title: str = Field(min_length=1)
    slide_purpose: str
    key_message: str
    main_points: list[str] = Field(min_length=1,description='适合页面展示的短要点；详细解释放讲解提纲。')
    evidence_refs: list[EvidenceRef] = Field(min_length=1)
    asset_ids: list[str] = Field(description='实际使用的图片/表格 ID，可为空；版本在 evidence_refs 中。')
    layout_intent: str
    speaker_notes_outline: list[str]
    estimated_density: Literal['low','medium','high']


class PresentationPlan(Record):
    presentation_goal: str
    target_audience: str
    core_message: str
    narrative_structure: list[str]
    section_allocation: list[Section]
    page_count_rationale: str
    slides: list[SlidePlan] = Field(min_length=1,max_length=30)
    cross_page_consistency: list[str] = Field(description='实际检查过的重复、顺序、证据及跨页一致性结论；不作质量自评分。')

    @model_validator(mode='after')
    def indices(self):
        expected=list(range(1,len(self.slides)+1))
        if [s.slide_index for s in self.slides] != expected:
            raise ValueError('slide_index must be consecutive, ordered, 1-based')
        allocated=[i for section in self.section_allocation for i in section.slide_indices]
        if sorted(allocated)!=expected:
            raise ValueError('section_allocation must cover each slide exactly once')
        return self


class PlanningSubmission(Record):
    paper_understanding: PaperUnderstanding
    presentation_plan: PresentationPlan


class UnderstandingSubmission(Record):
    paper_understanding: PaperUnderstanding


class PlanSubmission(Record):
    presentation_plan: PresentationPlan


class UnderstandingResult(Record):
    execution_status: Literal['succeeded']
    paper_understanding_path: str
    next_action: Literal['submit_presentation_plan']


class SubmissionResult(Record):
    execution_status: Literal['succeeded']
    planning_complete: Literal[True]
    slide_count: StrictInt
    paper_understanding_path: str
    presentation_plan_path: str
    task_path: str
    downstream_plan_count: StrictInt
    reference_validation: Literal['pass']


def check_references(submission: PlanningSubmission, manifest: dict) -> dict:
    assets={a['asset_id']:a for a in manifest['assets']}
    from ppt_agent_domain.pdf_assets.provenance import source_mapping
    physical=source_mapping(manifest)[0]
    refs=[];bad=[];visuals=[]
    def visit(value):
        if isinstance(value,dict):
            if {'object_id','version','source_page'} <= value.keys():refs.append(value)
            for child in value.values():visit(child)
        elif isinstance(value,list):
            for child in value:visit(child)
    visit(submission.model_dump())
    for r in refs:
        asset=assets.get(r['object_id'])
        if not asset:bad.append(dict(**r,reason='unknown_id'))
        elif r['version']!=asset.get('version',1):bad.append(dict(**r,reason='stale_version'))
        elif r['source_page'] not in physical.get(r['object_id'],{}).get('source_pages',[asset['source_page']]):bad.append(dict(**r,reason='wrong_page'))
    for module in submission.paper_understanding.modules:
        visuals.extend(module.related_asset_ids)
    for slide in submission.presentation_plan.slides:
        visuals.extend(slide.asset_ids)
        ref_ids={r.object_id for r in slide.evidence_refs}
        for aid in slide.asset_ids:
            if aid not in ref_ids:bad.append(dict(object_id=aid,slide_index=slide.slide_index,reason='visual_without_versioned_ref'))
    for aid in visuals:
        if aid not in assets or assets[aid]['type'] not in {'image','table'}:
            bad.append(dict(object_id=aid,reason='unknown_or_nonvisual_asset'))
    return dict(reference_count=len(refs),invalid_references=bad,
                evidence_reference_validity=(len(refs)-sum('version' in e for e in bad))/len(refs) if refs else 0,
                visual_reference_count=len(visuals),valid=not bad)
