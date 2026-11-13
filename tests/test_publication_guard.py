"""Publication safety checks use fabricated values only; no real credentials."""
import importlib.util
from pathlib import Path
import pytest
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('publication_packager',ROOT/'tools/package_release.py')
packager=importlib.util.module_from_spec(spec);spec.loader.exec_module(packager)

@pytest.mark.parametrize('payload',[
    'sk-'+('x'*32),
    'ghp_'+('x'*36),
    '-----'+'BEGIN PRIVATE KEY'+'-----',
    'https:'+('/'*2)+'account:'+('x'*20)+'@example.invalid/db',
    'https://example.invalid/?access_token='+('x'*25),
    'C:'+chr(92)+'Users'+chr(92)+'placeholder'+chr(92)+'private.txt',
])
def test_guard_rejects_sensitive_content_without_echoing_values(tmp_path,payload):
    p=tmp_path/'candidate.txt';p.write_text(payload,encoding='utf8')
    result=packager.audit([p]);assert result
    assert payload not in '\n'.join(result)


def test_guard_preserves_public_provider_endpoints_and_empty_environment_template(tmp_path):
    p=tmp_path/'.env.example';p.write_text('DASHSCOPE_API_KEY=\nARK_API_KEY=\nhttps://api.deepseek.com\n',encoding='utf8')
    assert packager.audit([p])==[]


def test_guard_does_not_open_real_environment_container(tmp_path,monkeypatch):
    p=tmp_path/'.env';p.write_text('never-read-this-file',encoding='utf8')
    original=Path.read_text
    def restricted(self,*args,**kwargs):
        if self==p:raise AssertionError('Credential container was read')
        return original(self,*args,**kwargs)
    monkeypatch.setattr(Path,'read_text',restricted)
    assert 'not read' in packager.audit([p])[0]


def test_static_verifier_accepts_help_without_launching_browser():
    import subprocess,sys
    result=subprocess.run([sys.executable,str(ROOT/'tools/verify_local_site.py'),'--help'],cwd=ROOT,capture_output=True,text=True)
    assert result.returncode==0
    assert '--output' in result.stdout
