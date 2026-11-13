"""Rebuild page-scoped Markdown from MinerU records without changing its original MD."""
from __future__ import annotations

from collections import Counter
from pathlib import Path
import os

from .provenance import source_mapping
from .storage import read_json, sha256_file, write_json


def _split_at_source_span(text: str, stored_page: int, mapping: dict) -> list[dict] | None:
    """Split only when a unique next-page span anchors a two-page merged text."""
    pages=mapping.get('source_pages') or []
    if len(pages)!=2 or pages[0]!=stored_page or pages[1]!=stored_page+1:
        return None
    normalized=[];positions=[]
    for pos,ch in enumerate(text):
        for folded in ch.casefold():
            if folded.isalnum(): normalized.append(folded);positions.append(pos)
    haystack=''.join(normalized)
    for span in mapping.get('source_spans',[]):
        if span['page']!=pages[1]: continue
        needle=''.join(ch for ch in span.get('anchor','').casefold() if ch.isalnum())
        at=haystack.find(needle)
        if len(needle)<20 or at<1 or haystack.find(needle,at+1)>=0: continue
        cut=positions[at]
        if 0<cut<len(text):
            return [dict(pdf_page=pages[0],text=text[:cut],char_range=[0,cut]),
                    dict(pdf_page=pages[1],text=text[cut:],char_range=[cut,len(text)])]
    return None


def _render(item: dict, *, image_root: Path, page_dir: Path) -> str:
    kind = item.get('type')
    caption = item.get('image_caption') or item.get('table_caption') or []
    footnote = item.get('image_footnote') or item.get('table_footnote') or []
    parts = []
    if kind == 'text':
        text = str(item.get('text') or '').strip()
        level = item.get('text_level')
        if text and isinstance(level, int) and 1 <= level <= 6:
            text = '#' * level + ' ' + text
        if text: parts.append(text)
    elif kind == 'equation':
        if item.get('text'): parts.append(str(item['text']).strip())
    elif kind == 'table':
        parts += [str(v).strip() for v in caption if str(v).strip()]
        if item.get('table_body'): parts.append(str(item['table_body']).strip())
    elif kind == 'image':
        pass
    path = item.get('img_path')
    if path and (kind == 'image' or (kind in {'equation','table'} and not item.get('text') and not item.get('table_body'))):
        target = (image_root / str(path)).resolve()
        parts.append(f'![]({Path(os.path.relpath(target, page_dir)).as_posix()})')
    if kind == 'image': parts += [str(v).strip() for v in caption if str(v).strip()]
    parts += [str(v).strip() for v in footnote if str(v).strip()]
    return '\n\n'.join(parts)


def build_page_markdown(manifest: dict, output_dir: str | Path) -> dict:
    """Write physical-page MD plus an index; ambiguous merged records stay separate."""
    source = manifest['mineru']
    content_path = Path(source['content_list_path']).resolve()
    content = read_json(content_path)
    if not isinstance(content, list): raise ValueError('MinerU content list is not an array')
    output = Path(output_dir).resolve(); pages_dir = output/'pages'
    pages_dir.mkdir(parents=True, exist_ok=True)
    page_start = manifest.get('parse_scope',{}).get('page_start_zero_based') or 0
    page_end = manifest.get('parse_scope',{}).get('page_end_zero_based')
    physical_pages = sorted({int(x['page_idx'])+1 for x in content if isinstance(x.get('page_idx'),int) and x['page_idx']>=0})
    pdf_count = None
    pdf_path = Path(manifest.get('source',{}).get('pdf_path') or '')
    if pdf_path.is_file():
        import fitz
        with fitz.open(pdf_path) as pdf: pdf_count=pdf.page_count
    if page_end is not None: physical_pages = list(range(page_start+1,page_end+2))
    elif pdf_count is not None: physical_pages = list(range(page_start+1,pdf_count+1))
    elif physical_pages: physical_pages = list(range(min(physical_pages),max(physical_pages)+1))
    counts: dict[tuple[int,str],int] = Counter()
    assets = {a['asset_id']:a for a in manifest['assets']}
    mappings, mapping_info = source_mapping(manifest)
    records = {}; assigned={p:[] for p in physical_pages}; related={p:[] for p in physical_pages}; unresolved=[]
    for i,item in enumerate(content):
        typ = str(item.get('type','unknown'))
        if typ == 'discarded': continue
        idx = item.get('page_idx')
        if not isinstance(idx,int) or idx < 0:
            unresolved.append(dict(source_index=i,asset_id=None,reason='invalid_page_idx',source_pages=[]))
            continue
        page=idx+1;counts[(page,typ)]+=1
        aid=f'{typ}-p{page:04d}-{counts[(page,typ)]:03d}'
        if aid not in assets: raise ValueError(f'Content list and Manifest disagree: {aid}')
        mapping=mappings.get(aid) or {}
        source_pages=mapping.get('source_pages') or [page]
        segments=(_split_at_source_span(str(item.get('text') or ''),page,mapping)
                  if typ=='text' and len(source_pages)>1 else None)
        status=('split_by_unique_source_span' if segments else
                'cross_page_unresolved' if len(source_pages)>1 else 'aligned_by_content_list_page_idx')
        record=dict(asset_id=aid,source_index=i,reading_order=i,type=typ,stored_page=page,
                    source_pages=source_pages,alignment_status=status,bbox=item.get('bbox'),
                    source_content_list_path=str(content_path),source_mapping_status=mapping.get('mapping_status','stored_page_only'))
        if mapping.get('source_spans'): record['source_spans']=mapping['source_spans']
        if segments: record['segments']=segments
        records[aid]=record
        if segments:
            for segment in segments: assigned[segment['pdf_page']].append(aid)
        elif status=='cross_page_unresolved':
            record['markdown']=_render(item,image_root=content_path.parent,page_dir=output)
            unresolved.append(record)
            for p in source_pages:
                if p in related: related[p].append(aid)
        else:
            assigned[page].append(aid)
    original_path=Path(source.get('markdown_path') or '')
    index=dict(schema_version='page-markdown/v1',derivation='Rebuilt from MinerU content_list, not an exact slice of original Markdown',
               original_markdown_path=str(original_path) if original_path.is_file() else '',
               original_markdown_sha256=sha256_file(original_path) if original_path.is_file() else None,
               content_list_path=str(content_path),content_list_sha256=sha256_file(content_path),
               source_mapping=mapping_info,pages=[],records=records,unresolved_records=unresolved,
               excluded_discarded_count=sum(x.get('type')=='discarded' for x in content))
    for p in physical_pages:
        blocks=[]
        for aid in assigned[p]:
            record=records[aid];item=content[record['source_index']]
            if record.get('segments'):
                segment=next(s for s in record['segments'] if s['pdf_page']==p)
                item=dict(item,text=segment['text'])
            blocks.append(_render(item,image_root=content_path.parent,page_dir=pages_dir))
        page_text='\n\n'.join(x for x in blocks if x)+'\n' if any(blocks) else ''
        path=pages_dir/f'page_{p:03d}.md'
        path.write_text(page_text,encoding='utf-8')
        index['pages'].append(dict(pdf_page=p,path=str(path),sha256=sha256_file(path),
            source_record_indices=[records[aid]['source_index'] for aid in assigned[p]],
            asset_ids=assigned[p],content_counts=dict(Counter(records[aid]['type'] for aid in assigned[p])),
            unresolved_asset_ids=related[p],alignment_status=('has_cross_page_unresolved' if related[p] else
                'contains_split_cross_page' if any(records[aid].get('segments') for aid in assigned[p]) else
                'aligned_by_content_list_page_idx')))
    unresolved_path=output/'unresolved.md'
    unresolved_blocks=[]
    for record in unresolved:
        item=content[record['source_index']]
        body=_render(item,image_root=content_path.parent,page_dir=output)
        if body: unresolved_blocks.append(f"<!-- source_index={record['source_index']} asset_id={record['asset_id']} alignment_status={record['reason'] if 'reason' in record else record['alignment_status']} -->\n\n{body}")
    unresolved_path.write_text('\n\n'.join(unresolved_blocks)+'\n' if unresolved_blocks else '',encoding='utf-8')
    index['unresolved_path']=str(unresolved_path)
    index_path=output/'page_index.json';write_json(index_path,index)
    return dict(page_index_path=str(index_path),page_count=len(physical_pages),unresolved_count=len(unresolved))
