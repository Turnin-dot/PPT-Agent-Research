"""Fixed, self-authored inputs, NOT Agent output or a real scientific paper."""
from pathlib import Path
import json
import fitz
from PIL import Image, ImageDraw, ImageFont
from ppt_agent_domain.presentation.storage import sha256_file
from .common import call, dump, tools_for

TASK='sample'; SLIDE='slide-01'
TEXT = ('Synthetic research fixture: SignalFusion. Two branches encode temporal and spectral '
        'features, concatenate them and predict a scalar. Synthetic demonstration scores: '
        'baseline MAE 5.0 and fusion MAE 4.0 on 100 fictional samples. '
        'These are invented software-test data and must never be presented as paper results.')

def prepare(workspace, cfg, resume=False):
    workspace=Path(workspace); workspace.mkdir(parents=True,exist_ok=True)
    marker=workspace/'prepared.json'
    if marker.exists():
        if not resume: raise FileExistsError('Output already prepared; use a fresh directory or --resume SESSION_ID')
        value=json.loads(marker.read_text(encoding='utf8'))
        for name, expected in value['hashes'].items():
            if sha256_file(workspace/name)!=expected: raise ValueError('Prepared input changed: '+name)
        return value
    if resume: raise FileNotFoundError('Cannot resume without prepared inputs')
    assets=workspace/'input'; assets.mkdir()
    pdf=assets/'source.pdf'
    image=assets/'diagram.png'; im=Image.new('RGB',(1000,350),'#f6f4ef'); draw=ImageDraw.Draw(im)
    for box,label in [((30,45,300,140),'Temporal encoder'),((30,210,300,305),'Spectral encoder'),((430,125,650,225),'Concatenate'),((770,125,970,225),'Predict scalar')]:
        draw.rounded_rectangle(box,radius=12,fill='#17324d');draw.text((box[0]+12,box[1]+35),label,fill='white',font=ImageFont.load_default(size=24))
    for points in [((300,90),(430,170)),((300,255),(430,180)),((650,175),(770,175))]:draw.line(points,fill='#c75b39',width=7)
    im.save(image)
    with fitz.open() as doc:
        page=doc.new_page(width=800,height=500)
        page.insert_text((40,55),'SignalFusion: SELF-AUTHORED SYNTHETIC FIXTURE',fontsize=18)
        page.insert_textbox(fitz.Rect(40,90,760,240),TEXT,fontsize=14)
        page.insert_image(fitz.Rect(40,255,760,490),filename=str(image),keep_proportion=True)
        doc.save(pdf)
    manifest=assets/'manifest.json'
    dump(manifest,dict(schema_version='pdf-assets-prototype/v1',revision=1,
        source=dict(pdf_path=str(pdf.resolve()),sha256=sha256_file(pdf),page_count=1),reviews=[],
        fixture_notice='Self-authored synthetic data, not parsed or independently reviewed',
        assets=[dict(asset_id='text-p0001-001',type='text',version=1,source_page=1,reading_order=1,text=TEXT),
                dict(asset_id='image-p0001-001',type='image',version=1,source_page=1,reading_order=2,
                     path=str(image.resolve()),pixel_width=1000,pixel_height=350,
                     caption='Fig. 1. Synthetic fusion diagram; original demo artwork.')]))
    (assets/'full.md').write_text('# SignalFusion (synthetic)\n\n'+TEXT+'\n\n![Synthetic diagram](diagram.png)\n',encoding='utf8')
    # Self-authored content in the existing parser-compatible schema, NOT actual MinerU output.
    source_records=assets/'content_list.json'
    dump(source_records,[dict(type='text',page_idx=0,text=TEXT),
                         dict(type='image',page_idx=0,img_path='diagram.png',image_caption=['Fig. 1. Self-authored synthetic diagram.'])])
    m=json.loads(manifest.read_text(encoding='utf8'))
    m['mineru']=dict(content_list_path=str(source_records.resolve()),markdown_path=str((assets/'full.md').resolve()),backend='self_authored_fixture_not_parsed')
    from ppt_agent_domain.pdf_assets.page_markdown import build_page_markdown
    m['reading_material']=build_page_markdown(m,assets/'markdown')
    m['reading_material']['markdown_path']=str((assets/'full.md').resolve())
    dump(manifest,m)
    ref=lambda name:dict(object_id=name,version=1,manifest_path=str(manifest.resolve()))
    tools=tools_for(cfg)
    call(tools,'save_brief',task_id=TASK,user_goal='制作一页中文研究原型演示，明确标注合成数据；解释双分支融合并准确展示5.0到4.0的合成MAE。',audience='技术面试',target_slide_count=1,source_manifest_paths=[str(manifest.resolve())])
    call(tools,'save_theme',task_id=TASK,theme=dict(name='Research demo',heading_font='Arial',body_font='Arial'))
    call(tools,'save_slide_plan',task_id=TASK,slide_id=SLIDE,goal='解释合成双分支融合示例',
         content_markdown='明确标注：自制合成示例，非真实论文。展示原始示意图与时间/频率双分支、拼接、标量预测。合成MAE：baseline 5.0，fusion 4.0，100个虚构样本。不得泛化为科研结论。',
         layout_intent='16:9，图为主体，少量大字说明；图像完整展示，布局由Agent决定。',
         asset_refs=[ref('image-p0001-001')],evidence_refs=[ref('text-p0001-001')],theme_version=1)
    value={'task_id':TASK,'slide_id':SLIDE,'manifest':str(manifest.resolve()),
           'input_scope':'fixed self-authored assets and fixed single-page plan, not model planning',
           'hashes':{str(p.relative_to(workspace)):sha256_file(p) for p in [pdf,image,manifest,assets/'full.md',source_records,*sorted((assets/'markdown').rglob('*'))] if p.is_file()}}
    dump(marker,value);return value
