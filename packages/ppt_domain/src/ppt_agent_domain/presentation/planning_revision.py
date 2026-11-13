"""Localized revision transport for planning experiments; no replacement deck."""
from copy import deepcopy
import hashlib
import json
from typing import Annotated, Literal, Any

from pydantic import Field, StrictInt
from .planning_schemas import Record, PlanningSubmission, SlidePlan


def content_hash(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()


class Edit(Record):
    target: Literal['paper_understanding','presentation_plan']
    path: str = Field(pattern=r'^/')
    # Target fields are validated by the complete PlanningSubmission below.
    # Avoid a recursive arbitrary-JSON Schema in provider function parameters.
    value: Any = Field(description='该目标字段的真实JSON值；数组/对象直接嵌套，禁止再次编码成JSON字符串。应用后按完整PaperUnderstanding/PresentationPlan校验。')
    issue_ids: list[str] = Field(min_length=1)
    reason: str


class Insertion(Record):
    after_original_slide: Annotated[StrictInt,Field(ge=0,description='原计划页码；0表示在首面前插入。按原页定位，非已插入后的索引。')]
    slide: SlidePlan
    issue_ids: list[str] = Field(min_length=1)
    reason: str


class Resolution(Record):
    issue_id: str
    action: Literal['addressed','deferred','disputed']
    explanation: str


class RevisionPatch(Record):
    base_sha256: str = Field(pattern=r'^[0-9a-f]{64}$',description='本轮所修订完整理解+计划的规范JSON哈希；防止旧版本覆盖。')
    edits: list[Edit]
    insertions: list[Insertion] = Field(default_factory=list)
    issue_responses: list[Resolution]


class RevisionResult(Record):
    revision_saved: Literal[True]
    revision_id: str
    slide_count: StrictInt
    changed_original_slides: list[StrictInt]
    inserted_slide_count: StrictInt
    quality_report_path: str
    content_pass: None = None
    summary: str


def apply_revision(base: dict, patch: RevisionPatch, *, valid_issue_ids: set[str]) -> tuple[dict,dict]:
    if patch.base_sha256!=content_hash(base):raise ValueError('STALE_BASE: read the current revision base hash')
    result=deepcopy(base);count=len(base['presentation_plan']['slides']);changed=set();paths=set();section_override=False
    for edit in patch.edits:
        key=(edit.target,edit.path)
        if key in paths:raise ValueError('Duplicate patch path')
        paths.add(key)
        if not set(edit.issue_ids)<=valid_issue_ids:raise ValueError('Unknown issue ID')
        parts=[p.replace('~1','/').replace('~0','~') for p in edit.path[1:].split('/')]
        if not parts or not parts[0]:raise ValueError('Cannot replace a whole artifact')
        if edit.target=='presentation_plan' and parts[0]=='section_allocation' and (len(parts)==1 or (len(parts)>=3 and parts[2]=='slide_indices')):
            section_override=True
        if edit.target=='presentation_plan' and parts[0]=='slides':
            if len(parts)<3:raise ValueError('Edit a slide field, not all slides or a whole slide')
            if not parts[1].isdigit() or not 0<=int(parts[1])<count:raise ValueError('Unknown original slide index')
            if parts[2]=='slide_index':raise ValueError('Slide indices are derived after insertion')
            changed.add(int(parts[1])+1)
        if edit.target=='paper_understanding' and parts[0] in {'modules','ablations','datasets','experiment_setup','innovations','key_results','limitations','conclusions'} and len(parts)<2:
            raise ValueError('Edit a specific existing claim field; do not regenerate an understanding section')
        parent=result[edit.target]
        for part in parts[:-1]:parent=parent[int(part)] if isinstance(parent,list) else parent[part]
        final=int(parts[-1]) if isinstance(parent,list) else parts[-1]
        if isinstance(parent,dict) and final not in parent:raise ValueError('Unknown field path')
        parent[final]=deepcopy(edit.value)
    if patch.insertions and ('presentation_plan','/page_count_rationale') not in paths:
        raise ValueError('Inserted pages require an updated count rationale')
    insertions={}
    for item in patch.insertions:
        if item.after_original_slide>count:raise ValueError('Insertion anchor outside original plan')
        if not set(item.issue_ids)<=valid_issue_ids:raise ValueError('Unknown insertion issue')
        insertions.setdefault(item.after_original_slide,[]).append(item)
    original_section={i:n for n,s in enumerate(base['presentation_plan']['section_allocation']) for i in s['slide_indices']}
    allocations=[[] for _ in base['presentation_plan']['section_allocation']];slides=[];lineage=[]
    def append(slide,original,section):
        slide=deepcopy(slide);slide['slide_index']=len(slides)+1;slides.append(slide)
        allocations[section].append(len(slides));lineage.append(dict(new_index=len(slides),original_index=original))
    for anchor in range(count+1):
        if anchor:append(result['presentation_plan']['slides'][anchor-1],anchor,original_section[anchor])
        for item in insertions.get(anchor,[]):
            append(item.slide.model_dump(),None,original_section[max(1,anchor)])
    result['presentation_plan']['slides']=slides
    if not section_override:
        for section,allocated in zip(result['presentation_plan']['section_allocation'],allocations):section['slide_indices']=allocated
    if not set(r.issue_id for r in patch.issue_responses)<=valid_issue_ids:raise ValueError('Unknown response issue')
    result=PlanningSubmission.model_validate(result).model_dump(mode='json')
    return result,dict(changed_original_slides=sorted(changed),inserted_slide_count=len(patch.insertions),lineage=lineage,
        unchanged_original_slide_count=count-len(changed),base_sha256=patch.base_sha256,result_sha256=content_hash(result))
