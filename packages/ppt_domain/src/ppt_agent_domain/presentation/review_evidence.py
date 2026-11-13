"""Bounded read-only original-PDF supplements for evidence omitted by parsing."""
from pathlib import Path
import re
import unicodedata

from .storage import sha256_file


def cited_pdf_pages(text: str) -> list[int]:
    """Explicit p.N / 第N页 citations, not slide counters or stage numbers."""
    matches=re.findall(r'\bp\.?\s*(\d{1,3})\b|第\s*(\d{1,3})\s*页',text,flags=re.I)
    return sorted({int(a or b) for a,b in matches if int(a or b)>0})


def _normalized(text):
    return re.sub(r'\s+','',unicodedata.normalize('NFKC',text))


def source_pdf_supplement(manifest, pages, provided_text, *, max_pages=4, max_chars=12000):
    """Use the bound PDF only; absence from this supplement never proves absence.

    Exact normalized lines already in SOURCE evidence are omitted. HTML/plan
    claims must not be used as provided_text, or unsupported claims could hide
    their own verification evidence. Math extraction remains secondary to images.
    """
    source=manifest.get('source',{});path=Path(source.get('pdf_path',''))
    requested=sorted({p for p in pages if isinstance(p,int) and not isinstance(p,bool) and p>0})
    result=dict(status='unavailable',source_pdf_path=str(path),requested_pages=requested,
        pages=[],omitted_pages=[],returned_chars=0,max_chars=max_chars,max_pages=max_pages,
        extraction='original_pdf_text_lines_supplement_not_reparsed_assets',hash_verified=False)
    if not path.is_file() or not source.get('sha256'):
        result['reason']='source_missing_or_hash_unavailable';return result
    try:
        actual_hash=sha256_file(path)
    except OSError:
        result['reason']='source_read_error';return result
    if actual_hash!=source['sha256']:
        result.update(status='unverified_source',reason='source_hash_mismatch');return result
    result['hash_verified']=True
    existing=_normalized(provided_text);remaining=max(0,max_chars)
    import fitz
    try:
        with fitz.open(path) as doc:
            valid=[p for p in requested if p<=doc.page_count]
            result['invalid_pages']=[p for p in requested if p>doc.page_count]
            for number in valid[:max_pages]:
                if remaining<=0:
                    result['omitted_pages'].append(number);continue
                fragments=[];seen=set();original_chars=0;deduplicated=0;truncated=False
                for block in doc[number-1].get_text('dict')['blocks']:
                    for line in block.get('lines',[]):
                        text=''.join(s['text'] for s in line.get('spans',[])).strip()
                        key=_normalized(text)
                        if not key:continue
                        original_chars+=len(text)
                        if key in existing or key in seen:
                            deduplicated+=1;continue
                        seen.add(key)
                        if len(text)>remaining:
                            truncated=True;continue  # Do not cut a formula/claim mid-line.
                        fragments.append(dict(text=text,bbox=line['bbox']))
                        remaining-=len(text)
                result['pages'].append(dict(pdf_page=number,fragments=fragments,
                    extracted_chars=original_chars,deduplicated_lines=deduplicated,truncated=truncated))
            result['omitted_pages'].extend(valid[max_pages:])
        result.update(status='available',returned_chars=max(0,max_chars)-remaining)
    except (RuntimeError,ValueError,OSError) as exc:
        result.update(status='unavailable',reason=type(exc).__name__)
    return result
