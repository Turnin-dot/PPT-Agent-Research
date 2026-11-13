"""Deterministic, read-only paper material assembly, without scientific synthesis.

Canonical evidence remains in the Manifest. This projection removes repeated
provenance/report bodies, not source text. Oversized pages/records are segmented
with explicit field offsets; source ambiguities are only copied when stored.
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path

from pydantic import BaseModel,ConfigDict,Field,StrictInt,StrictBool

from .assets import asset_view,ordered_assets
from ..pdf_assets.storage import load_manifest
from ..pdf_assets.hybrid import structured_value


def compact(value):
    return json.dumps(value,ensure_ascii=False,separators=(',',':'))


def estimate_tokens(value):
    """Conservative UTF8/2 planning heuristic, NOT a tokenizer or billable usage.

    Callers reserve tool/prompt/output space separately and meter actual usage.
    Provider tokenization can differ; this is an explicit configurable reference.
    """
    text=value if isinstance(value,str) else compact(value)
    return math.ceil(len(text.encode('utf-8'))/2)


class PaperContextResult(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    execution_status: str=Field(pattern='^succeeded$')
    read_only: StrictBool
    manifest_path: str
    manifest_revision: StrictInt
    source_sha256: str
    source_notes: list | dict
    evidence_policy: str = ''
    context_sha256: str
    segment_index: StrictInt
    segment_count: StrictInt
    segment: dict
    coverage: dict
    size: dict
    next_segment_index: StrictInt | None


def _fragment_record(record,budget):
    # Only an oversized record uses field fragments. Ordinary records stay native.
    identity={k:record[k] for k in ('asset_id','version','source_page','type','order')}
    fields=[]
    for key,value in record.items():
        if key in identity:continue
        if isinstance(value,str):fields.append((key,value))
        elif key=='captions':fields.extend((f'captions/{i}',v) for i,v in enumerate(value))
        else:identity[key]=deepcopy(value)
    if estimate_tokens(dict(identity,fragments=[]))+120>=budget:
        raise ValueError('Context budget too small for record identity/geometry; increase budget')
    output=[]
    for field,text in fields:
        offset=0
        if not text:output.append(dict(identity,fragments=[dict(field=field,start=0,end=0,text='')]))
        while offset<len(text):
            low,high=1,len(text)-offset;best=0
            while low<=high:
                n=(low+high)//2
                part=dict(identity,fragments=[dict(field=field,start=offset,end=offset+n,text=text[offset:offset+n])])
                if estimate_tokens(part)+80<=budget:best=n;low=n+1
                else:high=n-1
            if not best:raise ValueError('Context budget cannot fit one character and identity')
            output.append(dict(identity,fragments=[dict(field=field,start=offset,end=offset+best,text=text[offset:offset+best])]))
            offset+=best
    return output or [dict(identity,fragments=[])]


def build_paper_context(manifest_path:str,*,input_budget_tokens:int=80000):
    if input_budget_tokens<512:raise ValueError('input_budget_tokens must be >=512')
    path,manifest=load_manifest(manifest_path);missing=[];pages={};records=[]
    pdf=manifest.get('source',{}).get('pdf_path');page_count=0;page_count_basis='highest_asset_page'
    if pdf and Path(pdf).is_file():
        import fitz
        with fitz.open(pdf) as document:page_count=len(document)
        page_count_basis='source_pdf'
    page_count=max(page_count,max((a['source_page'] for a in manifest['assets']),default=0))
    for page in range(1,page_count+1):pages[page]=[]
    ids=[]
    for a in ordered_assets(manifest):
        aid=a['asset_id']
        if aid in ids:raise ValueError('Duplicate asset ID: '+aid)
        ids.append(aid);v=asset_view(a,manifest,str(path),geometry=True)
        page=a['source_page'];r=dict(asset_id=aid,version=v['version'],source_page=page,type=a['type'],order=len(pages[page]))
        r.update(bbox=v['bbox'], bbox_coordinate_space=v['bbox_coordinate_space'])
        if v['structured_source']:r['structured_source']=v['structured_source']
        if v['equation_numbers']:r['equation_numbers']=v['equation_numbers']
        if v['associations']:r['associations']=v['associations']
        if v['table_footnotes']:r['table_footnotes']=v['table_footnotes']
        if v['source_pages']!=[page]:
            r.update(source_pages=v['source_pages'],source_mapping_status=v['source_provenance']['mapping_status'])
        if a['type'] in {'image','table'}:
            r.update(number=v['figure_number'],captions=v['captions'],path=v['path'],
                semantic_description=v['semantic_description'],structure_description=v['structure_description'],
                description_status=v['description_status'],review_status=v['review_status'],
                review_applicability=v['review']['applicability'],is_verified=v['is_verified'],
                report_ids=[p.get('report_id') for p in v['review']['report_refs'] if p.get('report_id')],
                geometry={k:v.get(k) for k in ('pixel_width','pixel_height','aspect_ratio','orientation','bbox','bbox_coordinate_space') if v.get(k) is not None})
            quality=v['reliability']
            r['reliability']=dict(states=quality['states'],scope=quality['verified_scope'],
                state_basis=quality['state_basis'],preferred_evidence=quality['preferred_evidence'],
                needs_visual_check=quality['needs_visual_check'],has_current_corrections=quality['has_current_corrections'],
                report_refs=[dict(report_id=p['report_id'],path=p['report_path'],applicability=p['applicability']) for p in quality['report_refs']])
            r['is_verified_scope']='visual_crop_only'
            if a['type']=='table':r['table_text']=str(a.get('recognized_text') or structured_value(a) or '')
            body=str(a.get('recognized_text') or a.get('text') or '')
            if body and body not in r.get('captions',[]) and body!=r.get('table_text'):r['text']=body
            if not v['file_exists']:missing.append(dict(asset_id=aid,source_page=page,kind='missing_visual_file',path=v['path']))
            if not r['captions']:missing.append(dict(asset_id=aid,source_page=page,kind='missing_caption'))
            if v['description_status']!='current':missing.append(dict(asset_id=aid,source_page=page,kind='description_not_current',status=v['description_status']))
        else:
            r['text']=str(a.get('recognized_text') or (structured_value(a) if a['type']=='equation' else a.get('text')) or a.get('equation') or '')
            if not r['text']:missing.append(dict(asset_id=aid,source_page=page,kind='empty_text'))
        pages[page].append(r);records.append(r)
    source_notes=deepcopy(manifest.get('source_ambiguities') or [])
    empty_pages=[p for p,items in pages.items() if not items]
    full=dict(schema_version='paper-context/v1',manifest_path=str(path),manifest_revision=manifest['revision'],
        source_sha256=manifest.get('source',{}).get('sha256',''),source_notes=source_notes,
        evidence_policy='Legacy pass/is_verified certifies crop only. Raw OCR text/HTML is unverified unless a current scoped report says otherwise. Empty extracted cells do not prove absence. source_pages describes physical page coverage; each merged paragraph occurs once.',
        pages=[dict(page_number=p,records=items) for p,items in pages.items()])
    # The complete compact value is saved by the caller; no source text is sliced off.
    segments=[];current=[]
    def flush():
        if current:segments.append(dict(pages=deepcopy(current)));current.clear()
    for page,items in pages.items():
        entry=dict(page_number=page,records=items)
        if estimate_tokens(dict(pages=current+[entry]))<=input_budget_tokens:current.append(entry);continue
        flush()
        if estimate_tokens(dict(pages=[entry]))<=input_budget_tokens:current.append(entry);continue
        for record in items:
            pieces=[record] if estimate_tokens(record)+80<=input_budget_tokens else _fragment_record(record,input_budget_tokens)
            for piece in pieces:
                piece_entry=dict(page_number=page,records=[piece])
                if estimate_tokens(dict(pages=current+[piece_entry]))>input_budget_tokens:flush()
                current.append(piece_entry)
    flush()
    if not segments:segments=[dict(pages=[])]
    coverage=dict(page_count=page_count,page_count_basis=page_count_basis,pages=list(pages),empty_pages=empty_pages,
        asset_count=len(records),visual_count=sum(a['type'] in {'image','table'} for a in records),
        asset_counts=dict(Counter(a['type'] for a in records)),missing_records=missing,
        all_manifest_assets_included=True,source_text_not_truncated=True,
        source_ambiguity_inventory_available='source_ambiguities' in manifest,
        note='Coverage means stored material was included, not that extraction is complete/correct. Missing source ambiguities do not prove absence. Descriptions are auxiliary; image paths are not visual input.')
    from ..pdf_assets.provenance import source_mapping
    coverage['provenance_mapping']=source_mapping(manifest)[1]
    size=dict(compact_bytes=len(compact(full).encode('utf-8')),estimated_tokens=estimate_tokens(full),
        estimator='ceil(compact UTF8 bytes / 2); planning reference, actual API usage is authoritative',
        per_segment_budget_tokens=input_budget_tokens,segment_count=len(segments),
        segment_estimated_tokens=[estimate_tokens(s) for s in segments])
    if any(n>input_budget_tokens for n in size['segment_estimated_tokens']):raise ValueError('Segment cannot fit context budget')
    return dict(context=full,segments=segments,coverage=coverage,size=size,context_sha256=hashlib.sha256(compact(full).encode()).hexdigest())


def select_segment(package,index):
    if not 0<=index<len(package['segments']):raise ValueError('segment_index out of range')
    c=package['context']
    return PaperContextResult(execution_status='succeeded',read_only=True,manifest_path=c['manifest_path'],manifest_revision=c['manifest_revision'],
        source_sha256=c['source_sha256'],source_notes=c['source_notes'],evidence_policy=c['evidence_policy'],context_sha256=package['context_sha256'],segment_index=index,
        segment_count=len(package['segments']),segment=package['segments'][index],coverage=package['coverage'],size=package['size'],
        next_segment_index=index+1 if index+1<len(package['segments']) else None).model_dump(mode='json')


def context_input(user_request,package):
    """Public product adapter: raw material goes in a user message, never system rules."""
    first=select_segment(package,0)
    return compact(dict(user_task=user_request,paper_context=first,source_notes=package['context']['source_notes'],
        delivery=dict(initial_segments=[0],pending_segments=list(range(1,len(package['segments']))),
            complete_material_in_initial_request=len(package['segments'])==1,
            note='程序整理的原始资料，非论文理解或规划。缺少必要段时按get_paper_context读取；不要把摘要/路径当已读原图。')))
