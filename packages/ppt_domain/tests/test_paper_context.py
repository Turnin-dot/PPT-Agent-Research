"""Offline complete-material projection, segmentation and native tool tests."""
from copy import deepcopy
import json
from pathlib import Path

import fitz
from PIL import Image
import pytest

from ppt_agent_domain.presentation.paper_context import build_paper_context,select_segment,context_input
from ppt_agent_domain.presentation import PresentationConfig,make_presentation_tools


def fixture(tmp_path,*,long=False):
    pdf=tmp_path/'source.pdf'
    with fitz.open() as d:
        d.new_page();d.new_page();d.save(pdf)
    image=tmp_path/'figure.png';Image.new('RGB',(120,60),'white').save(image)
    text='完整原文α中文与English。'*600 if long else 'first source paragraph'
    manifest=dict(schema_version='pdf-assets-prototype/v1',revision=2,source=dict(pdf_path=str(pdf),sha256='a'*64),
        source_ambiguities=[dict(statement='Stored source uncertainty',source_page=1)],reviews=[],assets=[
        dict(asset_id='text-b',type='text',source_page=1,version=1,reading_order=2,text='second paragraph'),
        dict(asset_id='text-a',type='text',source_page=1,version=1,reading_order=1,text=text),
        dict(asset_id='fig-1',type='image',source_page=1,version=2,caption='Fig. 1. Original caption',path=str(image),
            semantic_description='Existing auxiliary meaning',structure_description='Two panels',description_status='current',
            description_provenance=dict(asset_version=2,source_sha256='a'*64),review_status='pass'),
        dict(asset_id='table-1',type='table',source_page=1,version=1,captions=['Table 1. Original'],table_body='<table><tr><td>4.07</td></tr></table>',path=str(image)),
        dict(asset_id='eq-1',type='equation',source_page=1,version=1,equation='y=x+1')])
    p=tmp_path/'manifest.json';p.write_text(json.dumps(manifest,ensure_ascii=False),encoding='utf-8')
    return p,manifest


def test_original_content_order_geometry_legacy_fields_and_gaps(tmp_path):
    p,m=fixture(tmp_path);before=p.read_bytes();package=build_paper_context(str(p))
    r=package['context']['pages'][0]['records'];ids=[a['asset_id'] for a in r]
    assert ids.index('text-a')<ids.index('text-b')
    index={a['asset_id']:a for a in r}
    assert index['text-a']['text']=='first source paragraph'
    assert index['fig-1']['captions']==['Fig. 1. Original caption']
    assert index['fig-1']['geometry']['aspect_ratio']==2.0
    assert index['fig-1']['semantic_description']=='Existing auxiliary meaning'
    assert index['table-1']['table_text']==m['assets'][3]['table_body']
    assert index['eq-1']['text']=='y=x+1'
    assert package['context']['source_notes']==m['source_ambiguities']
    assert package['coverage']['empty_pages']==[2]
    assert package['coverage']['asset_count']==5 and package['coverage']['visual_count']==2
    assert not index['fig-1']['is_verified'] # a pass label without current report is not verified
    assert p.read_bytes()==before
    assert 'description_provenance' not in index['fig-1'] and 'source_sha256' not in index['fig-1']


def test_oversized_page_and_single_record_are_losslessly_segmented(tmp_path):
    p,m=fixture(tmp_path,long=True);package=build_paper_context(str(p),input_budget_tokens=700)
    assert len(package['segments'])>1
    chunks=[];whole={}
    for i in range(len(package['segments'])):
        s=select_segment(package,i)
        assert s['size']['segment_estimated_tokens'][i]<=700
        for page in s['segment']['pages']:
            for r in page['records']:
                if r['asset_id']=='text-a':
                    if 'fragments' in r:chunks.extend(f for f in r['fragments'] if f['field']=='text')
                    else:whole['text']=r['text']
    chunks.sort(key=lambda c:c['start'])
    assert chunks and chunks[0]['start']==0
    assert all(a['end']==b['start'] for a,b in zip(chunks,chunks[1:]))
    assert ''.join(c['text'] for c in chunks)==m['assets'][1]['text']
    assert package['coverage']['source_text_not_truncated']
    assert json.loads(context_input('Plan source',package))['delivery']['pending_segments']
    with pytest.raises(ValueError):select_segment(package,len(package['segments']))


def test_stale_descriptions_and_missing_files_are_explicit(tmp_path):
    p,m=fixture(tmp_path);m['assets'][2]['version']=3;m['assets'][3]['path']=str(tmp_path/'missing.png')
    p.write_text(json.dumps(m),encoding='utf-8');package=build_paper_context(str(p))
    idx={r['asset_id']:r for pg in package['context']['pages'] for r in pg['records']}
    assert idx['fig-1']['description_status']=='stale' and not idx['fig-1']['semantic_description']
    assert any(r['kind']=='missing_visual_file' for r in package['coverage']['missing_records'])


def test_native_tool_returns_complete_bounded_material_not_excerpt(tmp_path):
    p,m=fixture(tmp_path);tools={t.name:t for t in make_presentation_tools(PresentationConfig(workspace=tmp_path/'work'))}
    result=tools['get_paper_context'].invoke_result(dict(manifest_path=str(p)))
    rendered=json.loads(result.content)
    assert rendered['segment']['pages'][0]['records'][0]['text']=='first source paragraph'
    assert rendered['next_segment_index'] is None and result.result_ref
    assert result.value['coverage']['all_manifest_assets_included']
    with pytest.raises(Exception):tools['get_paper_context'].invoke_result(dict(manifest_path=str(p),segment_index=-1))


def test_formal_application_input_is_user_data_and_has_full_coverage(tmp_path):
    from ppt_agent_api.services import prepare_paper_context_input
    p,m=fixture(tmp_path)
    data=json.loads(prepare_paper_context_input('Read this paper',str(p)))
    assert data['user_task']=='Read this paper'
    assert data['paper_context']['coverage']['asset_count']==5
    assert data['delivery']['complete_material_in_initial_request']
