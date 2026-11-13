"""Real Agent single-page entry. Default is no-network preflight, --run explicitly opts into paid APIs."""
import argparse, json, os, time
from pathlib import Path
from dotenv import load_dotenv
from agent_harness.core.models import FakeModel, init_chat_model
from ppt_agent_domain.presentation.config import asset_inspection_model_spec
from .common import ROOT, config, harness, run_logged, call, tools_for, dump
from .sample_data import prepare, TASK, SLIDE

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',default='outputs/single-page')
    p.add_argument('--pdf',help='Optional raw PDF; no prebuilt Manifest or plan is created in this mode')
    p.add_argument('--model',default=None);p.add_argument('--run',action='store_true')
    p.add_argument('--resume',metavar='SESSION_ID');p.add_argument('--export',action='store_true')
    p.add_argument('--max-turns',type=int,default=18)
    args=p.parse_args();load_dotenv(ROOT/'.env',override=False)
    w=Path(args.output).resolve();cfg=config(w)
    spec=args.model or os.environ.get('PPT_AGENT_DEMO_MODEL','qwen:qwen3.8-flash')
    # Building tools/skills with a FakeModel sends NO model request.
    probe=harness(w,FakeModel([]),cfg,max_turns=args.max_turns)
    keys={'qwen':'DASHSCOPE_API_KEY','doubao':'ARK_API_KEY','deepseek':'DEEPSEEK_API_KEY','openai':'OPENAI_API_KEY','anthropic':'ANTHROPIC_API_KEY'}
    specs={'main':spec,'content':os.environ.get('PPT_AGENT_PLANNING_REVIEW_MODEL','qwen:qwen3.8-flash'),
           'visual':os.environ.get('PPT_AGENT_PAGE_REVIEW_MODEL','doubao:doubao-seed-2-1-turbo-260628'),
           'asset_inspection':asset_inspection_model_spec(),
           'optional_pdf_review':'deepseek:deepseek-flash'}
    required={keys[x.split(':')[0]] for role,x in specs.items() if (role!='optional_pdf_review' or bool(args.pdf)) and x.split(':')[0] in keys}
    preflight=dict(mode='preflight_no_api_calls',model_specs=specs,tool_count=len(probe.tools),
        skills=[s.name for s in probe.skills],api_key_present={k:bool(os.environ.get(k)) for k in sorted(required)},
        node=str(cfg.node_executable),node_modules=str(cfg.node_modules),chromium=str(cfg.chromium_executable),
        warning='Model IDs, endpoint access and review outcomes require a separately authorized real run. Keys are never printed.')
    from .environment import inspect_environment
    preflight['environment']=inspect_environment(w)
    probe.close();dump(w/'preflight.json',preflight);print(json.dumps(preflight,ensure_ascii=False,indent=2))
    if not args.run:
        if not preflight['environment']['ready_for_local_tools']:raise SystemExit('Local dependencies incomplete; inspect preflight.json')
        return
    if not preflight['environment']['ready_for_local_tools']:raise SystemExit('Local dependencies incomplete; no model request sent')
    missing=[k for k in required if not os.environ.get(k)]
    if missing:raise SystemExit('Missing configured provider credentials: '+', '.join(missing))
    if args.pdf:
        from .raw_input import prepare_raw_pdf
        prepared=prepare_raw_pdf(w,args.pdf,resume=bool(args.resume))
    else:
        prepared=prepare(w,cfg,resume=bool(args.resume))
    output_arg={'max_completion_tokens':8192} if spec.startswith('qwen:') else {'max_tokens':8192}
    model=init_chat_model(spec,timeout=180,max_retries=3,**output_arg)
    h=harness(w,model,cfg,max_turns=args.max_turns)
    if args.pdf:
        from .raw_input import raw_request
        request=raw_request(prepared,export=args.export)
    else:
        request=('Use the prepared fixed single-page task sample / slide-01. Read ppt-production Skill, task state and necessary evidence. '
          'Source manifest: '+prepared['manifest']+'. Produce HTML autonomously inside the workspace; there is no prewritten real-demo HTML. '
          'Keep the synthetic-data notice visible and do not invent research claims. Choose tools/layout yourself. '
          'Bind current plan/assets, render, independently review content and visuals, revise only justified issues (at most one revision), '
          're-render and re-review changed versions. Never edit task/report JSON or bypass guards. '
          'Do not reparse the source PDF. If blocked, retain artifacts and report the blocker. '
          + ('If all formal gates pass, use the official editable PPTX export and, if PowerPoint is available, render/validate the export. '
             if args.export else 'This task stops at the reviewed single HTML page; do not export PPTX. '))
    dump(w/'agent-request.json',{'request':request,'input_mode':'raw_pdf' if args.pdf else 'prepared_assets'})
    label='real-'+time.strftime('%Y%m%d-%H%M%S')
    events,summary=run_logged(h,request,w,session_id=args.resume,label=label)
    try: state=call(tools_for(cfg),'get_task_state',task_id=TASK,view='progress')
    except Exception as exc:state={'state_read_error':str(exc)}
    page=state.get('page_progress',{}).get(SLIDE,{})
    accepted=page.get('ready_for_export') is True
    export_count=state.get('summary',{}).get('export_count',0)
    export_missing=args.export and not export_count
    status='reviewed_html' if accepted else 'blocked_or_incomplete'
    if args.export and accepted:status='export_requires_final_validation' if export_count else 'html_reviewed_export_incomplete'
    dump(w/(label+'-result.json'),dict(mode='real_model',status=status,export_requested=args.export,summary=summary,formal_state=state,
        note='An end_turn is not acceptance. Inspect independent reports and delivery state. Unknown fees are not zero.'))
    if summary['error']:raise SystemExit('Run failed; logs and partial artifacts retained.')
    if export_missing:raise SystemExit('Requested PPTX export did not complete; partial state retained.')
    if not accepted:raise SystemExit('Current HTML is not formally approved; failure/partial state retained.')
    print('Run ended; inspect formal_state and reports for pass/blocked status. No automatic success claim.')

if __name__=='__main__':main()
