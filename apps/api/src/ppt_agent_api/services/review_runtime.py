"""Bounded Qwen page/global review using the existing Harness and evidence tools."""
from dataclasses import replace
from pathlib import Path
import time

from agent_harness.runtime import Harness, HarnessConfig
from ppt_agent_domain.presentation import PresentationConfig, make_presentation_tools
from ppt_agent_domain.presentation.planning import READ_TOOLS, FIGURE_PLANNING_POLICY
from ppt_agent_domain.presentation.planning_observer import ObservedPlanningModel
from ppt_agent_domain.pdf_assets import PdfAssetConfig, make_pdf_asset_tools
from ppt_agent_domain.pdf_assets.storage import read_json, write_json


PAGE_PROMPT = '''你是独立的 Qwen 论文页面审核者。当前输入只包含一页完整 PPT 规划、全局概览及该页资产索引。
先检查目标、逻辑、资产和引用。重要公式、实验数值、消融、结构和结论必须通过 get_evidence/get_evidence_bundle/get_asset 核查。
结构化证据有疑点时按 PDF 物理页调用 get_paper_markdown(pdf_pages=[页码])；必要时 view_pdf_page。
只审当前 PPT 页，证据中的 source_page 是原 PDF 物理页。未核实的结论写 uncertain，不能宣称通过。
有足够证据后立即调用 submit_page_review 保存。问题使用现有 ReviewIssue 字段，affected_slides 写当前 PPT 页码。不要反复读取相同证据。
''' + FIGURE_PLANNING_POLICY
GLOBAL_PROMPT = '''你是独立的 Qwen 全局审核者。输入有全部 PPT 页的摘要和已保存逐页审核结果。
检查叙事顺序、贡献覆盖、重复、用户需求、图表分配、跨页事实矛盾、数量与密度。
按需查询结构化资产和原 PDF 物理页 Markdown。明确区分未验证与通过。完成后调用 submit_global_review 保存。
''' + FIGURE_PLANNING_POLICY


def build_ppt_review_harness(workflow,*,page_id=None,config=None,model_factory=None,project_root=None):
    from ppt_agent_domain.presentation.planning_config import PlanningConfig
    config=config or PlanningConfig()
    project=Path(project_root).resolve() if project_root else Path(__file__).resolve().parents[5]
    label=f'page_{page_id:02d}' if page_id is not None else 'global'
    root=workflow.root/'review_sessions'/workflow.binding.planning_sha256[:12]/label
    phase=root/'review';evidence_path=phase/'evidence_access.json'
    log=read_json(evidence_path) if evidence_path.is_file() else []
    save_name='submit_page_review' if page_id is not None else 'submit_global_review'
    observed=ObservedPlanningModel(config,'review',root,factory=model_factory,terminal_tool=save_name)
    native=make_presentation_tools(PresentationConfig(workspace=phase/'workspace/ppt_tasks'))
    selected=[]
    for t in native:
        if t.name not in READ_TOOLS-{'get_paper_context'}:continue
        def read_tool(_tool=t,**args):
            start=time.perf_counter();value=_tool.func(**args)
            log.append(dict(tool=_tool.name,args=args,elapsed_seconds=time.perf_counter()-start))
            write_json(evidence_path,log)
            return value
        selected.append(replace(t,func=read_tool))
    page_tool=next(t for t in make_pdf_asset_tools(PdfAssetConfig(workspace=phase/'source-pages')) if t.name=='view_pdf_page')
    def source_page(pdf_path,page_number,output_dir='',describe=False):
        if describe or output_dir:raise ValueError('Use default output and describe=false')
        if page_number not in observed.source_images and len(observed.source_images)>=2:raise ValueError('At most two source page images')
        start=time.perf_counter();value=page_tool.func(pdf_path,page_number,output_dir='',describe=False)
        observed.source_images[page_number]=value['image_path']
        log.append(dict(tool='view_pdf_page',args=dict(pdf_path=pdf_path,page_number=page_number),elapsed_seconds=time.perf_counter()-start))
        write_json(evidence_path,log)
        return value
    selected.append(replace(page_tool,func=source_page))
    save=workflow.save_tool(page_id,log);selected.append(save)
    harness=Harness(HarnessConfig(model=observed,workspace=str(phase/'workspace'),
        system_prompt=PAGE_PROMPT if page_id is not None else GLOBAL_PROMPT,
        skills_dir=str(project/'skills'),extra_tools=selected,permission_mode='accept_edits',enable_bash=False,
        session_root=str(phase/'sessions'),serial_tools=(save_name,),tool_risk={t.name:('write' if t.name==save_name else 'read') for t in selected},
        max_turns=config.max_calls_per_phase,max_context_tokens=config.max_context_tokens))
    harness.tools=[t for t in harness.tools if t.name in {x.name for x in selected}|{'read_file','read_skill'}]
    gate=harness.gate
    def scoped(call):
        if call.name in READ_TOOLS and Path(call.args.get('manifest_path','')).resolve()!=workflow.manifest_path:
            return 'Only the current bound Manifest may be queried'
        if call.name=='get_paper_markdown' and not call.args.get('pdf_pages'):
            return 'Review Markdown access requires specific PDF physical pages'
        if call.name=='view_pdf_page' and Path(call.args.get('pdf_path','')).resolve()!=Path(workflow.manifest['source']['pdf_path']).resolve():
            return 'Only the bound source PDF may be viewed'
        return gate(call)
    harness.gate=scoped
    packet=workflow.page_input(page_id) if page_id is not None else workflow.global_input()
    write_json(phase/'phase_input.json',__import__('json').loads(packet))
    return harness,packet
