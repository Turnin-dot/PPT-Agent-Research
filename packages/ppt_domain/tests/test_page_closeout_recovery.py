"""Offline public-tool regressions; no paper edits, browser or paid model required."""
import json
from pathlib import Path

import pytest
from PIL import Image

from agent_harness.core import FakeModel, ToolCall
from agent_harness.core.messages import AIMessage, ToolMessage
from agent_harness.core.tools import run_tool_calls
from ppt_agent_domain.presentation import PresentationConfig, PresentationService, make_presentation_tools
from ppt_agent_domain.presentation.storage import read_json, sha256_file


@pytest.fixture
def page(tmp_path, monkeypatch):
    browser_calls=[]

    def browser(self, script, args, **kwargs):
        assert script=='render_html.mjs'
        browser_calls.append(list(args))
        image=Path(args[args.index('--output')+1])
        metadata=Path(args[args.index('--metadata')+1])
        Image.new('RGB',(160,90),'white').save(image)
        metadata.write_text(json.dumps(dict(viewport=dict(width=1600,height=900),
            elements=[dict(id='title',type='text',font_size_px=32,text='Offline fixture')],diagnostics={})),encoding='utf8')

    monkeypatch.setattr(PresentationService,'_run_node',browser)
    config=PresentationConfig(workspace=tmp_path/'tasks')
    tools={t.name:t for t in make_presentation_tools(config)}
    def call(name,**args):return tools[name].invoke_result(args).value
    call('save_brief',task_id='paper',user_goal='offline recovery fixture')
    call('save_slide_plan',task_id='paper',slide_id='s1',goal='fixture',content_markdown='fixture',layout_intent='one block')
    html=tmp_path/'source.html';html.write_text('<div id="title" data-pptx="text">Offline fixture</div>',encoding='utf8')
    args=dict(task_id='paper',slide_id='s1',html_path=str(html),elements=[dict(element_id='title',role='title',generated_decoration=True)])
    return PresentationService(config),call,args,browser_calls,tools


def test_save_render_inspect_is_one_public_call_and_retries_are_idempotent(page):
    ppt,call,args,browser_calls,_=page
    result=call('save_slide_binding',**args,check_layout=True)
    assert result['closeout']['execution_status']=='succeeded'
    assert result['closeout']['review_completed'] is False
    assert len(browser_calls)==1 and result['html_ref']['version']==1
    assert result['closeout']['progress']['ready_for_export'] is False
    assert 'review_slide:content' in result['closeout']['progress']['pending_actions']
    task_path,task=ppt._task('paper');before=task_path.read_bytes()
    reused=call('save_slide_binding',**args,check_layout=True)
    assert reused['reused'] and all(step['reused'] for step in reused['closeout']['steps'].values())
    assert reused['task_revision']==result['task_revision'] and len(browser_calls)==1
    assert task_path.read_bytes()==before
    # The packaged path is a valid recovery input, not an extra HTML version.
    packaged=call('save_slide_binding',**dict(args,html_path=result['html_ref']['path']),check_layout=True)
    assert packaged['reused'] and packaged['html_ref']['version']==1
    with pytest.raises(ValueError,match='review'):
        ppt.export_editable_pptx('paper',slide_ids=['s1'],output_path='',expected_revision=None)


@pytest.mark.parametrize('stage',['render','inspect'])
def test_interruption_preserves_binding_and_resumes_at_failed_step(page,monkeypatch,stage):
    ppt,call,args,browser_calls,_=page
    name='render_html_slide' if stage=='render' else 'inspect_html_layout'
    original=getattr(PresentationService,name)
    with monkeypatch.context() as m:
        def fail(*a,**kw):raise RuntimeError('offline injected '+stage+' failure')
        m.setattr(PresentationService,name,fail)
        result=call('save_slide_binding',**args,check_layout=True)
    assert result['execution_status']=='succeeded'  # Binding, not QA, was saved.
    assert result['closeout']['execution_status']=='partial' and result['closeout']['failed_step']==stage
    assert Path(result['binding_ref']['path']).is_file()
    assert getattr(PresentationService,name)==original
    recovered=call('save_slide_binding',**args,check_layout=True)
    assert recovered['reused'] and recovered['closeout']['execution_status']=='succeeded'
    assert recovered['html_ref']['version']==1 and len(browser_calls)==1


def test_plan_change_cannot_reuse_a_stale_binding_and_revision_guard_remains(page):
    ppt,call,args,_,_=page
    first=call('save_slide_binding',**args,check_layout=True)
    call('save_slide_plan',task_id='paper',slide_id='s1',goal='updated',content_markdown='updated',layout_intent='one block')
    with pytest.raises(ValueError,match='revision conflict'):
        call('save_slide_binding',**args,expected_task_revision=first['task_revision'])
    with pytest.raises(ValueError,match='plan version conflict'):
        call('save_slide_binding',**args,expected_plan_version=1)
    with pytest.raises(ValueError,match='stale plan'):
        ppt.review_slide('paper','s1',html_version=1,scope='all',force=False)
    second=call('save_slide_binding',**args,check_layout=True,expected_plan_version=2)
    assert not second['reused'] and second['binding_ref']['version']==2
    assert read_json(Path(second['binding_ref']['path']))['plan_version']==2
    assert first['html_ref']['path']!=second['html_ref']['path']


def test_progress_view_is_readonly_small_and_keeps_full_details_available(page):
    ppt,call,args,_,tools=page
    result=call('save_slide_binding',**args,check_layout=True)
    path,_=ppt._task('paper');before=sha256_file(path)
    full=call('get_task_state',task_id='paper',slide_id='s1')
    progress=call('get_task_state',task_id='paper',view='progress')
    assert 'slide_details' not in progress and 'change_log' not in progress
    assert progress['page_progress']['s1']['html_version']==result['html_ref']['version']
    assert 'html_text' in full['slide_details'] and progress['read_only']
    assert len(json.dumps(progress))<len(json.dumps(full)) and sha256_file(path)==before
    messages=run_tool_calls([ToolCall('get_task_state',dict(task_id='paper',view='progress'))],tools,parallel=False)
    assert isinstance(messages[0],ToolMessage) and not messages[0].is_error
    assert 'pending_actions' in messages[0].content and 'html_text' not in messages[0].content
    with pytest.raises(ValueError,match='excludes'):
        call('get_task_state',task_id='paper',view='progress',include_history=True)


def test_preview_and_layout_cache_never_hide_bound_html_or_resource_changes(page,tmp_path):
    ppt,call,args,browser_calls,_=page
    image=tmp_path/'figure.png';Image.new('RGB',(20,20),'white').save(image)
    Path(args['html_path']).write_text(f'<img id="title" src="{image.as_uri()}">',encoding='utf8')
    result=call('save_slide_binding',**args,check_layout=True)
    packaged=Path(result['html_ref']['staged_resources'][0]);packaged.write_bytes(b'changed')
    with pytest.raises(ValueError,match='resource'):
        ppt.render_html_slide('paper','s1',html_version=1,force=False)
    repaired=call('save_slide_binding',**args,check_layout=True)
    assert not repaired['reused'] and repaired['html_ref']['version']==2
    Path(repaired['html_ref']['path']).write_text('<div id="title">tampered</div>',encoding='utf8')
    with pytest.raises(ValueError,match='HTML changed'):
        ppt.inspect_html_layout('paper','s1',html_version=2,minimum_font_px=18,force_render=False)


def test_layout_cache_depends_on_check_parameters_and_renderer_metadata(page):
    ppt,call,args,browser_calls,_=page
    call('save_slide_binding',**args,check_layout=True)
    original=ppt.inspect_html_layout('paper','s1',html_version=1,minimum_font_px=18,force_render=False)
    assert original['reused']
    changed=ppt.inspect_html_layout('paper','s1',html_version=1,minimum_font_px=40,force_render=False)
    assert not changed['reused'] and changed['report_version']==original['report_version']+1
    assert any(i['category']=='readability' for i in changed['issues'])
    assert ppt.inspect_html_layout('paper','s1',html_version=1,minimum_font_px=40,force_render=False)['reused']
    assert len(browser_calls)==1


def test_valid_uncertain_after_contract_retry_is_successful_persistent_and_reused(page):
    ppt,call,args,_,_=page
    call('save_slide_binding',**args,check_layout=True)
    content=FakeModel([AIMessage(content='not JSON'),AIMessage(content=json.dumps(dict(verdict='uncertain',summary='core evidence unavailable',issues=[])))])
    visual=FakeModel([AIMessage(content=json.dumps(dict(verdict='pass',summary='visual checked',issues=[])))])
    ppt.config.content_review_model_factory=lambda:content
    ppt.config.model_factory=lambda:visual
    first=ppt.review_slide('paper','s1',html_version=1,scope='all',force=False)
    report=read_json(Path(first['dimensions']['content']['report_path']))
    assert report['execution_status']=='succeeded' and report['review_verdict']=='uncertain' and report['attempt_count']==2
    assert first['review_verdict']=='uncertain'
    progress=call('get_task_state',task_id='paper',view='progress')['page_progress']['s1']
    assert progress['execution_statuses']['content_review']=='succeeded'
    assert 'resolve_evidence_gap:content' in progress['pending_actions']
    _,task=ppt._task('paper');revision=task['revision']
    second=ppt.review_slide('paper','s1',html_version=1,scope='all',force=False)
    assert second['reused'] and second['task_revision']==revision
    assert len(content.calls)==2 and len(visual.calls)==1 and second['model_usage']['input_tokens']==0
    assert ppt._task('paper')[1]['revision']==revision
    with pytest.raises(ValueError,match='not a current passed review'):
        ppt.export_editable_pptx('paper',slide_ids=['s1'],output_path='',expected_revision=None)


def test_harness_executes_save_and_local_closeout_without_extra_model_tool_calls(page,tmp_path):
    from ppt_agent_api.services.agent_runtime import build_ppt_agent_harness
    ppt,_,args,browser_calls,_=page
    model=FakeModel([[ToolCall('save_slide_binding',dict(args,check_layout=True))],'Local checks saved; model review remains pending.'])
    harness=build_ppt_agent_harness(workspace=tmp_path/'agent',model=model,
        presentation_config=ppt.config,tool_profile='production')
    try:
        results=[e.data['message'] for e in harness.run('Save the fixture with local checks.') if e.type=='tool_result']
        assert len(results)==1 and not results[0].is_error and len(browser_calls)==1
        assert 'review_completed' in results[0].content and 'pending_actions' in results[0].content
        assert len(model.calls)==2  # One tool-bearing response and one completion.
    finally:harness.close()


def test_failed_contract_is_retryable_not_confused_with_an_evidence_gap(page):
    ppt,call,args,_,_=page
    call('save_slide_binding',**args,check_layout=True)
    ppt.config.content_review_model_factory=lambda:FakeModel([AIMessage(content='invalid'),AIMessage(content='still invalid')])
    ppt.review_slide('paper','s1',html_version=1,scope='content',force=False)
    progress=call('get_task_state',task_id='paper',view='progress')['page_progress']['s1']
    assert progress['statuses']['content_review']=='uncertain'
    assert progress['execution_statuses']['content_review']=='failed'
    assert 'review_slide:content' in progress['pending_actions']
    assert 'resolve_evidence_gap:content' not in progress['pending_actions']


def test_contract_comparison_has_identical_first_pass_context_and_no_cross_policy_cache(page):
    ppt,call,args,_,_=page
    call('save_slide_binding',**args,check_layout=True)
    finding=dict(element_id='title',location='title',category='style',severity='warning',
        finding_type='optional_preference',description='could use another accent',basis='visible accent',suggestion='optional color adjustment')
    output=json.dumps(dict(verdict='needs_revision',checks_complete=True,summary='only preference',issues=[finding]))
    visual=FakeModel([AIMessage(content=output),AIMessage(content=output)])
    ppt.config.model_factory=lambda:visual
    ppt.config.review_contract='legacy-v1'
    before=ppt.review_slide('paper','s1',html_version=1,scope='visual',force=False)
    ppt.config.review_contract='classified-v1'
    after=ppt.review_slide('paper','s1',html_version=1,scope='visual',force=False)
    assert len(visual.calls)==2 and not after['reused']
    assert visual.calls[0][1].content==visual.calls[1][1].content
    assert visual.calls[0][1].images==visual.calls[1][1].images
    assert visual.calls[0][0].content!=visual.calls[1][0].content
    first=read_json(Path(before['dimensions']['visual']['report_path']))
    second=read_json(Path(after['dimensions']['visual']['report_path']))
    assert first['review_verdict']=='needs_revision' and second['review_verdict']=='pass'
    assert first['input_context_sha256']==second['input_context_sha256']
    # Content has not been reviewed, so aggregate remains uncertain, not approved.
    assert after['review_verdict']=='uncertain'
    assert ppt.config.review_contract=='classified-v1'
