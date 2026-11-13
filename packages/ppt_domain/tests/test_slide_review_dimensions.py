import json
from pathlib import Path

import pytest

from ppt_agent_domain.presentation.slide_review import normalize, source_reference_issues
from ppt_agent_domain.presentation.service import PresentationService
from ppt_agent_domain.presentation.storage import mark_slide_reports_stale


def issue(**kw):
    return dict(element_id='formula',location='下部公式',category='formula',severity='error',
                description='残差被并入DW定义',basis='规划DW定义不含残差加法',suggestion='恢复DW定义并将相加另列',**kw)


def test_pass_cannot_hide_important_fact_error():
    r=normalize(dict(verdict='pass',issues=[issue()]),'content','slide-05',{'formula'})
    assert r['verdict']=='needs_revision'
    assert r['issues'][0]['slide_id']=='slide-05'


def test_source_mapping_loss_is_deterministic_blocker(tmp_path):
    binding=dict(elements=[dict(element_id='figure',asset_refs=[dict(object_id='fig2',version=1,manifest_path=None)])])
    issues=source_reference_issues(binding)
    assert issues and issues[0]['severity']=='error'
    p=tmp_path/'binding.json';p.write_text(json.dumps(binding))
    with pytest.raises(ValueError,match='Manifest source mapping'):
        PresentationService._check_export_source('s',dict(binding=dict(path=str(p))))


@pytest.mark.parametrize('field',['location','basis','suggestion'])
def test_feedback_requires_position_evidence_action(field):
    i=issue();i.pop(field)
    with pytest.raises(ValueError):normalize(dict(verdict='needs_revision',issues=[i]),'content','s',{'formula'})


def test_unknown_html_id_is_not_a_valid_repair_target():
    with pytest.raises(ValueError):normalize(dict(verdict='needs_revision',issues=[issue()]),'visual','s',{'other'})


def test_compound_known_ids_preserve_all_findings_and_blocking_severity():
    finding=issue();finding['element_id']='formula + caption'
    result=normalize(dict(verdict='pass',issues=[finding]),'visual','s',{'formula','caption'})
    assert result['verdict']=='needs_revision'
    assert [item['element_id'] for item in result['issues']]==['formula','caption']
    assert [item['issue_id'] for item in result['issues']]==['visual-1','visual-2']
    assert all(item['severity']=='error' and item['basis']==finding['basis'] for item in result['issues'])


def test_compound_ids_cannot_silently_drop_an_unknown_element():
    finding=issue();finding['element_id']='formula + invented'
    with pytest.raises(ValueError,match='unknown element_id'):
        normalize(dict(verdict='pass',issues=[finding]),'visual','s',{'formula'})


def test_new_version_invalidates_both_dimensions(tmp_path):
    slide={}
    for key in ('content_review','visual_review','review'):
        p=tmp_path/(key+'.json');p.write_text(json.dumps(dict(applicability='current',is_verified=True)))
        slide[key]=dict(path=str(p),applicability='current')
    task=dict(slides={'s':slide})
    mark_slide_reports_stale(task,'s')
    for key in slide:
        assert slide[key]['applicability']=='stale'
        assert not json.loads(Path(slide[key]['path']).read_text())['is_verified']


def test_legacy_single_pass_cannot_replace_dual_approval(tmp_path):
    html=tmp_path/'slide.html';html.write_text('<h1>OK</h1>')
    slide=dict(html=dict(version=1,path=str(html)))
    for key in ('preview','layout_report','review'):
        p=tmp_path/(key+'.json');p.write_text(json.dumps(dict(review_verdict='pass',html_version=1)))
        slide[key]=dict(html_version=1,path=str(p),applicability='current',review_verdict='pass')
    with pytest.raises(ValueError,match='content_review'):
        PresentationService._check_export_source('s',slide)


def test_explicit_preference_is_nonblocking_only_after_complete_visual_check():
    finding=dict(issue(),severity='warning',finding_type='optional_preference')
    result=normalize(dict(verdict='needs_revision',checks_complete=True,issues=[finding]),'visual','s',{'formula'})
    assert result['verdict']=='pass' and result['issues'][0]['blocking'] is False
    assert result['issues'][0]['suggestion']==finding['suggestion']
    incomplete=normalize(dict(verdict='needs_revision',checks_complete=False,issues=[finding]),'visual','s',{'formula'})
    assert incomplete['verdict']=='uncertain'
    # Unclassified warnings and uncertain coverage are never auto-approved.
    legacy=normalize(dict(verdict='needs_revision',checks_complete=True,issues=[dict(issue(),severity='warning')]),'visual','s',{'formula'})
    assert legacy['verdict']=='needs_revision'
    uncertain=normalize(dict(verdict='uncertain',checks_complete=True,issues=[finding]),'visual','s',{'formula'})
    assert uncertain['verdict']=='uncertain'


@pytest.mark.parametrize('core,expected',[(True,'uncertain'),(False,'pass')])
def test_evidence_gap_is_not_proof_of_a_fact_error(core,expected):
    finding=dict(issue(),severity='warning',finding_type='evidence_gap',affects_core_content=core)
    result=normalize(dict(verdict='pass',checks_complete=True,issues=[finding]),'content','s',{'formula'})
    assert result['verdict']==expected
    assert result['issues'][0]['blocking'] is core


@pytest.mark.parametrize('updates,dimension',[
    (dict(finding_type='optional_preference'),'visual'),
    (dict(finding_type='optional_preference',severity='warning'),'content'),
    (dict(finding_type='evidence_gap',severity='warning'),'content'),
    (dict(finding_type='evidence_gap',severity='warning',affects_core_content='false'),'content'),
    (dict(finding_type='optional_preference',severity='warning',blocking=True),'visual'),
    (dict(finding_type='optional_preference',severity='warning',affects_core_content=True),'visual'),
])
def test_invalid_classification_is_rejected_not_downgraded(updates,dimension):
    with pytest.raises(ValueError):
        normalize(dict(verdict='pass',issues=[dict(issue(),**updates)]),dimension,'s',{'formula'})


def test_confirmed_critical_error_blocks_even_with_other_preferences_and_missing_evidence():
    result=normalize(dict(verdict='pass',checks_complete=False,issues=[
        dict(issue(),finding_type='confirmed_defect',blocking=False),
        dict(issue(),finding_type='optional_preference',severity='warning'),
    ]),'visual','s',{'formula'})
    assert result['verdict']=='needs_revision'
    assert result['issues'][0]['blocking'] is True


