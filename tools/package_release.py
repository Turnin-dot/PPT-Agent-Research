"""Build an explicit allowlisted candidate archive. Does NOT grant a license or publish."""
import argparse, hashlib, json, re, zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
TOP={'README.md','AGENTS.md','THIRD_PARTY_NOTICES.md','.gitignore','.env.example',
     'pyproject.toml','package.json','package-lock.json','constraints-tested.txt','requirements-tested.txt'}
DIRS=['agent_harness/src','agent_harness/tests','packages/ppt_domain/src','packages/ppt_domain/tests',
      'apps/api/src','apps/api/tests','skills','demos','tests','docs','showcase','.github']
TOOLS=['tools/watch_demo_b.py','tools/run_demo_b_timed.py','tools/verify_local_site.py','tools/serve_showcase.py','tools/check_environment.py','tools/verify_showcase.mjs','tools/package_release.py']
SUB=['agent_harness/pyproject.toml','agent_harness/README.md','packages/ppt_domain/pyproject.toml',
     'packages/ppt_domain/README.md','apps/api/pyproject.toml','reports/verification.md','reports/verification.json']
ALLOWED={'.py','.typed','.md','.txt','.json','.png','.html','.mjs','.ps1','.toml','.yml','.patch','.jpg','.jpeg','.pdf','.pptx'}
EXCLUDED={'showcase/data/history.json','showcase/data/plan-excerpt.json','showcase/data/review-versions.json'}

def is_public(p):
    label=p.relative_to(ROOT).as_posix()
    return label not in EXCLUDED and not label.startswith('showcase/assets/historical-')

def candidates():
    paths={ROOT/p for p in TOP|set(TOOLS)|set(SUB) if (ROOT/p).is_file()}
    for folder in DIRS:
        for p in (ROOT/folder).rglob('*'):
            if p.is_file() and '__pycache__' not in p.parts and not any(x.endswith('.egg-info') for x in p.parts) and p.suffix in ALLOWED:paths.add(p)
    return sorted(p for p in paths if is_public(p))
def audit(files):
    """Report locations and categories only, never matched credential values."""
    checks={
        'private machine path':re.compile(r'(?:[A-Za-z]:[\\/]+(?:Users[\\/]+[^\s\\/"<>]+|Agent[\\/]+PPT Agent|anaconda3(?:[\\/]|\b)|model_cache(?:[\\/]|\b))|/(?:home|Users)/[^\s/"<>]+/)'),
        'possible credential token':re.compile(r'\b(?:sk-[A-Za-z0-9_-]{24,}|gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{35,}|AKIA[A-Z0-9]{16}|ASIA[A-Z0-9]{16}|xox[baprs]-[A-Za-z0-9-]{20,})\b'),
        'private key material':re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH |DSA |ENCRYPTED )?PRIVATE KEY-----'),
        'credentials embedded in URL':re.compile(r'\b(?:https?|postgres(?:ql)?|mysql|redis|mongodb(?:\+srv)?|amqps?)://[^\s/:@]+:[^\s/@]{3,}@',re.I),
        'credential query parameter':re.compile(r'[?&](?:api[_-]?key|access_token|client_secret|password|sig)=[A-Za-z0-9_%+/=.-]{16,}',re.I),
        'literal authorization credential':re.compile(r'\b(?:Bearer|Basic)\s+[A-Za-z0-9_+/=.-]{28,}'),
        'internal service URL':re.compile(r'https?://(?:10\.(?:\d{1,3}\.){2}\d{1,3}|192\.168\.\d{1,3}\.\d{1,3}|172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}|[A-Za-z0-9.-]+\.(?:corp|internal))(?=[:/\s"\x27]|$)',re.I),
    }
    issues=[]
    for p in files:
        try:label=p.relative_to(ROOT).as_posix()
        except ValueError:label=p.name
        if p.name=='.env' or (p.name.startswith('.env.') and p.name!='.env.example'):
            issues.append(label+': environment credential container (not read)');continue
        suffix=p.suffix.lower()
        if suffix in {'.png','.jpg','.jpeg'}:
            from PIL import Image
            with Image.open(p) as im:
                text=str(im.info)+' '+str(dict(im.getexif()))
        elif suffix=='.pptx':
            with zipfile.ZipFile(p) as z:
                text='\n'.join(z.read(n).decode('utf8') for n in z.namelist() if n.endswith(('.xml','.rels')))
        elif suffix=='.pdf':
            import fitz
            with fitz.open(p) as doc:
                text=str(doc.metadata)+'\n'+'\n'.join(page.get_text() for page in doc)
                text+='\n'+'\n'.join(doc.xref_object(i) for i in range(1,doc.xref_length()))
        else:
            text=p.read_text(encoding='utf-8-sig')
        for category,pattern in checks.items():
            if pattern.search(text):issues.append(label+': '+category)
    return issues

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--check',action='store_true');parser.add_argument('--output');args=parser.parse_args()
    files=candidates();issues=audit(files)
    if issues:raise SystemExit('\n'.join(issues))
    records=[dict(path=p.relative_to(ROOT).as_posix(),sha256=hashlib.sha256(p.read_bytes()).hexdigest(),bytes=p.stat().st_size) for p in files]
    manifest=dict(status='local candidate; no license selected, NOT published',files=records,
        omitted=['.env','.venv','node_modules','.build','outputs','raw local logs','third-party PDFs/figures (owned synthetic source explicitly included)','personal documents'],
        audit='allowlist plus regex scan: text, PDF text/objects, PPTX XML, image metadata; no OCR/steganography or legal audit')
    index=ROOT/'release_manifest.json';index.write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    if args.output:
        output=Path(args.output).resolve()
        if output.exists():raise FileExistsError('Refusing to overwrite existing archive')
        output.parent.mkdir(parents=True,exist_ok=True)
        with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as z:
            for p in [*files,index]:z.write(p,'PPT-Agent-Research/'+p.relative_to(ROOT).as_posix())
    print(json.dumps(dict(file_count=len(files)+1,bytes=sum(p.stat().st_size for p in files)+index.stat().st_size,scan_issues=issues,archive=args.output,license='none selected')))
if __name__=='__main__':main()
