"""Checkpointed review of an existing paper plan, one slide at a time."""
from __future__ import annotations

from pathlib import Path
import json
import uuid

from agent_harness.core.tools import tool
from pydantic import BaseModel
from ..pdf_assets.storage import load_manifest, read_json, write_json, sha256_file
from .assets import asset_view
from .planning_review import ReviewSubmission, ReviewBinding, build_review_report
from .planning_revision import content_hash


class SavedReview(BaseModel):
    execution_status: str = 'succeeded'
    page_id: int | None = None
    path: str
    review_verdict: str


class ReviewWorkflow:
    def __init__(self,root,manifest_path,planning_root,*,user_task,reviewer_model,batch_size=2):
        self.root=Path(root).resolve();self.root.mkdir(parents=True,exist_ok=True)
        self.manifest_path,self.manifest=load_manifest(manifest_path)
        self.planning_root=Path(planning_root).resolve()
        self.base={k:read_json(self.planning_root/f'{k}.json') for k in ('paper_understanding','presentation_plan')}
        self.binding=ReviewBinding(planning_version='v01',planning_sha256=content_hash(self.base),
            plan_file_sha256=sha256_file(self.planning_root/'presentation_plan.json'),
            manifest_revision=self.manifest['revision'],manifest_sha256=sha256_file(self.manifest_path),
            source_pdf_sha256=self.manifest['source']['sha256'])
        self.version_root=self.root/'planning_review'/self.binding.planning_sha256[:12]
        self.user_task=user_task;self.reviewer_model=reviewer_model
        if batch_size<1 or batch_size>3:raise ValueError('batch_size must be 1..3')
        self.batch_size=batch_size
        slides=self.base['presentation_plan']['slides']
        self.slides={s['slide_index']:s for s in slides}
        if len(self.slides)!=len(slides):raise ValueError('Duplicate slide indices')

    def _fresh(self):
        current={k:read_json(self.planning_root/f'{k}.json') for k in self.base}
        if (sha256_file(self.manifest_path)!=self.binding.manifest_sha256 or
            sha256_file(self.planning_root/'presentation_plan.json')!=self.binding.plan_file_sha256 or
            content_hash(current)!=self.binding.planning_sha256):
            raise ValueError('Review input changed; start a new versioned review run')

    def page_path(self,page_id):return self.version_root/f'page_{page_id:02d}.json'

    def completed(self,page_id):
        path=self.page_path(page_id)
        if not path.is_file():return False
        value=read_json(path)
        return value.get('status')=='completed' and value.get('binding')==self.binding.model_dump(mode='json')

    def overview(self):
        p=self.base['paper_understanding'];plan=self.base['presentation_plan']
        return dict(title=p.get('title'),research_problem=p.get('research_problem'),method_overview=p.get('method_overview'),
            target_audience=plan.get('target_audience'),narrative_structure=plan.get('narrative_structure'),
            slides=[dict(slide_index=s['slide_index'],title=s['slide_title'],purpose=s['slide_purpose'],key_message=s['key_message']) for s in plan['slides']])

    def page_input(self,page_id):
        self._fresh();slide=self.slides[page_id]
        ids=set(slide['asset_ids'])|{r['object_id'] for r in slide['evidence_refs']}
        assets={a['asset_id']:a for a in self.manifest['assets']}
        index=[]
        for aid in sorted(ids):
            if aid not in assets:continue
            view=asset_view(assets[aid],self.manifest,str(self.manifest_path))
            keys=('asset_id','type','version','source_page','source_pages','figure_number','captions','pixel_width','pixel_height','aspect_ratio','review_status','structured_source')
            index.append({k:view[k] for k in keys if view.get(k) not in (None,'',[],{})})
        return json.dumps(dict(phase='page_review',user_task=self.user_task,ppt_page=page_id,batch_size=self.batch_size,
            overview=self.overview(),current_slide=slide,related_asset_index=index,
            manifest_path=str(self.manifest_path),binding=self.binding.model_dump(mode='json'),
            source_policy='Read structured evidence for important facts. PDF page Markdown is available through get_paper_markdown(pdf_pages=[...]). Full Markdown and Manifest are not injected.'),ensure_ascii=False,separators=(',',':'))

    def global_input(self):
        self._fresh()
        if not all(self.completed(p) for p in self.slides):raise ValueError('All page reviews must be saved before global review')
        pages=[read_json(self.page_path(p)) for p in sorted(self.slides)]
        brief=[{k:v for k,v in x.items() if k in ('page_id','summary','review_verdict','issues','checked_evidence','markdown_consulted')} for x in pages]
        return json.dumps(dict(phase='global_review',user_task=self.user_task,overview=self.overview(),page_reviews=brief,
            manifest_path=str(self.manifest_path),binding=self.binding.model_dump(mode='json')),
            ensure_ascii=False,separators=(',',':'))

    def save_tool(self,page_id,evidence_log):
        name='submit_page_review' if page_id is not None else 'submit_global_review'
        @tool(name=name,args_schema=ReviewSubmission,result_schema=SavedReview)
        def save(summary:str,reviewed_topics:list[str],issues:list[dict]):
            self._fresh()
            if page_id is None and not all(self.completed(p) for p in self.slides):
                raise ValueError('Cannot save global review before all pages are complete')
            path=self.page_path(page_id) if page_id is not None else self.version_root/'global_review.json'
            if path.is_file():
                prior=read_json(path)
                if prior['binding']!=self.binding.model_dump(mode='json'):raise ValueError('Stale review checkpoint')
                return SavedReview(page_id=page_id,path=str(path),review_verdict=prior['review_verdict']).model_dump(mode='json')
            submission=ReviewSubmission(summary=summary,reviewed_topics=reviewed_topics,issues=issues)
            report=build_review_report(submission,binding=self.binding,report_id=uuid.uuid4().hex,
                reviewer_model=self.reviewer_model,manifest=self.manifest,slide_count=len(self.slides))
            if page_id is not None and any(i.affected_slides and page_id not in i.affected_slides for i in report.issues):
                raise ValueError('Page finding must reference the audited PPT page')
            checked=[dict(tool=e['tool'],args=e.get('args',{})) for e in evidence_log if e['tool'] in
                     {'get_evidence','get_evidence_bundle','get_asset','get_paper_markdown','view_pdf_page'}]
            value=dict(status='completed',page_id=page_id,binding=self.binding.model_dump(mode='json'),
                summary=summary,reviewed_topics=reviewed_topics,issues=[i.model_dump(mode='json') for i in report.issues],
                review_verdict=report.review_verdict,checked_evidence=checked,
                markdown_consulted=any(e['tool']=='get_paper_markdown' for e in checked),reviewer_model=self.reviewer_model)
            write_json(path,value)
            return SavedReview(page_id=page_id,path=str(path),review_verdict=report.review_verdict).model_dump(mode='json')
        return save

    def mark_incomplete(self,page_id,reason):
        if not self.completed(page_id):
            write_json(self.version_root/f'page_{page_id:02d}.incomplete.json',dict(status='incomplete',page_id=page_id,
                binding=self.binding.model_dump(mode='json'),reason=str(reason)))

    def finalize(self,revision_workspace):
        self._fresh()
        if not all(self.completed(p) for p in self.slides):raise ValueError('Page review incomplete')
        global_path=self.version_root/'global_review.json'
        if not global_path.is_file():raise ValueError('Global review incomplete')
        pages=[read_json(self.page_path(p)) for p in sorted(self.slides)]
        global_review=read_json(global_path)
        issues=[]
        for item in pages+[global_review]:
            prefix=f"P{item['page_id']:02d}" if item['page_id'] is not None else 'G'
            for issue in item['issues']:
                issues.append(dict(issue,issue_id=prefix+'-'+issue['issue_id']))
        submission=ReviewSubmission(summary=global_review['summary'],reviewed_topics=global_review['reviewed_topics'],issues=issues)
        report=build_review_report(submission,binding=self.binding,report_id=uuid.uuid4().hex,
            reviewer_model=self.reviewer_model,manifest=self.manifest,slide_count=len(self.slides))
        summary=dict(status='completed',binding=self.binding.model_dump(mode='json'),reviewed_pages=len(pages),
            total_pages=len(self.slides),page_review_paths=[str(self.page_path(p)) for p in sorted(self.slides)],
            global_review_path=str(global_path),review_verdict=report.review_verdict,issues=report.model_dump(mode='json')['issues'])
        summary_path=self.version_root/'review_summary.json';write_json(summary_path,summary)
        target=Path(revision_workspace).resolve();(target/'planning').mkdir(parents=True,exist_ok=True)
        for key,value in self.base.items():write_json(target/'planning'/f'{key}.json',value)
        write_json(target/'review'/'planning_review.json',report.model_dump(mode='json'))
        return dict(summary_path=str(summary_path),planning_review_path=str(target/'review'/'planning_review.json'))
