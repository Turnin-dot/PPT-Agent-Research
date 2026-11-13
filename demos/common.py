from __future__ import annotations
from dataclasses import asdict
from pathlib import Path
import json, time
from dotenv import load_dotenv
from agent_harness.core import FakeModel
from ppt_agent_api.services.agent_runtime import build_ppt_agent_harness
from ppt_agent_domain.presentation import PresentationConfig, make_presentation_tools
from ppt_agent_domain.pdf_assets import PdfAssetConfig

ROOT = Path(__file__).resolve().parents[1]

def dump(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str), encoding='utf8')

def config(workspace):
    return PresentationConfig(workspace=Path(workspace) / 'tasks')

def tools_for(cfg):
    return {tool.name: tool for tool in make_presentation_tools(cfg)}

def call(tools, name, **args):
    return tools[name].invoke_result(args).value

def harness(workspace, model, cfg, max_turns=24):
    h = build_ppt_agent_harness(workspace=workspace, project_root=ROOT, model=model,
        presentation_config=cfg, pdf_asset_config=PdfAssetConfig(workspace=Path(workspace)/'pdf'),
        enable_bash=False, max_turns=max_turns, tool_profile='full')
    return h

def run_logged(h, prompt, workspace, session_id=None, label='run'):
    started=time.perf_counter(); events=[]; end={}; error=None
    workspace=Path(workspace)
    try:
        with (workspace/(label+'-events.jsonl')).open('x',encoding='utf8') as log:
            for event in h.run(prompt,session_id=session_id):
                record=asdict(event); events.append(record)
                log.write(json.dumps(record,ensure_ascii=False,default=str)+'\n'); log.flush()
                if event.type=='run_end': end=event.data
                if event.type=='error': error=event.data
                if event.type in ('tool_start','run_end','error'):
                    print(event.type, json.dumps(event.data,ensure_ascii=False,default=str)[:220],flush=True)
    except Exception as exc:
        error={'type':type(exc).__name__,'message':str(exc)}
    finally:
        summary={'wall_seconds':time.perf_counter()-started,
            'session_id':getattr(getattr(h,'last_session',None),'id',None),
            'run_end':end,'error':error,
            'billing':'not computed; no current provider price assumed',
            'sdk_hidden_retries':'unknown unless SDK retries explicitly disabled'}
        dump(workspace/(label+'-summary.json'),summary)
        h.close()
    return events, summary
