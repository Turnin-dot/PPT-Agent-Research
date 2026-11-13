"""Recover merged paragraph page membership from existing MinerU intermediates.

No OCR, splitting of canonical paragraphs, or duplicated text. Span matches are
normalized character matches, not claims that all extracted text is correct.
"""
from functools import lru_cache
import json
from pathlib import Path


def norm(text):
    return ''.join(c for c in text.casefold() if c.isalnum())


def source_mapping(manifest):
    source = manifest.get('mineru', {}).get('result_dir')
    files = list(Path(source).glob('*_middle.json')) if source and Path(source).is_dir() else []
    texts = tuple((a['asset_id'], a['source_page'], a.get('text') or '') for a in manifest.get('assets',[]) if a.get('type')=='text')
    if len(files)!=1:
        return {}, dict(status='unavailable', reason='Existing MinerU middle file unavailable; stored pages retained')
    p=files[0]
    return _build(str(p),p.stat().st_mtime_ns,p.stat().st_size,texts)


@lru_cache(maxsize=8)
def _build(path,mtime,size,texts):
    data=json.loads(Path(path).read_text(encoding='utf-8'))
    index=[(aid,page,norm(text)) for aid,page,text in texts if text]
    locations={}; ambiguous=0; unmatched=0
    for page in data.get('pdf_info',[]):
        number=page['page_idx']+1
        for block in page.get('preproc_blocks',[]):
            if block.get('type')!='text':continue
            for line in block.get('lines',[]):
                for span in line.get('spans',[]):
                    if span.get('type')!='text':continue
                    text=span.get('content','');needle=norm(text)
                    if len(needle)<20:continue
                    hits=[(aid,stored) for aid,stored,body in index if needle in body]
                    if len(hits)!=1:
                        ambiguous+=len(hits)>1;unmatched+=not hits;continue
                    aid,stored=hits[0]
                    if stored!=number:
                        locations.setdefault(aid,[]).append(dict(page=number,bbox=span.get('bbox'),coordinate_space='mineru_page_units',
                            page_size=page.get('page_size'),anchor=text,match='normalized_text_span'))
    result={}
    for aid,stored,text in texts:
        extra=locations.get(aid,[])
        if extra:
            result[aid]=dict(stored_page=stored,source_pages=sorted({stored,*[s['page'] for s in extra]}),
                mapping_status='matched_spans',source_spans=extra,
                note='Stored merged paragraph kept once. Additional pages are supported by unique normalized text-span matches; punctuation/math accuracy not certified.')
    return result,dict(status='available',cross_page_record_count=len(result),unmatched_spans=unmatched,ambiguous_spans=ambiguous,
                       method='unique_normalized_text_spans',middle_path=path)
