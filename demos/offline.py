"""Scripted FakeModel simulation. Real local files/browser; NO genuine model judgment."""
import argparse, json
from pathlib import Path
from agent_harness.core import FakeModel, ToolCall
from .common import config, harness, run_logged, dump, call, tools_for
from .sample_data import prepare, TASK, SLIDE

def tc(tool_name,**args): return [ToolCall(tool_name,args)]

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',default='outputs/offline');args=parser.parse_args()
    w=Path(args.output).resolve();cfg=config(w);prepare(w,cfg)
    # Deliberately authored fixture. FakeModel only replays tool requests; it does not design this page.
    html='''<!doctype html><html><head><meta charset="utf-8"><style>
    *{box-sizing:border-box}body{margin:0;background:#f6f4ef;font-family:Arial}
    main{width:1600px;height:900px;padding:65px;color:#17324d}
    h1{font-size:56px;margin:0 0 30px}p{font-size:32px;line-height:1.5}
    img{width:1400px;height:420px;object-fit:contain}</style></head><body><main>
    <h1 id="title" data-pptx="text">SignalFusion — SCRIPTED SIMULATION</h1>
    <img id="figure" data-pptx="image" src="input/diagram.png">
    <p id="claim" data-pptx="text">Synthetic MAE: baseline 5.0 → fusion 4.0 / 100 fictional samples.</p>
    <p id="note" data-pptx="text">Self-authored test data. Not a real paper or AI design result.</p>
    </main></body></html>'''
    manifest=str((w/'input/manifest.json').resolve())
    ref=lambda obj:dict(object_id=obj,version=1,manifest_path=manifest)
    binding=dict(task_id=TASK,slide_id=SLIDE,html_path=str(w/'page.html'),expected_plan_version=1,
        elements=[dict(element_id='title',role='title',generated_decoration=True),
                  dict(element_id='figure',role='figure',asset_refs=[ref('image-p0001-001')]),
                  dict(element_id='claim',role='body',evidence_refs=[ref('text-p0001-001')]),
                  dict(element_id='note',role='notice',generated_decoration=True)],check_layout=True)
    script=[tc('read_skill',name='ppt-production'),tc('write_file',path='page.html',content=html),
            tc('save_slide_binding',**binding),tc('get_task_state',task_id=TASK,view='progress'),'Simulation checkpoint saved; review has NOT passed.']
    h=harness(w,FakeModel(script),cfg);_,first=run_logged(h,'Execute the scripted offline fixture.',w,label='initial')
    if first['error']:raise RuntimeError(first['error'])
    # Recreate Harness and replay persisted session; demonstrate a recoverable tool failure.
    wrong=dict(binding,expected_plan_version=999)
    script=[tc('save_slide_binding',**wrong),tc('get_task_state',task_id=TASK,view='progress'),
            tc('write_file',path='page.html',content=html.replace('SCRIPTED SIMULATION','SCRIPTED SIMULATION V2')),
            tc('save_slide_binding',**binding),tc('export_editable_pptx',task_id=TASK,slide_ids=[SLIDE]),
            'Simulation ended. Invalid plan version was rejected. Export remains blocked without independent reviews.']
    h=harness(w,FakeModel(script),cfg);events,second=run_logged(h,'Resume the same session and demonstrate guards.',w,session_id=first['session_id'],label='resumed')
    state=call(tools_for(cfg),'get_task_state',task_id=TASK,view='progress')
    errors=[e for e in events if e['type']=='tool_result' and e['data'].get('message',{}).get('is_error')]
    rendered=list((w/'tasks'/TASK/'slides'/SLIDE/'renders').glob('html-v*/preview.png'))
    layout_reports=list((w/'tasks'/TASK/'slides'/SLIDE/'layout_reports').rglob('*.json'))
    render_ok=len(rendered)>=2 and all(x.stat().st_size>0 for x in rendered)
    result=dict(rendered_preview_count=len(rendered),render_ok=render_ok,mode='FakeModel scripted simulation',real_model_calls=0,api_cost=0,
        token_notice='FakeModel character estimates are not API token usage',
        session_restored=first['session_id']==second['session_id'],observed_tool_errors=len(errors),
        initial=first,resumed=second,progress=state,
        status='mechanism_demonstrated_not_quality_approved',pptx_delivered=False)
    dump(w/'result.json',result)
    if second['error'] or len(errors)!=2 or not render_ok:raise RuntimeError('Guard demonstration did not complete; inspect logs')
    print('OFFLINE SIMULATION COMPLETE; no quality approval or formal PPTX delivery claimed.')

if __name__=='__main__':main()
