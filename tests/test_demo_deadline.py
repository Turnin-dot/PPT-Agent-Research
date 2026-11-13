"""Deadline configuration tests; subprocesses are mocked, no model calls."""
import importlib.util,json,sys
from pathlib import Path
import pytest
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('demo_deadline',ROOT/'tools/run_demo_b_timed.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)

@pytest.mark.parametrize('seconds,expected',[(None,900),(900,900),(600,600)])
def test_default_and_explicit_deadline_reach_process_wait(tmp_path,monkeypatch,seconds,expected):
    captured={}
    class Process:
        pid=123
        returncode=0
        def __init__(self,command,**kwargs):captured['command']=command
        def wait(self,timeout):captured['timeout']=timeout;return 0
    monkeypatch.setattr(module.subprocess,'Popen',Process)
    output=tmp_path/'run'
    args=['run_demo_b_timed','--pdf',str(tmp_path/'source.pdf'),'--output',str(output)]
    if seconds is not None:args+=['--seconds',str(seconds)]
    monkeypatch.setattr(sys,'argv',args)
    with pytest.raises(SystemExit) as exc:module.main()
    assert exc.value.code==0
    assert captured['timeout']==expected
    assert json.loads((output/'launch.json').read_text(encoding='utf8'))['deadline_seconds']==expected

@pytest.mark.parametrize('seconds',[0,901])
def test_invalid_deadline_is_rejected_before_launch(tmp_path,monkeypatch,seconds):
    def forbidden(*a,**kw):raise AssertionError('Invalid deadline launched a subprocess')
    monkeypatch.setattr(module.subprocess,'Popen',forbidden)
    monkeypatch.setattr(sys,'argv',['run_demo_b_timed','--pdf','unused.pdf','--output',str(tmp_path/'not-created'),'--seconds',str(seconds)])
    with pytest.raises(ValueError,match='900'):module.main()
    assert not (tmp_path/'not-created').exists()
