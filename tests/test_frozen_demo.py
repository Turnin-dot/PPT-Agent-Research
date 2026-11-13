"""Frozen evidence/publication checks; no real model calls."""
import json, zipfile, xml.etree.ElementTree as ET
from tools.package_release import audit, candidates, ROOT

def test_frozen_snapshot_is_self_contained_and_honest():
    f=ROOT/'showcase/demo-b-2026-11-13'
    s=json.loads((f/'run-summary.json').read_text(encoding='utf8'))
    t=json.loads((f/'tool-trace.json').read_text(encoding='utf8'))['events']
    assert s['status']=='incomplete' and not s['export']['rendered_visual_comparison']
    assert len(t)==s['tool_calls']==39
    assert sum(x['failed'] for x in t)==s['tool_failures']==5
    assert len(s['model_calls'])==33
    for key in ['input_tokens','output_tokens']:
        assert sum(c['usage'][key] for c in s['model_calls'])==s['usage'][key]
    assert s['cost'] is None and s['sdk_http_retry_count'] is None
    assert not any('max' in c['model'].lower() for c in s['model_calls'])
    from html.parser import HTMLParser
    class Images(HTMLParser):
        def __init__(self):super().__init__();self.sources=[]
        def handle_starttag(self,tag,attrs):
            if tag=='img':self.sources.append(dict(attrs)['src'])
    p=Images();p.feed((f/'slide.html').read_text(encoding='utf8'))
    assert p.sources and all((f/src).is_file() for src in p.sources)
    assert audit([p for p in f.rglob('*') if p.is_file()])==[]

def test_export_is_editable_and_has_no_external_relationships():
    ns={'p':'http://schemas.openxmlformats.org/presentationml/2006/main','a':'http://schemas.openxmlformats.org/drawingml/2006/main'}
    with zipfile.ZipFile(ROOT/'showcase/demo-b-2026-11-13/final.pptx') as z:
        assert z.testzip() is None
        x=ET.fromstring(z.read('ppt/slides/slide1.xml'))
        assert len([s for s in x.findall('.//p:sp',ns) if s.findall('.//a:t',ns)])==31
        assert len(x.findall('.//p:pic',ns))==1
        for n in z.namelist():
            if n.endswith('.rels'):assert b'TargetMode="External"' not in z.read(n)

def test_packager_scope():
    paths={p.relative_to(ROOT).as_posix() for p in candidates()}
    assert 'showcase/demo-b-2026-11-13/source.pdf' in paths
    assert 'showcase/demo-b-2026-11-13/final.pptx' in paths
    assert not any(p.startswith('showcase/assets/historical-') for p in paths)
    assert not any(p.startswith(('outputs/','.build/','node_modules/')) for p in paths)

def test_guard_checks_office_metadata_without_echo(tmp_path):
    p=tmp_path/'bad.pptx';token='sk-'+('x'*32)
    with zipfile.ZipFile(p,'w') as z:z.writestr('docProps/core.xml','<value>'+token+'</value>')
    findings=audit([p]);assert findings and token not in str(findings)

def test_guard_checks_pdf_metadata_without_echo(tmp_path):
    import fitz
    p=tmp_path/'bad.pdf';token='sk-'+('x'*32)
    with fitz.open() as d:
        d.new_page();d.set_metadata({'author':token});d.save(p)
    findings=audit([p]);assert findings and token not in str(findings)
