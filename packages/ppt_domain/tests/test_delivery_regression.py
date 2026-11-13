from pathlib import Path
import json
import pytest
from ppt_agent_domain.presentation import PresentationService


def test_relative_resource_survives_revision_and_move(tmp_path):
    source = tmp_path / 'source'; source.mkdir()
    (source / 'figure.png').write_bytes(b'original-scientific-image')
    v1 = tmp_path / 'v1'; v2 = tmp_path / 'v2'
    html, files = PresentationService._stage_html_resources('<img src="figure.png">', v1, source)
    revised, files2 = PresentationService._stage_html_resources(html, v2, tmp_path, v1)
    assert Path(files[0]).read_bytes() == Path(files2[0]).read_bytes()
    assert 'resources/' in revised
    with pytest.raises(FileNotFoundError):
        PresentationService._stage_html_resources('<img src="lost.png">', tmp_path / 'v3', source)


def test_export_rejects_stale_unpassed_and_tampered_sources(tmp_path):
    from ppt_agent_domain.presentation.storage import sha256_file
    html = tmp_path / 'slide.html'; html.write_text('<h1>Evidence</h1>')
    preview = tmp_path / 'preview.png'; preview.write_bytes(b'png')
    slide = {'html': {'version': 2, 'path': str(html), 'packaged_sha256': sha256_file(html)},
             'preview': {'html_version': 2, 'path': str(preview)}}
    # Current production contract requires independent content AND visual reports.
    # Keep all approvals in the fixture so this test reaches its intended stale/
    # tamper assertions instead of failing first on a legacy missing dimension.
    for key in ('layout_report','review','content_review','visual_review'):
        p = tmp_path / (key+'.json')
        p.write_text(json.dumps({'html_version':2,'review_verdict':'pass'}))
        slide[key] = {'html_version':2,'path':str(p),'applicability':'current','review_verdict':'pass'}
    PresentationService._check_export_source('slide-01', slide)
    slide['review']['html_version']=1
    with pytest.raises(ValueError): PresentationService._check_export_source('slide-01', slide)
    slide['review']['html_version']=2;slide['review']['review_verdict']='needs_revision'
    with pytest.raises(ValueError): PresentationService._check_export_source('slide-01', slide)
    slide['review']['review_verdict']='pass';html.write_text('modified')
    with pytest.raises(ValueError): PresentationService._check_export_source('slide-01', slide)


def test_browser_export_preserves_text_background_and_rejects_crop(tmp_path):
    from ppt_agent_domain.presentation import PresentationConfig
    from PIL import Image
    import zipfile
    service = PresentationService(PresentationConfig(workspace=tmp_path/'tasks', export_visual_review_enabled=False))
    image=tmp_path/'figure.png';Image.new('RGB',(200,100),'red').save(image)
    html=tmp_path/'page.html'
    html.write_text(f'''<html><body style="margin:0"><div style="width:1600px;height:900px;background:#f6f4ef">
    <div data-pptx="text" style="background:#17324d;color:white;width:600px;font-size:40px">Visible <b>inline</b> label</div>
    <img id="science" src="{image.as_uri()}" style="width:400px;height:200px;object-fit:contain"></div></body></html>''',encoding='utf8')
    request=tmp_path/'request.json';request.write_text(json.dumps({'task_id':'offline','theme':{'width_px':1600,'height_px':900,'background':'#F6F4EF'},'slides':[{'slide_id':'s1','html_version':1,'html_path':str(html)}]}))
    args=['--request',str(request),'--output',str(tmp_path/'out.pptx'),'--map',str(tmp_path/'map.json')]
    if service.config.chromium_executable:args+=['--browser',str(service.config.chromium_executable)]
    service._run_node('html_to_pptx.mjs',args,timeout=90)
    with zipfile.ZipFile(tmp_path/'out.pptx') as archive:
        xml=archive.read('ppt/slides/slide1.xml').decode()
        assert 'F6F4EF' in xml and '17324D' in xml and 'sz="2400"' in xml
        assert 'inline' in xml and len([p for p in archive.namelist() if p.startswith('ppt/media/')])>=1
    html.write_text(html.read_text().replace('object-fit:contain','object-fit:cover'))
    with pytest.raises(RuntimeError,match='crop scientific content'):
        service._run_node('html_to_pptx.mjs',args,timeout=90)
