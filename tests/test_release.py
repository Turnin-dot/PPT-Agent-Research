"""Release regressions: synthetic inputs only. No real model calls."""
import json, subprocess, sys
from pathlib import Path
from html.parser import HTMLParser
import pytest
from demos.common import ROOT, config, harness
from demos.sample_data import prepare
from agent_harness.core import FakeModel


def test_prepared_assets_are_owned_fixed_inputs_and_detect_tampering(tmp_path):
    w=tmp_path/'sample';value=prepare(w,config(w))
    assert 'self-authored' in value['input_scope']
    from ppt_agent_domain.presentation.markdown import read_markdown
    assert read_markdown(value['manifest'])['available']
    assert 'Synthetic research fixture' in read_markdown(value['manifest'],pdf_pages=[1])['pages'][0]['text']
    assert prepare(w,config(w),resume=True)==value
    with pytest.raises(FileExistsError):prepare(w,config(w))
    (w/'input/diagram.png').write_bytes(b'tampered')
    with pytest.raises(ValueError,match='changed'):prepare(w,config(w),resume=True)


def test_formal_assembly_preserves_tools_skills_and_independent_layers(tmp_path):
    h=harness(tmp_path,FakeModel([]),config(tmp_path))
    names={t.name for t in h.tools}
    assert len(names)==40
    assert {'crop_pdf_asset','review_slide','save_slide_binding','export_editable_pptx'}<=names
    assert {s.name for s in h.skills}=={'paper-planning','pdf-asset-preparation','ppt-production'}
    import agent_harness
    assert Path(agent_harness.__file__).resolve().is_relative_to(ROOT)
    h.close()


def test_real_entry_preflight_cannot_invoke_models(tmp_path,monkeypatch):
    import demos.single_page as entry
    def forbidden(*a,**kw):raise AssertionError('Preflight attempted model construction')
    monkeypatch.setattr(entry,'init_chat_model',forbidden)
    monkeypatch.setattr(sys,'argv',['single_page','--output',str(tmp_path)])
    entry.main()
    result=json.loads((tmp_path/'preflight.json').read_text(encoding='utf8'))
    assert result['mode']=='preflight_no_api_calls'
    assert result['tool_count']==40
    assert result['model_specs']['asset_inspection']=='deepseek:deepseek-flash'
    assert 'DEEPSEEK_API_KEY' in result['api_key_present']
    assert not (tmp_path/'prepared.json').exists()


def test_static_showcase_local_resources_exist():
    class Links(HTMLParser):
        links=[]
        def handle_starttag(self,tag,attrs):
            for key,value in attrs:
                if key in ('src','href') and value and not value.startswith('#'):
                    self.links.append(value)
    parser=Links();parser.feed((ROOT/'showcase/index.html').read_text(encoding='utf8'))
    for path in parser.links:
        assert not path.startswith(('http:','https:','file:'))
        assert (ROOT/'showcase'/path).is_file()
    frozen=ROOT/'showcase/demo-b-2026-11-13'
    html=(frozen/'slide.html').read_text(encoding='utf8')
    assert '<img' in html and '<script' not in html
    import hashlib
    provenance=json.loads((frozen/'provenance.json').read_text(encoding='utf8'))
    for item in provenance['files']:
        assert hashlib.sha256((frozen/item['path']).read_bytes()).hexdigest()==item['sha256']
