import hashlib
from pathlib import Path

import fitz

from ppt_agent_domain.presentation.review_evidence import cited_pdf_pages, source_pdf_supplement


def source(tmp_path,pages=1):
    pdf=tmp_path/'source.pdf'
    with fitz.open() as doc:
        for i in range(pages):
            p=doc.new_page(width=600,height=800)
            p.insert_text((60,70),'Known body already provided')
            p.insert_text((30,500),f'ICASSP 2025 IEEE original page {i+1}',rotate=90)
            p.insert_text((60,150),'The model avoids mis-segmentation and under-segmentation.')
        doc.save(pdf)
    return dict(source=dict(pdf_path=str(pdf),sha256=hashlib.sha256(pdf.read_bytes()).hexdigest()))


def test_citations_are_physical_page_hints_not_slide_or_stage_counters():
    assert cited_pdf_pages('p.4 正文；p2；第3页。13 / 15；stage 2/3/4；第2阶段；p0')==[2,3,4]


def test_omitted_margin_text_is_recovered_without_repeating_existing_body(tmp_path):
    manifest=source(tmp_path)
    result=source_pdf_supplement(manifest,[1],'Known body already provided')
    text='\n'.join(f['text'] for p in result['pages'] for f in p['fragments'])
    assert result['hash_verified'] and result['status']=='available'
    assert 'ICASSP 2025' in text and 'under-segmentation' in text
    assert 'Known body' not in text
    assert all(len(f['bbox'])==4 for p in result['pages'] for f in p['fragments'])
    assert result['pages'][0]['deduplicated_lines']==1


def test_source_hash_mismatch_is_not_trusted_and_missing_file_does_not_crash(tmp_path):
    manifest=source(tmp_path);manifest['source']['sha256']='0'*64
    result=source_pdf_supplement(manifest,[1],'')
    assert result['status']=='unverified_source' and not result['hash_verified'] and not result['pages']
    Path(manifest['source']['pdf_path']).unlink()
    assert source_pdf_supplement(manifest,[1],'')['status']=='unavailable'


def test_budget_page_limit_and_invalid_citations_are_explicit(tmp_path):
    manifest=source(tmp_path,pages=5)
    result=source_pdf_supplement(manifest,[1,2,3,4,5,99],'',max_pages=2,max_chars=75)
    assert result['returned_chars']<=75
    assert result['invalid_pages']==[99] and {3,4,5}<=set(result['omitted_pages'])
    assert any(p['truncated'] for p in result['pages'])
    assert all(len(f['text'])<=75 for p in result['pages'] for f in p['fragments'])


def test_all_source_lines_already_provided_is_not_an_extraction_failure(tmp_path):
    manifest=source(tmp_path)
    provided='Known body already provided; ICASSP 2025 IEEE original page 1; The model avoids mis-segmentation and under-segmentation.'
    result=source_pdf_supplement(manifest,[1],provided)
    assert result['status']=='available' and result['hash_verified']
    assert result['returned_chars']==0 and result['pages'][0]['fragments']==[]
    assert result['pages'][0]['deduplicated_lines']==3
