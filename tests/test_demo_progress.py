import importlib.util,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('demo_progress',ROOT/'tools/watch_demo_b.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)

def put(p,v):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(v),encoding='utf8')

def test_prepared_manifest_does_not_claim_real_pdf_parse(tmp_path):
    put(tmp_path/'prepared.json',{'input_scope':'fixed synthetic'})
    put(tmp_path/'input/manifest.json',{'schema_version':'pdf-assets-prototype/v1','revision':1,'assets':[{}]})
    state=module.snapshot(tmp_path)
    assert '跳过' in state['阶段']['PDF解析']
    assert state['阶段']['内容审核']=='未保存'
    assert state['阶段']['最终交付验收']=='未保存'

def test_timeout_is_not_displayed_as_running_and_partial_last_line_is_tolerated(tmp_path):
    e={'type':'tool_start','data':{'call':{'id':'a','name':'parse_pdf'}},'ts':1}
    (tmp_path/'run-events.jsonl').write_text(json.dumps(e)+'\n{"unfinished"',encoding='utf8')
    put(tmp_path/'timed-execution.json',{'timed_out':True,'wall_seconds':600,'exit_code':1})
    s=module.snapshot(tmp_path)
    assert '超时' in s['运行状态'] and s['待返回工具']==[]
    assert s['最后提交工具']=='parse_pdf'

def test_raw_manifest_alone_is_not_parse_success_and_error_payload_is_not_echoed(tmp_path):
    put(tmp_path/'prepared.json',{'mode':'raw_pdf'})
    put(tmp_path/'pdf/p/manifest.json',{'schema_version':'pdf-assets-prototype/v1','revision':1,'assets':[{}]})
    e={'type':'tool_result','ts':2,'data':{'message':{'name':'parse_pdf','tool_call_id':'a','is_error':True,'content':'do-not-display-sensitive-payload'}}}
    (tmp_path/'run-events.jsonl').write_text(json.dumps(e)+'\n',encoding='utf8')
    s=module.snapshot(tmp_path)
    assert '尚无解析成功' in s['阶段']['PDF解析']
    assert 'do-not-display-sensitive-payload' not in json.dumps(s)

def test_current_review_and_stale_review_are_distinguished(tmp_path):
    report=tmp_path/'report.json';put(report,{'review_verdict':'pass'})
    put(tmp_path/'tasks/sample/task.json',{'slide_plans':{'slide-01':{}},'slides':{'slide-01':{'html':{'version':2},'content_review':{'html_version':1,'applicability':'current','path':str(report)}}}})
    assert '非当前版本' in module.snapshot(tmp_path)['阶段']['内容审核']

def test_nonexistent_run_can_be_watched_before_creation(tmp_path):
    path=tmp_path/'not-created'
    assert '等待' in module.snapshot(path)['运行状态']
    assert not path.exists()


def test_resumed_run_does_not_inherit_previous_run_end(tmp_path):
    events=[{'type':'run_start','ts':1,'data':{}},{'type':'run_end','ts':2,'data':{'stop_reason':'max_turns'}},{'type':'run_start','ts':3,'data':{}},{'type':'text_delta','ts':4,'data':{'text':'not displayed'}}]
    (tmp_path/'run-events.jsonl').write_text('\n'.join(json.dumps(e) for e in events)+'\n',encoding='utf8')
    s=module.snapshot(tmp_path)
    assert s['运行状态']=='模型响应接收中'
    assert '尚未确定' in s['阶段']['PDF解析']
