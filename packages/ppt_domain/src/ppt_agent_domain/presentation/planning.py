"""Persistent planning tools and phase inputs, without a global PPT workflow."""
from pathlib import Path
from copy import deepcopy
import json
import uuid

from agent_harness.core.tools import tool
from .planning_schemas import (PlanningSubmission, UnderstandingSubmission, PlanSubmission,
    UnderstandingResult, SubmissionResult, check_references)
from .planning_revision import RevisionPatch, RevisionResult, apply_revision, content_hash
from .planning_review import ReviewSubmission, PlanningReviewReport, ReviewBinding, build_review_report
from .planning_quality import check_plan_quality
from .markdown import reading_packet
from ..pdf_assets.storage import read_json, write_json, load_manifest, sha256_file

FIGURE_PLANNING_POLICY = '''科学图表按讲解目的选择：真实网络结构优先原图或可溯源子图；运算原理可用有来源的自绘示意，不冒充论文原图。
原图不必铺满整页；同一图可为不同目的复用，不把避免重复变成禁用原图。不能仅凭像素长边或未渲染的规划判定不可读，
不得自行添加统一分辨率门槛并据此强制自绘替代。疑似不清晰先查原页与资产；尚需重裁/核验须明确记录未完成前置工作，
不能把计划保存或修订响应deferred当作资产已准备。修订须核实审核建议，不机械采纳，也不把所有方法页统一改成原图。'''

COMMON = '''你是论文PPT规划Agent。工具与Skill指导按需取证，不是固定全局PPT工作流。
本轮仅理解/规划/独立审核/局部修订，不解析PDF、不做PDF模型审核、不制作HTML。
规划阶段首条输入提供完整Markdown及JSON资产索引；修订阶段按需通过工具读取原文。JSON/Manifest是结构化主证据。
Markdown与JSON同源时可能共享OCR错误；公式/表格存在VLM替换，必要时用get_evidence_bundle读取当前机器表示。
不要每轮重复全文或反复读取已提供的Markdown。数字带数据集/条件/指标；图像路径不等于视觉输入。
先读paper-planning Skill；保持source_notes和结构化补充的未核实状态。证据足够时及时保存，不空转。
截图通过不代表公式/表格HTML已正确；原文冲突如实限定，不自行裁决作者意图。
''' + FIGURE_PLANNING_POLICY
PROMPTS = {
    'planning': COMMON+'''\n通读全文后保存论文理解(save_paper_understanding)，再保存全局页面计划(submit_presentation_plan)。
若提供seed_candidate，它只是历史草稿，不是标准答案；须依据当前原文重新检查。中文短要点，细节放speaker_notes_outline。
至少读取一次当前JSON证据再提交。保持计划范围精简但覆盖研究问题、方法、实验、消融、局限。''',
    'review': COMMON+'''\n你是独立审核者，只审核当前候选，不继承规划会话。必须主动调用JSON证据工具核查事实，不能只根据候选自洽判定。
核查公式、配置、数据条件、图表关联、关键覆盖与叙事。给出具体页码、可核查原文和可执行建议。
静态密度通常为minor；未渲染不能声称视觉不合格。审核建议不等于Ground Truth。用submit_planning_review保存一次报告。''',
    'revision': COMMON+'''\n只对当前真实审核意见提交一轮局部补丁(submit_plan_revision)，保留正确内容，不整套重写。
所有意见包括minor都要在issue_responses记录addressed/deferred/disputed及理由。无问题时可提交空补丁。
base_sha256必须匹配；path用0-based JSON Pointer定位现有字段，value是实际JSON。先读取相关JSON原文核实建议。
本轮没有第二次正式修订或第二轮模型审核。'''
}
READ_TOOLS = {'get_document_overview','query_assets','get_evidence','get_evidence_bundle','get_asset','get_paper_context','get_paper_markdown'}


def materialize_visual_refs(plan, manifest):
    """Resolve model-selected IDs to current identity, without changing claims.

    asset_ids is itself an explicit asset request. Missing duplicate identity
    fields can be resolved deterministically; stale/existing refs still fail.
    """
    result=deepcopy(plan);assets={a['asset_id']:a for a in manifest['assets']};added=[]
    for slide in result['slides']:
        existing={r['object_id'] for r in slide['evidence_refs']}
        for aid in slide['asset_ids']:
            if aid not in existing and aid in assets and assets[aid]['type'] in {'image','table'}:
                a=assets[aid];ref=dict(object_id=aid,version=a.get('version',1),source_page=a['source_page'])
                slide['evidence_refs'].append(ref);existing.add(aid)
                added.append(dict(slide_index=slide['slide_index'],reference=ref))
    return result,added


class PlanningService:
    def __init__(self, root, manifest_path, *, user_task, reviewer_model):
        self.root=Path(root).resolve(); self.root.mkdir(parents=True,exist_ok=True)
        self.manifest_path,self.manifest=load_manifest(manifest_path)
        self.manifest_hash=sha256_file(self.manifest_path)
        self.user_task=user_task; self.reviewer_model=reviewer_model

    def _fresh(self):
        if sha256_file(self.manifest_path)!=self.manifest_hash:
            raise ValueError('Manifest changed; preserve checkpoints and rebuild phase inputs')

    def base(self):
        return {k:read_json(self.root/'planning'/(k+'.json')) for k in ('paper_understanding','presentation_plan')}

    def input(self, phase, *, seed_candidate=None):
        self._fresh()
        if phase=='revision':
            material=dict(mode='on_demand_revision',manifest_path=str(self.manifest_path),
                manifest_revision=self.manifest['revision'],source=self.manifest['source'],
                page_index_path=(self.manifest.get('reading_material') or {}).get('page_index_path',''),
                source_notes=self.manifest.get('source_ambiguities',[]),
                policy='Use get_paper_markdown(pdf_pages=[...]) or bounded offsets and current JSON evidence tools for specific disputed claims.')
        else:material=reading_packet(str(self.manifest_path))
        packet=dict(user_task=self.user_task,phase=phase,source_material=material)
        if phase=='planning' and (self.root/'planning/paper_understanding.json').is_file():
            packet['checkpoint']=dict(paper_understanding=read_json(self.root/'planning/paper_understanding.json'),
                action='Understanding already saved; continue to plan submission without overwriting it.')
        if phase!='planning':
            packet.update(candidate=self.base(),base_sha256=content_hash(self.base()))
        elif seed_candidate is not None:packet['seed_candidate']=seed_candidate
        if phase=='revision':packet['feedback']=read_json(self.root/'review/planning_review.json')
        return json.dumps(packet,ensure_ascii=False,separators=(',',':'))

    def _check(self, value):
        checked=check_references(PlanningSubmission.model_validate(value),self.manifest)
        if not checked['valid']:raise ValueError('Invalid references: '+str(checked['invalid_references']))
        return checked

    def _bridge(self, directory, value):
        from .tools import make_presentation_tools
        from .config import PresentationConfig
        native={t.name:t for t in make_presentation_tools(PresentationConfig(workspace=directory/'ppt_tasks'))}
        plan=value['presentation_plan']; tid='paper-planning'
        native['save_brief'].invoke_result(dict(task_id=tid,user_goal=self.user_task,audience=plan['target_audience'],
            target_slide_count=len(plan['slides']),source_manifest_paths=[str(self.manifest_path)]))
        native['save_outline'].invoke_result(dict(task_id=tid,title=value['paper_understanding']['title'],
            narrative=' → '.join(plan['narrative_structure']),slides=[dict(slide_id=f"slide-{s['slide_index']:02d}",title=s['slide_title'],purpose=s['slide_purpose']) for s in plan['slides']]))
        for s in plan['slides']:
            refs=[dict(object_id=r['object_id'],version=r['version'],manifest_path=str(self.manifest_path)) for r in s['evidence_refs']]
            native['save_slide_plan'].invoke_result(dict(task_id=tid,slide_id=f"slide-{s['slide_index']:02d}",goal=s['slide_purpose'],
                content_markdown='## '+s['key_message']+'\n\n'+'\n'.join('- '+p for p in s['main_points']),layout_intent=s['layout_intent'],
                asset_refs=[r for r in refs if r['object_id'] in s['asset_ids']],evidence_refs=refs))
        return str(directory/'ppt_tasks'/tid/'task.json')

    def tools(self, phase):
        dest=self.root/phase
        @tool(name='save_paper_understanding',args_schema=UnderstandingSubmission,result_schema=UnderstandingResult)
        def understanding(paper_understanding:dict):
            self._fresh(); path=dest/'paper_understanding.json'
            if path.exists():raise FileExistsError('Understanding already checkpointed; do not overwrite')
            # Validate all references even before the plan is available.
            from ..pdf_assets.provenance import source_mapping
            physical=source_mapping(self.manifest)[0];assets={a['asset_id']:a for a in self.manifest['assets']}
            def visit(v):
                if isinstance(v,dict):
                    if {'object_id','version','source_page'}<=v.keys():
                        a=assets.get(v['object_id'])
                        if not a or v['version']!=a.get('version',1) or v['source_page'] not in physical.get(v['object_id'],{}).get('source_pages',[a['source_page']]):raise ValueError('Invalid understanding reference')
                    for child in v.values():visit(child)
                elif isinstance(v,list):
                    for child in v:visit(child)
            visit(paper_understanding);write_json(path,paper_understanding)
            return dict(execution_status='succeeded',paper_understanding_path=str(path),next_action='submit_presentation_plan')

        @tool(name='submit_presentation_plan',args_schema=PlanSubmission,result_schema=SubmissionResult)
        def plan(presentation_plan:dict):
            self._fresh(); path=dest/'presentation_plan.json'
            if path.exists():raise FileExistsError('Initial plan already saved')
            write_json(dest/'model_presentation_plan.json',presentation_plan)
            presentation_plan,added=materialize_visual_refs(presentation_plan,self.manifest)
            value=dict(paper_understanding=read_json(dest/'paper_understanding.json'),presentation_plan=presentation_plan)
            checked=self._check(value)
            # Save before downstream bridging, so a later tool error cannot lose the plan.
            write_json(path,presentation_plan);write_json(dest/'reference_validation.json',checked)
            write_json(dest/'reference_materialization.json',dict(added=added,policy='Only resolve explicitly model-selected asset IDs; no changes to scientific content, layout, narrative or existing refs.'))
            task_path=self._bridge(dest,value)
            write_json(dest/'programmatic_checks.json',check_plan_quality(presentation_plan,self.manifest,manifest_path=str(self.manifest_path)))
            return dict(execution_status='succeeded',planning_complete=True,slide_count=len(presentation_plan['slides']),
                paper_understanding_path=str(dest/'paper_understanding.json'),presentation_plan_path=str(path),
                task_path=task_path,downstream_plan_count=len(presentation_plan['slides']),reference_validation='pass')

        @tool(name='submit_planning_review',args_schema=ReviewSubmission,result_schema=PlanningReviewReport)
        def review(summary:str,reviewed_topics:list[str],issues:list[dict]):
            self._fresh(); path=dest/'planning_review.json'
            if path.exists():raise FileExistsError('One review only')
            base=self.base()
            bound=ReviewBinding(planning_version='v01',planning_sha256=content_hash(base),
                plan_file_sha256=sha256_file(self.root/'planning/presentation_plan.json'),manifest_revision=self.manifest['revision'],
                manifest_sha256=self.manifest_hash,source_pdf_sha256=self.manifest['source']['sha256'])
            result=build_review_report(ReviewSubmission(summary=summary,reviewed_topics=reviewed_topics,issues=issues),
                binding=bound,report_id=uuid.uuid4().hex,reviewer_model=self.reviewer_model,manifest=self.manifest,
                slide_count=len(base['presentation_plan']['slides'])).model_dump(mode='json')
            write_json(path,result);return result

        @tool(name='submit_plan_revision',args_schema=RevisionPatch,result_schema=RevisionResult)
        def revision(base_sha256:str,edits:list[dict],insertions:list[dict],issue_responses:list[dict]):
            self._fresh();report=read_json(self.root/'review/planning_review.json');base=self.base()
            if report['binding']['planning_sha256']!=content_hash(base):raise ValueError('Review binding is stale')
            ids={i['issue_id'] for i in report['issues']}
            if {r['issue_id'] for r in issue_responses}!=ids or len(issue_responses)!=len(ids):raise ValueError('Respond exactly once to every review issue')
            patch=RevisionPatch(base_sha256=base_sha256,edits=edits,insertions=insertions,issue_responses=issue_responses)
            value,delta=apply_revision(base,patch,valid_issue_ids=ids)
            value['presentation_plan'],added=materialize_visual_refs(value['presentation_plan'],self.manifest)
            if added:
                delta.update(model_patch_result_sha256=delta['result_sha256'],materialized_visual_refs=added,
                             result_sha256=content_hash(value))
            checked=self._check(value)
            final=dest/'v02'
            if (final/'presentation_plan.json').exists():raise FileExistsError('One revision only; preserve existing v02')
            for key,data in value.items():write_json(final/(key+'.json'),data)
            write_json(final/'patch.json',patch.model_dump(mode='json'));write_json(final/'change_manifest.json',delta)
            write_json(final/'reference_validation.json',checked)
            quality=check_plan_quality(value['presentation_plan'],self.manifest,manifest_path=str(self.manifest_path))
            write_json(final/'quality_checks.json',quality);self._bridge(final,value)
            return dict(revision_saved=True,revision_id='v02',slide_count=len(value['presentation_plan']['slides']),
                changed_original_slides=delta['changed_original_slides'],inserted_slide_count=delta['inserted_slide_count'],
                quality_report_path=str(final/'quality_checks.json'),content_pass=None,summary='One local revision saved; no post-revision scientific acceptance claimed.')
        return {'planning':[understanding,plan],'review':[review],'revision':[revision]}[phase]
