"""Advisory semantic reviews and evidence-verified planning delivery decisions.

No API calls or automatic revision loop. Review findings are proposals until a
separate evidence review confirms them; a score never overrides a blocker.
"""
from __future__ import annotations
from typing import Literal
from pydantic import BaseModel,ConfigDict,Field,StrictBool,StrictInt,model_validator


class Record(BaseModel):
    model_config=ConfigDict(extra='forbid')


class ReviewEvidence(Record):
    source_kind: Literal['asset','pdf_page','plan']
    object_id: str | None = Field(default=None,description='asset时必须为当前Manifest中的稳定ID；原PDF页证据不伪造ID。')
    version: StrictInt | None = None
    source_page: StrictInt | None = Field(default=None,ge=1,description='原PDF物理页码，1-based。')
    quote: str = Field(default='',max_length=900,description='简短可核查摘录；plan证据写具体字段。')

    @model_validator(mode='after')
    def kind_fields(self):
        if self.source_kind=='asset' and (not self.object_id or self.version is None or self.version<1 or self.source_page is None):
            raise ValueError('Asset evidence requires ID, positive version and page')
        if self.source_kind=='pdf_page' and self.source_page is None:raise ValueError('PDF evidence requires a source page')
        return self


class ReviewIssue(Record):
    @model_validator(mode='before')
    @classmethod
    def accept_uncertain_field_typo(cls,value):
        if isinstance(value,dict) and 'uncertain' in value and 'certainty' not in value:
            value=dict(value)
            value['certainty']=value.pop('uncertain')
        return value

    issue_id: str = Field(min_length=1,max_length=80)
    severity: Literal['critical','major','minor']
    blocking: StrictBool = Field(description='critical必须true；major按实际交付影响判断；静态密度风险不是视觉不合格。')
    category: Literal['scientific_fact','coverage','narrative','asset_matching','execution','wording','layout_risk']
    affected_slides: list[StrictInt] = Field(default_factory=list,description='当前计划页码，1-based；全局问题可为空。')
    description: str = Field(min_length=1,max_length=900)
    evidence_refs: list[ReviewEvidence] = Field(default_factory=list,max_length=8)
    suggested_action: str = Field(min_length=1,max_length=1000)
    certainty: Literal['suspected','uncertain'] = Field(default='suspected',description='独立模型意见不是Ground Truth；证据不足用uncertain。')

    @model_validator(mode='after')
    def severity_contract(self):
        if self.severity=='critical' and not self.blocking:raise ValueError('Critical findings must be blocking')
        if self.severity=='minor' and self.blocking:raise ValueError('Minor findings cannot be blocking')
        if self.blocking and not self.evidence_refs:raise ValueError('Blocking findings require traceable evidence')
        if any(i<1 for i in self.affected_slides):raise ValueError('Slide numbers are 1-based')
        return self


class ReviewSubmission(Record):
    summary: str = Field(min_length=1,max_length=1200)
    reviewed_topics: list[str] = Field(min_length=1,max_length=30,description='实际检查主题，不是质量自评分。')
    issues: list[ReviewIssue] = Field(max_length=64,description='优先可操作的重要问题；不为凑数提意见。')


class ReviewBinding(Record):
    planning_version: str
    planning_sha256: str = Field(pattern=r'^[0-9a-f]{64}$',description='完整理解+计划的规范JSON哈希。')
    plan_file_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    manifest_revision: StrictInt
    manifest_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    source_pdf_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')


class PlanningReviewReport(Record):
    report_id: str
    binding: ReviewBinding
    reviewer_model: str
    execution_status: Literal['succeeded']
    review_verdict: Literal['pass','needs_revision','uncertain']
    advisory_only: Literal[True] = True
    critical_count: StrictInt
    blocking_major_count: StrictInt
    non_blocking_count: StrictInt
    summary: str
    reviewed_topics: list[str]
    issues: list[ReviewIssue]
    metrics_ref: str = ''
    usage: dict[str,int | None] = Field(default_factory=dict)
    elapsed_seconds: float | None = None


def build_review_report(submission: ReviewSubmission, *, binding: ReviewBinding,
                        report_id: str, reviewer_model: str, manifest: dict, slide_count: int,
                        metrics_ref: str='', usage: dict | None=None, elapsed_seconds: float | None=None) -> PlanningReviewReport:
    ids=[i.issue_id for i in submission.issues]
    if len(set(ids))!=len(ids):raise ValueError('Duplicate review issue IDs')
    assets={a['asset_id']:a for a in manifest['assets']}
    from ..pdf_assets.provenance import source_mapping
    physical=source_mapping(manifest)[0]
    for issue in submission.issues:
        if any(i>slide_count for i in issue.affected_slides):raise ValueError('Finding references a nonexistent slide')
        for ref in issue.evidence_refs:
            if ref.source_kind=='asset':
                a=assets.get(ref.object_id)
                if not a or a.get('version',1)!=ref.version or ref.source_page not in physical.get(ref.object_id,{}).get('source_pages',[a['source_page']]):
                    raise ValueError('Unknown/stale/wrong-page review evidence: '+str(ref.object_id))
    critical=sum(i.severity=='critical' for i in submission.issues)
    blocking=sum(i.severity=='major' and i.blocking for i in submission.issues)
    uncertainty=any(i.blocking and i.certainty=='uncertain' for i in submission.issues)
    verdict='uncertain' if uncertainty else 'needs_revision' if critical or blocking else 'pass'
    return PlanningReviewReport(report_id=report_id,binding=binding,reviewer_model=reviewer_model,execution_status='succeeded',
        review_verdict=verdict,critical_count=critical,blocking_major_count=blocking,
        non_blocking_count=sum(not i.blocking for i in submission.issues),
        metrics_ref=metrics_ref,usage=usage or {},elapsed_seconds=elapsed_seconds,**submission.model_dump())


class VerifiedIssue(Record):
    issue_id: str
    reviewer_issue_id: str | None = None
    decision: Literal['confirmed','rejected','uncertain']
    severity: Literal['critical','major','minor']
    blocking: StrictBool
    resolution: Literal['unresolved','resolved','deferred'] = 'unresolved'
    evidence: list[str] = Field(min_length=1)
    rationale: str

    @model_validator(mode='after')
    def severity_contract(self):
        if self.severity=='minor' and self.blocking:raise ValueError('Verified minor cannot block')
        if self.severity=='critical' and not self.blocking:raise ValueError('Verified critical must block')
        return self


class DeliveryChecks(Record):
    schema_valid: StrictBool | None
    references_valid: StrictBool | None
    core_coverage_verified: StrictBool | None
    downstream_readable: StrictBool | None
    narrative_consistent: StrictBool | None
    page_count_consistent: StrictBool | None
    source_versions_current: StrictBool | None
    semantic_review_complete: StrictBool | None


def assess_delivery(*,binding: ReviewBinding, current_binding: ReviewBinding, checks: DeliveryChecks,
                    issues: list[VerifiedIssue], quality_score: float | None=None) -> dict:
    values=checks.model_dump();failed=[k for k,v in values.items() if v is False]
    unknown=[k for k,v in values.items() if v is None]
    stale=binding!=current_binding
    active=[i for i in issues if i.decision!='rejected' and i.resolution!='resolved']
    confirmed=[i for i in active if i.decision=='confirmed']
    critical=sum(i.severity=='critical' for i in confirmed)
    major=sum(i.severity=='major' and i.blocking for i in confirmed)
    uncertain=any(i.decision=='uncertain' and i.blocking for i in active)
    if failed or stale or critical or major:status='needs_revision'
    elif unknown or uncertain:status='uncertain'
    elif active:status='accepted_with_notes'
    else:status='accepted'
    return dict(status=status,binding=binding.model_dump(),binding_current=not stale,checks=values,
        failed_checks=failed,unknown_checks=unknown,critical_count=critical,blocking_major_count=major,
        unresolved_non_blocking_count=sum(not i.blocking for i in active),quality_score=quality_score,
        recommended_90_score_met=None if quality_score is None else quality_score>=90,
        can_enter_html=status in {'accepted','accepted_with_notes'},
        html_rendered=False,page_visual_reviewed=False,
        issues=[i.model_dump() for i in issues],
        scope='Planning acceptance only; score cannot override blockers and static density is not rendered overflow.')
