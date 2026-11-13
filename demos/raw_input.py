"""Raw-PDF input adapter: copy only source bytes, never fabricate parsed assets or plans."""
from pathlib import Path
import json, shutil
from .common import dump
from ppt_agent_domain.presentation.storage import sha256_file

def prepare_raw_pdf(workspace, pdf_path, resume=False):
    workspace=Path(workspace);workspace.mkdir(parents=True,exist_ok=True)
    marker=workspace/'prepared.json'
    if marker.exists():
        if not resume:raise FileExistsError('Prepared run exists; choose a new output or --resume')
        value=json.loads(marker.read_text(encoding='utf8'))
        if value.get('mode')!='raw_pdf':raise ValueError('Cannot resume a prepared-assets task as raw PDF')
        if sha256_file(Path(value['source_pdf']))!=value['source_sha256']:raise ValueError('Source PDF changed')
        if sha256_file(Path(pdf_path).resolve())!=value['source_sha256']:raise ValueError('Resume input differs')
        return value
    if resume:raise FileNotFoundError('Raw PDF preparation record missing')
    source=Path(pdf_path).expanduser().resolve()
    if not source.is_file():raise FileNotFoundError(source)
    if source.suffix.lower()!='.pdf':raise ValueError('Expected a PDF source')
    target=workspace/'input/source.pdf';target.parent.mkdir(parents=True,exist_ok=True)
    if target.exists():raise FileExistsError(target)
    shutil.copyfile(source,target)
    value=dict(mode='raw_pdf',task_id='sample',slide_id='slide-01',source_pdf=str(target.resolve()),source_sha256=sha256_file(target),input_scope='Raw PDF bytes only: no Manifest, no parser JSON, no fixed plan, no HTML')
    dump(marker,value);return value

def raw_request(prepared, export=False):
    return json.dumps(dict(input_kind='raw_pdf',task_id=prepared['task_id'],slide_id=prepared['slide_id'],
        pdf_path=prepared['source_pdf'],source_sha256=prepared['source_sha256'],
        user_goal='从这份自制合成示例PDF制作一页中文、16:9研究演示。所有数字均须保留合成/虚构声明，不将其包装为真实论文成果。根据实际解析材料自主理解、规划和制作。',
        scope='使用正式工具实际解析PDF、保存并核验正式资产/来源及Markdown，然后自主生成单页规划和HTML，实际渲染并进行独立内容与视觉审核，必要时定向修订并重新检查。没有预制资产或规划可复用。',
        delivery=('在正式当前版本审核通过后，使用正式可编辑PPTX导出、PowerPoint实际渲染、validate_export与validate_delivery检查并保存最终状态。' if export else '本次止于审核后的HTML，不导出PPTX。'),
        constraints='工具与Skills按需使用，操作顺序由Agent决定。不得修改原始输入/审核状态来制造通过，不绕过来源、版本和导出保护。不因非阻断视觉偏好循环修改；遇到无法恢复的阻断保留状态并如实结束。'),ensure_ascii=False)
