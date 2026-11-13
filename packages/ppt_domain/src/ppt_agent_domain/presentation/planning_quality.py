"""Offline planning checks. Structural success never implies factual approval.

Paper-specific facts/configurations are supplied as data. Natural-language
entailment, narrative quality and true coverage remain independent review work.
No model requests, source mutation or lifecycle scheduling occur here.
"""
from __future__ import annotations

from collections import Counter
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .assets import asset_view


class Record(BaseModel):
    model_config = ConfigDict(extra='forbid')


class QualityIssue(Record):
    issue_id: str
    severity: Literal['Critical','Major','Minor','Info']
    kind: str
    slide_indices: list[int] = Field(default_factory=list)
    description: str
    evidence: list[dict] = Field(default_factory=list)
    suggestion: str
    must_fix: bool = False
    certainty: Literal['deterministic','review_required'] = 'deterministic'
    blocking: bool = False


class DensityLimits(Record):
    max_points: int = Field(default=4,ge=1)
    max_point_chars: int = Field(default=90,ge=1)
    max_display_chars: int = Field(default=350,ge=1)
    max_visuals: int = Field(default=3,ge=1)


class ExperimentConfiguration(Record):
    configuration_id: str
    dataset: str
    setting: str
    metric: str
    unit: str
    components: set[str]
    value: float
    evidence_refs: list[dict]


class ExperimentComparison(Record):
    from_id: str
    to_id: str
    added_components: set[str]
    removed_components: set[str] = Field(default_factory=set)
    claimed_delta: float | None = None


def check_experiment_relations(configurations: list[ExperimentConfiguration],
                               comparisons: list[ExperimentComparison]) -> list[QualityIssue]:
    """Validate declared configuration edges, not arbitrary prose via regex."""
    index={c.configuration_id:c for c in configurations}
    if len(index)!=len(configurations):raise ValueError('Duplicate configuration IDs')
    issues=[]
    for n,edge in enumerate(comparisons):
        left,right=index.get(edge.from_id),index.get(edge.to_id)
        reasons=[]
        if left is None or right is None:reasons.append('Unknown experiment configuration')
        else:
            if any(getattr(left,k)!=getattr(right,k) for k in ('dataset','setting','metric','unit')):
                reasons.append('Comparison mixes dataset/setting/metric/unit')
            if (right.components-left.components)!=edge.added_components or (left.components-right.components)!=edge.removed_components:
                reasons.append('Claimed incremental components do not match the two configurations')
            if edge.claimed_delta is not None and abs((right.value-left.value)-edge.claimed_delta)>1e-6:
                reasons.append('Claimed delta differs from target minus source')
        if reasons:
            issues.append(QualityIssue(issue_id=f'EXPERIMENT-{n+1}',severity='Major',kind='experiment_relation',
                description='; '.join(reasons),evidence=[c.model_dump(mode='json') for c in (left,right) if c],
                suggestion='Compare independent branches from their common baseline; retain dataset, setting, metric and unit.',must_fix=True))
    return issues


def check_scoped_result(reference: ExperimentConfiguration, *, dataset: str, setting: str,
                        metric: str, unit: str, value: float) -> list[str]:
    actual=dict(dataset=dataset,setting=setting,metric=metric,unit=unit,value=value)
    return [k for k,v in actual.items() if (abs(v-reference.value)>1e-6 if k=='value' else v!=getattr(reference,k))]


def check_plan_quality(plan: dict, manifest: dict, *, manifest_path: str='',
                       required_visual_ids: list[str] | None=None,
                       limits: DensityLimits | None=None) -> dict:
    """Check bounds, declared count and sources. Warnings require adjudication.

    Density bounds indicate risk before HTML exists, not measured overflow.
    References are checked here as well as by the native submission Schema.
    """
    limits=limits or DensityLimits();issues=[];metrics=[]
    assets={a['asset_id']:a for a in manifest.get('assets',[])}
    from ..pdf_assets.provenance import source_mapping
    physical=source_mapping(manifest)[0]
    slides=plan.get('slides',[]);used=set();seen=set()
    for slide in slides:
        i=slide['slide_index'];points=slide['main_points'];visuals=slide['asset_ids'];used.update(visuals)
        display=len(slide['slide_title'])+len(slide['key_message'])+sum(map(len,points))
        measure=dict(slide_index=i,point_count=len(points),max_point_chars=max(map(len,points),default=0),
                     display_chars=display,visual_count=len(visuals))
        excess=[k for k,v in {'point_count':limits.max_points,'max_point_chars':limits.max_point_chars,
                             'display_chars':limits.max_display_chars,'visual_count':limits.max_visuals}.items() if measure[k]>v]
        measure['risk_fields']=excess;metrics.append(measure)
        if excess:
            issues.append(QualityIssue(issue_id=f'DENSITY-{i}',severity='Minor',kind='density',slide_indices=[i],
                description='Static density risks: '+', '.join(excess),evidence=[measure],certainty='review_required',
                suggestion='Check readability during HTML rendering; retain the risk without assuming actual overflow.',must_fix=False,blocking=False))
        signature=(slide['key_message'],tuple(points))
        if signature in seen:
            issues.append(QualityIssue(issue_id=f'DUPLICATE-{i}',severity='Minor',kind='duplicate',slide_indices=[i],
                description='Exact repeated page message and points',suggestion='Review whether both pages have a distinct purpose.',certainty='review_required'))
        seen.add(signature)
        refs={r['object_id']:r for r in slide['evidence_refs']}
        for aid in set(refs)|set(visuals):
            asset=assets.get(aid);ref=refs.get(aid)
            bad=not asset or not ref or ref['version']!=asset.get('version',1) or ref['source_page'] not in physical.get(aid,{}).get('source_pages',[asset['source_page']])
            if bad:
                issues.append(QualityIssue(issue_id=f'REF-{i}-{aid}',severity='Major',kind='reference',slide_indices=[i],
                    description='Unknown, missing, wrong-page or stale reference: '+aid,
                    suggestion='Resolve the stable ID and bind its actual version and page.',must_fix=True,blocking=True))
                continue
            if aid in visuals:
                view=asset_view(asset,manifest,manifest_path)
                if not view['is_verified']:
                    issues.append(QualityIssue(issue_id=f'SOURCE-{i}-{aid}',severity='Minor',kind='source_reliability',slide_indices=[i],
                        description='Visual source has no current verified conclusion',evidence=[dict(asset_id=aid,review=view['review'])],
                        suggestion='Preserve review uncertainty; file existence is not visual approval.',certainty='review_required'))
                if asset['type']=='table' and view['reliability']['states']['structure']!='verified':
                    issues.append(QualityIssue(issue_id=f'CONTENT-{i}-{aid}',severity='Minor',kind='source_reliability',slide_indices=[i],
                        description='Crop acceptance does not verify table OCR or scientific configuration relationships',
                        evidence=[dict(asset_id=aid,reliability=view['reliability'])],
                        suggestion='Use current scoped verification for relevant claims; inspect key cells only when needed.',certainty='review_required'))
    counts=re.findall(r'(?:规划|共|总计|总共|合计|维持|总页数(?:为|是)?)\s*(\d+)\s*页',plan.get('page_count_rationale',''))
    if counts and int(counts[0])!=len(slides):
        issues.append(QualityIssue(issue_id='PAGE-COUNT',severity='Major',kind='page_count',
            description=f'Declared {counts[0]} pages but plan contains {len(slides)}',
            suggestion='Update rationale and section allocation to actual page count.',must_fix=True,blocking=True))
    missing=sorted(set(required_visual_ids or [])-used)
    if missing:
        issues.append(QualityIssue(issue_id='REQUIRED-VISUALS',severity='Major',kind='coverage',
            description='Required source visuals not selected: '+', '.join(missing),
            suggestion='Restore required evidence or document why an equivalent source covers the fact.',must_fix=True,certainty='review_required'))
    return dict(schema_version='planning-quality/v1',issues=[i.model_dump(mode='json') for i in issues],
        page_metrics=metrics,density_risk_count=sum(bool(m['risk_fields']) for m in metrics),
        declared_count_check='checked' if counts else 'not_machine_verifiable',
        semantic_review_required=True,content_pass=None,
        caveat='No natural-language fact, narrative or full-coverage pass is inferred from structural checks.')
