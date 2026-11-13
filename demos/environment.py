"""No-network dependency inspection. This never validates a remote model account."""
import json, os, subprocess
from pathlib import Path
from .common import ROOT, config

def inspect_environment(workspace):
    cfg=config(workspace);errors=[];runtime={}
    env=dict(os.environ)
    if cfg.node_modules:env['NODE_PATH']=str(cfg.node_modules)
    code="""const fs=require('fs');const p=require('playwright');const browser=process.env.PPT_AGENT_CHROMIUM||process.argv[1]||p.chromium.executablePath();console.log(JSON.stringify({node:process.version,playwright:require('playwright/package.json').version,pptxgenjs:JSON.parse(fs.readFileSync(require('path').join(process.env.NODE_PATH||'node_modules','pptxgenjs/package.json'),'utf8')).version,browser_exists:fs.existsSync(browser),browser}));"""
    try:
        result=subprocess.run([str(cfg.node_executable),'-e',code,str(cfg.chromium_executable or '')],
            cwd=ROOT,env=env,capture_output=True,text=True,encoding='utf8',timeout=15,check=True)
        runtime=json.loads(result.stdout)
        if not runtime['browser_exists']:errors.append('Chromium missing: run npx playwright install chromium or set PPT_AGENT_CHROMIUM')
    except Exception as exc:errors.append(type(exc).__name__+': '+str(exc))
    origins={}
    for name in ['agent_harness','ppt_agent_domain','ppt_agent_api']:
        try:
            module=__import__(name);path=Path(module.__file__).resolve();origins[name]=str(path)
            if not path.is_relative_to(ROOT):errors.append('Module is outside release: '+name)
        except Exception as exc:errors.append(name+': '+str(exc))
    return dict(ready_for_local_tools=not errors,errors=errors,runtime=runtime,module_origins=origins,
        network_requests=0,remote_model_availability='not tested')
