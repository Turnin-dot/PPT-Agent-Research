"""Synthetic faults prove capability boundaries, not real-model autonomy."""
import json
from pathlib import Path

import fitz
import pytest

from agent_harness.core import FakeModel, ToolCall
from ppt_agent_api.services.agent_runtime import build_ppt_agent_harness
from ppt_agent_domain.pdf_assets import PdfAssetConfig
from ppt_agent_domain.presentation import PresentationConfig, make_presentation_tools
from ppt_agent_domain.presentation.storage import sha256_file


def missing_image_fixture(root):
    root.mkdir(parents=True,exist_ok=True)
    pdf=root/'source.pdf'
    with fitz.open() as doc:
        page=doc.new_page(width=300,height=200)
        page.draw_rect(fitz.Rect(30,30,230,150),color=(0,0,1))
        page.insert_text((50,80),'Synthetic scientific figure')
        doc.save(pdf)
    manifest=root/'manifest.json'
    manifest.write_text(json.dumps(dict(schema_version='pdf-assets-prototype/v1',revision=1,
        source=dict(pdf_path=str(pdf),sha256=sha256_file(pdf)),assets=[dict(asset_id='figure-1',type='image',version=1,
        source_page=1,bbox=[30,30,230,150],bbox_coordinate_space='pdf_points',path=str(root/'missing.png'),
        captions=['Synthetic figure'],text='',review_status='not_reviewed')],reviews=[],issues=[],change_log=[])),encoding='utf8')
    return manifest


@pytest.mark.parametrize('profile,restored',[('full',True),('production',False)])
def test_asset_crop_recovery_through_formal_harness(profile,restored,tmp_path):
    manifest=missing_image_fixture(tmp_path/profile/'assets')
    before=manifest.read_bytes()
    model=FakeModel([
        [ToolCall('get_asset',dict(manifest_path=str(manifest),asset_id='figure-1'))],
        [ToolCall('crop_pdf_asset',dict(manifest_path=str(manifest),asset_id='figure-1',page_number=1,bbox=[30,30,230,150]))],
        'Recovery probe complete; report only observed state.',
    ])
    harness=build_ppt_agent_harness(workspace=tmp_path/profile/'agent',model=model,tool_profile=profile,
        pdf_asset_config=PdfAssetConfig(workspace=tmp_path/profile/'pdf-tools'))
    try:
        results=[e.data['message'] for e in harness.run('Restore only the missing synthetic figure through formal tools.') if e.type=='tool_result']
        crop=next(r for r in results if r.name=='crop_pdf_asset')
        assert crop.is_error is not restored
        actual=json.loads(manifest.read_text(encoding='utf8'))
        assert Path(actual['assets'][0]['path']).is_file() is restored
        if restored:
            assert actual['revision']==2 and actual['assets'][0]['version']==2
        else:
            assert manifest.read_bytes()==before
    finally:harness.close()


@pytest.mark.parametrize('profile,updated',[('full',True),('production',False)])
def test_planning_recovery_boundary_is_explicit_without_silent_grant(profile,updated,tmp_path):
    config=PresentationConfig(workspace=tmp_path/profile/'tasks')
    tools={t.name:t for t in make_presentation_tools(config)}
    tools['save_brief'].invoke_result(dict(task_id='paper',user_goal='Synthetic planning recovery'))
    tools['save_slide_plan'].invoke_result(dict(task_id='paper',slide_id='s1',goal='original goal',content_markdown='Original',layout_intent='one region'))
    model=FakeModel([[ToolCall('save_slide_plan',dict(task_id='paper',slide_id='s1',goal='revised goal',content_markdown='Revised',layout_intent='two regions'))],'Probe finished.'])
    harness=build_ppt_agent_harness(workspace=tmp_path/profile/'agent',model=model,tool_profile=profile,presentation_config=config)
    try:
        results=[e.data['message'] for e in harness.run('Synthetic planning recovery probe.') if e.type=='tool_result']
        assert len(results)==1 and results[0].is_error is not updated
        state=tools['get_task_state'].invoke_result(dict(task_id='paper')).value
        assert state['slide_plans']['s1']['version']==(2 if updated else 1)
        # Full remains the product default; neither profile silently expands.
        assert ('save_slide_plan' in {t.name for t in harness.tools}) is updated
    finally:harness.close()
