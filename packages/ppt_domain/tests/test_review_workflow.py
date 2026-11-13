"""Offline checkpoints and bounded inputs for independent page review."""
import json
from pathlib import Path
import pytest

from ppt_agent_domain.pdf_assets.storage import read_json, write_json, sha256_file
from ppt_agent_domain.presentation.planning import PlanningService
from ppt_agent_domain.presentation.planning_review_workflow import ReviewWorkflow
from ppt_agent_domain.presentation.planning_review import ReviewSubmission


def fixture(tmp_path):
    pdf=tmp_path/'source.pdf';pdf.write_bytes(b'fixture PDF')
    md=tmp_path/'full.md';md.write_text('# Paper\n\nFull source text.',encoding='utf-8')
    manifest=tmp_path/'manifest.json'
    write_json(manifest,dict(schema_version='pdf-assets-prototype/v1',revision=1,
        source=dict(pdf_path=str(pdf),sha256=sha256_file(pdf)),mineru=dict(markdown_path=str(md)),
        assets=[],reviews=[]))
    planning=tmp_path/'initial'
    write_json(planning/'paper_understanding.json',dict(title='Paper',research_problem={'statement':'Question'},method_overview={'statement':'Method'}))
    slides=[dict(slide_index=i,slide_title=f'Page {i}',slide_purpose='Explain source',key_message='Fact',
        main_points=['Fact'],asset_ids=[],evidence_refs=[]) for i in (1,2)]
    write_json(planning/'presentation_plan.json',dict(target_audience='research group',narrative_structure=['problem','method'],slides=slides))
    return manifest,planning


def test_page_review_checkpoint_resume_global_and_revision_input(tmp_path):
    manifest,planning=fixture(tmp_path)
    flow=ReviewWorkflow(tmp_path/'run',manifest,planning,user_task='two-page review',reviewer_model='qwen:qwen3.8-flash')
    packet=json.loads(flow.page_input(1))
    assert packet['batch_size']==2 and packet['ppt_page']==1 and len(packet['overview']['slides'])==2
    assert 'Full source text.' not in flow.page_input(1)
    one=flow.save_tool(1,[])
    args=dict(summary='Checked page',reviewed_topics=['logic'],issues=[])
    result=one.invoke_result(args).value
    assert Path(result['path']).is_file() and flow.completed(1)
    assert one.invoke_result(args).value['path']==result['path']
    flow.mark_incomplete(2,'budget exhausted')
    assert read_json(flow.version_root/'page_02.incomplete.json')['status']=='incomplete'
    with pytest.raises(ValueError,match='All page reviews'):
        flow.global_input()
    two=flow.save_tool(2,[])
    with pytest.raises(Exception):
        two.invoke_result(dict(summary='bad',reviewed_topics=['facts'],issues=[dict(issue_id='E',severity='critical',blocking=True,
            category='scientific_fact',affected_slides=[2],description='wrong',suggested_action='fix',evidence_refs=[])]))
    assert not flow.completed(2)
    two.invoke_result(args)
    assert len(json.loads(flow.global_input())['page_reviews'])==2
    flow.save_tool(None,[]).invoke_result(dict(summary='Global checked',reviewed_topics=['coverage'],issues=[]))
    finalized=flow.finalize(tmp_path/'revision_workspace')
    service=PlanningService(tmp_path/'revision_workspace',manifest,user_task='two-page review',reviewer_model='qwen:qwen3.8-flash')
    revision=json.loads(service.input('revision'))
    assert revision['feedback']['binding']['planning_sha256']==flow.binding.planning_sha256
    assert read_json(Path(finalized['summary_path']))['reviewed_pages']==2
    old=flow.page_path(1)
    changed=read_json(planning/'presentation_plan.json');changed['slides'][0]['key_message']='Changed'
    write_json(planning/'presentation_plan.json',changed)
    with pytest.raises(ValueError,match='changed'):flow.page_input(2)
    new=ReviewWorkflow(tmp_path/'run',manifest,planning,user_task='two-page review',reviewer_model='qwen:qwen3.8-flash')
    assert not new.completed(1) and old.is_file() and new.version_root!=flow.version_root


def test_review_harness_saves_only_current_page(tmp_path):
    from agent_harness.core.messages import ToolCall
    from agent_harness.core.models import FakeModel
    from ppt_agent_api.services.review_runtime import build_ppt_review_harness
    manifest,planning=fixture(tmp_path)
    flow=ReviewWorkflow(tmp_path/'run',manifest,planning,user_task='review',reviewer_model='qwen:qwen3.8-flash')
    fake=FakeModel([[ToolCall('submit_page_review',dict(summary='Checked',reviewed_topics=['logic'],issues=[]))]])
    harness,packet=build_ppt_review_harness(flow,page_id=1,model_factory=lambda phase:fake)
    assert len(json.loads(packet)['overview']['slides'])==2
    try:
        for event in harness.run(packet):
            if event.type=='tool_result' and event.data['message'].name=='submit_page_review':
                assert not event.data['message'].is_error
                harness.agent.interrupt()
    finally:harness.close()
    assert flow.completed(1) and not flow.completed(2)


def test_qwen_uncertain_field_typo_accepts_valid_certainty_only():
    issue=dict(issue_id='I',severity='major',blocking=True,category='scientific_fact',
        affected_slides=[1],description='Source conflict',suggested_action='Correct claim',
        evidence_refs=[dict(source_kind='pdf_page',source_page=1,quote='Source page')],uncertain='uncertain')
    checked=ReviewSubmission.model_validate(dict(summary='Reviewed',reviewed_topics=['facts'],issues=[issue]))
    assert checked.issues[0].certainty=='uncertain'
    bad=dict(issue,uncertain='invented')
    with pytest.raises(Exception):ReviewSubmission.model_validate(dict(summary='Reviewed',reviewed_topics=['facts'],issues=[bad]))


def test_review_advertised_skills_can_actually_be_loaded(tmp_path):
    from agent_harness.core.messages import ToolCall
    from agent_harness.core.models import FakeModel
    from ppt_agent_api.services.review_runtime import build_ppt_review_harness
    manifest,planning=fixture(tmp_path)
    flow=ReviewWorkflow(tmp_path/'run',manifest,planning,user_task='review',reviewer_model='qwen:qwen3.8-flash')
    fake=FakeModel([[ToolCall('read_skill',dict(name='paper-planning'))],
        [ToolCall('submit_page_review',dict(summary='Checked',reviewed_topics=['logic'],issues=[]))]])
    harness,packet=build_ppt_review_harness(flow,page_id=1,model_factory=lambda phase:fake)
    try:
        assert 'read_skill' in {t.name for t in harness.tools}
        loaded=[]
        for event in harness.run(packet):
            if event.type=='tool_result':
                message=event.data['message']
                if message.name=='read_skill':
                    assert not message.is_error and '<skill' in message.content
                    loaded.append(message)
                if message.name=='submit_page_review':harness.agent.interrupt()
        assert loaded and flow.completed(1)
    finally:harness.close()
