import pytest

from ppt_agent_domain.presentation import PresentationConfig,make_presentation_tools
from ppt_agent_domain.pdf_assets.storage import sha256_file


def test_agent_can_read_current_page_artifacts_through_domain_tool_without_full_deck_injection(tmp_path):
    tools={t.name:t for t in make_presentation_tools(PresentationConfig(workspace=tmp_path/'domain-tasks'))}
    def call(name,**args):return tools[name].invoke_result(args).value
    call('save_brief',task_id='paper',user_goal='Offline task fixture')
    sources=[]
    for sid,text in (('slide-01','PAGE_ONE'),('slide-02','PAGE_TWO')):
        call('save_slide_plan',task_id='paper',slide_id=sid,goal=text,content_markdown=text,layout_intent='one topic')
        body=text+(' scientific facts'*450+' END_OF_CURRENT_HTML' if sid=='slide-01' else '')
        html=tmp_path/(sid+'.html');html.write_text(f'<div id="title" data-pptx="text">{body}</div>',encoding='utf8');sources.append(html)
        call('save_slide_binding',task_id='paper',slide_id=sid,html_path=str(html),
            elements=[dict(element_id='title',role='title',generated_decoration=True)],expected_plan_version=1)
    taskpath=tmp_path/'domain-tasks/paper/task.json'
    before=[sha256_file(p) for p in [taskpath,*sources]]
    scoped=call('get_task_state',task_id='paper',slide_id='slide-01')
    assert set(scoped['slides'])==set(scoped['slide_plans'])=={'slide-01'}
    assert scoped['summary']['slide_plan_count']==2 and scoped['read_only'] is True
    details=scoped['slide_details']
    assert details['plan']['plan']['goal']=='PAGE_ONE'
    assert details['binding']['plan_version']==scoped['slide_plans']['slide-01']['version']
    assert 'PAGE_ONE' in details['html_text'] and 'PAGE_TWO' not in str(scoped)
    assert scoped['retrieval_scope']=='single_slide' and details['visual_review'] is None
    from ppt_agent_domain.presentation.result_schemas import GetTaskStateResult,render_result
    import json
    rendered=json.loads(render_result(GetTaskStateResult.model_validate(scoped)))
    assert rendered['summary_only'] is False and 'END_OF_CURRENT_HTML' in rendered['slide_details']['html_text']
    only_binding=call('get_task_state',task_id='paper',slide_id='slide-01',detail_sections=['binding'])
    assert set(only_binding['slide_details'])=={'slide_id','binding'}
    assert only_binding['slide_details']['binding']==details['binding']
    with pytest.raises(ValueError,match='requires slide_id'):
        call('get_task_state',task_id='paper',detail_sections=['binding'])
    with pytest.raises(ValueError):
        call('get_task_state',task_id='paper',slide_id='slide-01',detail_sections=['not-a-section'])
    oversized={**scoped,'slide_details':{**details,'html_text':'X'*70000+' UNCHANGED_TAIL'}}
    projected=json.loads(render_result(GetTaskStateResult.model_validate(oversized)))
    assert projected['summary_only'] is True
    assert oversized['slide_details']['html_text'].endswith('UNCHANGED_TAIL')
    global_index=call('get_task_state',task_id='paper')
    assert len(global_index['slides'])==2 and 'slide_details' not in global_index
    with pytest.raises(ValueError,match='slide_id not found'):
        call('get_task_state',task_id='paper',slide_id='slide-99')
    assert before==[sha256_file(p) for p in [taskpath,*sources]]
    # The domain tool remains usable when its task files are outside the
    # coding workspace; the Agent need not probe those paths with read_file.
    from agent_harness.core import FakeModel,ToolCall
    from agent_harness.core.messages import ToolMessage
    from ppt_agent_api.services import build_ppt_agent_harness
    model=FakeModel([[ToolCall('get_task_state',dict(task_id='paper',slide_id='slide-01'))],'Read the scoped page.'])
    harness=build_ppt_agent_harness(workspace=tmp_path/'isolated-agent',model=model,
        presentation_config=PresentationConfig(workspace=tmp_path/'domain-tasks'))
    try:
        events=list(harness.run('Read the current page through its domain tool.'))
        messages=[e.data['message'] for e in events if e.type=='tool_result']
        assert len(messages)==1 and isinstance(messages[0],ToolMessage) and not messages[0].is_error
        assert 'PAGE_ONE' in messages[0].content and 'PAGE_TWO' not in messages[0].content
        assert len(messages[0].content)>5500 and 'END_OF_CURRENT_HTML' in messages[0].content
    finally:harness.close()
