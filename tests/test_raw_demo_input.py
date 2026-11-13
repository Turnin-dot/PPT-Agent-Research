import json
from pathlib import Path
import fitz
import pytest
from demos.raw_input import prepare_raw_pdf,raw_request

def test_raw_pdf_does_not_seed_parsed_assets_or_plans_and_resumes_by_hash(tmp_path):
    pdf=tmp_path/'original.pdf'
    with fitz.open() as d:d.new_page();d.save(pdf)
    w=tmp_path/'run';value=prepare_raw_pdf(w,pdf)
    assert list((w/'input').iterdir())==[w/'input/source.pdf']
    assert not (w/'tasks').exists() and not (w/'input/manifest.json').exists()
    assert prepare_raw_pdf(w,pdf,resume=True)==value
    with pytest.raises(FileExistsError):prepare_raw_pdf(w,pdf)
    request=json.loads(raw_request(value,export=True))
    assert request['task_id']=='sample' and request['slide_id']=='slide-01'
    assert request['input_kind']=='raw_pdf' and 'validate_delivery' in request['delivery']
    (w/'input/source.pdf').write_bytes(b'changed')
    with pytest.raises(ValueError,match='changed'):prepare_raw_pdf(w,pdf,resume=True)


def test_real_cli_raw_branch_does_not_require_prebuilt_manifest(tmp_path,monkeypatch):
    import sys
    import demos.single_page as entry
    from agent_harness.core import FakeModel
    pdf=tmp_path/'input.pdf'
    with fitz.open() as d:d.new_page();d.save(pdf)
    for key in ['DASHSCOPE_API_KEY','ARK_API_KEY','DEEPSEEK_API_KEY']:monkeypatch.setenv(key,'offline-test-value')
    captured_model_kwargs={}
    def fake_factory(*a,**kw):
        captured_model_kwargs.update(kw)
        return FakeModel([])
    monkeypatch.setattr(entry,'init_chat_model',fake_factory)
    monkeypatch.setattr(entry,'run_logged',lambda *a,**kw:([],dict(error=None)))
    w=tmp_path/'run'
    monkeypatch.setattr(sys,'argv',['single_page','--run','--pdf',str(pdf),'--output',str(w)])
    with pytest.raises(SystemExit,match='not formally approved'):entry.main()
    request=json.loads(json.loads((w/'agent-request.json').read_text(encoding='utf8'))['request'])
    assert request['input_kind']=='raw_pdf' and request['task_id']=='sample'
    assert not list(w.rglob('manifest.json'))
    assert captured_model_kwargs['max_retries']==3
