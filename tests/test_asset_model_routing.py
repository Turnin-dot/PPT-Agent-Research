"""Approved asset-model routing only; FakeModel, no real vision/API evaluation."""
import json
from pathlib import Path
import pytest
from PIL import Image
from agent_harness.core.models import FakeModel
from ppt_agent_domain.presentation import PresentationConfig,make_presentation_tools
import ppt_agent_domain.presentation.config as cfg

@pytest.mark.parametrize('override',[None,'deepseek:deepseek-flash'])
def test_asset_model_default_and_approved_override(monkeypatch,override):
    if override is None:monkeypatch.delenv('PPT_AGENT_ASSET_INSPECTION_MODEL',raising=False)
    else:monkeypatch.setenv('PPT_AGENT_ASSET_INSPECTION_MODEL',override)
    captured={}
    def factory(spec,**kwargs):
        captured.update(spec=spec,**kwargs)
        return FakeModel([])
    monkeypatch.setattr(cfg,'init_chat_model',factory)
    cfg.default_asset_inspection_model_factory()
    assert captured['spec']=='deepseek:deepseek-flash'
    assert captured['reasoning_effort']=='low'
    assert 'max_tokens' in captured and 'max_completion_tokens' not in captured

@pytest.mark.parametrize('override',['qwen:qwen3.8-max-0902','qwen:qwen3.8-flash'])
def test_unapproved_asset_override_is_rejected_before_model_creation(monkeypatch,override):
    monkeypatch.setenv('PPT_AGENT_ASSET_INSPECTION_MODEL',override)
    def forbidden(*a,**kw):raise AssertionError('Unapproved model client created')
    monkeypatch.setattr(cfg,'init_chat_model',forbidden)
    with pytest.raises(ValueError,match='must use deepseek:deepseek-flash'):
        cfg.default_asset_inspection_model_factory()

@pytest.mark.parametrize('table',[False,True])
def test_real_tool_image_and_table_branches_use_approved_factory(tmp_path,monkeypatch,table):
    monkeypatch.setenv('PPT_AGENT_ASSET_INSPECTION_MODEL','deepseek:deepseek-flash')
    image=tmp_path/'source.png';Image.new('RGB',(40,30),'white').save(image)
    model=FakeModel([json.dumps({'cells':[dict(row=1,column=1,visual_value='4.0',readability='clear',note='Synthetic fixture')]} ) if table else 'Synthetic source description'])
    model.model='deepseek-flash';seen=[]
    def factory(spec,**kwargs):seen.append(spec);return model
    monkeypatch.setattr(cfg,'init_chat_model',factory)
    tools={t.name:t for t in make_presentation_tools(PresentationConfig(workspace=tmp_path/'tasks'))}
    args=dict(prompt='Inspect synthetic source')
    if table:
        manifest=tmp_path/'manifest.json'
        manifest.write_text(json.dumps(dict(schema_version='pdf-assets-prototype/v1',revision=1,source=dict(sha256='a'*64),reviews=[],assets=[dict(asset_id='table-1',version=1,type='table',source_page=1,path=str(image),table_body='<table><tr><td>4.0</td></tr></table>') ])),encoding='utf8')
        args.update(manifest_path=str(manifest),asset_id='table-1',table_cells=[dict(row=1,column=1)],table_header_rows=0)
    else:args['image_path']=str(image)
    result=tools['inspect_image'].invoke_result(args).value
    assert result['internal_model']=='deepseek-flash'
    assert seen==['deepseek:deepseek-flash']
    assert any(getattr(m,'images',None) for m in model.calls[0])
