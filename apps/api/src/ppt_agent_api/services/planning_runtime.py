"""Explicit planning/review/revision assembly using the same product configuration.

The caller chooses a phase. The Harness model selects evidence and save tools;
this is not an automatic whole-PPT lifecycle scheduler.
"""
from dataclasses import replace
from pathlib import Path
import json

from agent_harness.runtime import Harness, HarnessConfig
from ppt_agent_domain.presentation import PresentationConfig, make_presentation_tools
from ppt_agent_domain.presentation.planning import PlanningService, READ_TOOLS, PROMPTS
from ppt_agent_domain.presentation.planning_config import PlanningConfig
from ppt_agent_domain.presentation.planning_observer import ObservedPlanningModel
from ppt_agent_domain.pdf_assets.storage import write_json, read_json, sha256_file


def build_ppt_planning_harness(*, workspace, manifest_path, phase, user_task, project_root=None,
                               config=None, model_factory=None, seed_candidate=None):
    config=config or PlanningConfig(); root=Path(workspace).resolve()
    project=Path(project_root).resolve() if project_root else Path(__file__).resolve().parents[5]
    service=PlanningService(root,manifest_path,user_task=user_task,reviewer_model=config.spec('review'))
    packet=service.input(phase,seed_candidate=seed_candidate)
    observed=ObservedPlanningModel(config,phase,root,factory=model_factory)
    native=make_presentation_tools(PresentationConfig(workspace=root/phase/'workspace/ppt_tasks'))
    evidence_path=root/phase/'evidence_access.json'
    evidence_log=read_json(evidence_path) if evidence_path.is_file() else []
    selected=[]
    for t in native:
        if t.name not in READ_TOOLS:continue
        def read_tool(_tool=t, **args):
            value=_tool.func(**args)
            evidence_log.append(dict(tool=_tool.name,args=args))
            write_json(root/phase/'evidence_access.json',evidence_log)
            return value
        # **kwargs is internal; the explicit Pydantic public schema is retained.
        selected.append(replace(t,func=read_tool))
    # Reuse the existing deterministic source-page reader. Only the phase model
    # receives the actual image; no separate PDF review/image-model call occurs.
    from ppt_agent_domain.pdf_assets import PdfAssetConfig, make_pdf_asset_tools
    page_tool=next(t for t in make_pdf_asset_tools(PdfAssetConfig(workspace=root/phase/'source-pages')) if t.name=='view_pdf_page')
    def source_page(pdf_path,page_number,output_dir='',describe=False):
        if describe or output_dir:raise ValueError('Use default output and describe=false; no internal model')
        if page_number not in observed.source_images and len(observed.source_images)>=2:
            raise ValueError('This bounded phase permits at most two source-page images')
        value=page_tool.func(pdf_path,page_number,output_dir='',describe=False)
        observed.source_images[page_number]=value['image_path']
        evidence_log.append(dict(tool='view_pdf_page',page_number=page_number,image_path=value['image_path']))
        write_json(root/phase/'evidence_access.json',evidence_log)
        return value
    selected.append(replace(page_tool,func=source_page))
    saves=service.tools(phase)
    def evidence_obtained():
        return any(e['tool'] in {'get_evidence','get_evidence_bundle','get_asset'} for e in evidence_log)
    for t in saves:
        original=t.func
        def save_tool(_function=original, **args):
            if not evidence_obtained():raise ValueError('Read current structured JSON evidence before saving this phase')
            return _function(**args)
        selected.append(replace(t,func=save_tool))
    harness=Harness(HarnessConfig(model=observed,workspace=str(root/phase/'workspace'),
        system_prompt=PROMPTS[phase],skills_dir=str(project/'skills'),extra_tools=selected,
        permission_mode='accept_edits',enable_bash=False,session_root=str(root/phase/'sessions'),
        serial_tools=tuple(t.name for t in saves),tool_risk={t.name:('write' if t.name in {s.name for s in saves} else 'read') for t in selected},
        max_turns=config.max_calls_per_phase,max_context_tokens=config.max_context_tokens))
    harness.tools=[t for t in harness.tools if t.name in READ_TOOLS|{'read_file','read_skill','view_pdf_page'}|{t.name for t in saves}]
    gate=harness.gate
    def scoped(call):
        if call.name in READ_TOOLS and Path(call.args.get('manifest_path','')).resolve()!=service.manifest_path:
            return 'Only the current bound Manifest may be queried'
        if call.name=='view_pdf_page' and Path(call.args.get('pdf_path','')).resolve()!=Path(service.manifest['source']['pdf_path']).resolve():
            return 'Only the bound source PDF may be viewed'
        return gate(call)
    harness.gate=scoped
    write_json(root/phase/'phase_input.json',json.loads(packet))
    write_json(root/phase/'binding.json',dict(phase=phase,model_spec=config.spec(phase),parameters=config.parameters(phase),
        manifest_path=str(service.manifest_path),manifest_sha256=sha256_file(service.manifest_path),
        input_policy='Full Markdown once in initial user message plus JSON index; subsequent turns retain normal session history.',
        allowed_tools=[t.name for t in harness.tools]))
    return harness, packet
