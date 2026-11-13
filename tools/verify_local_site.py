from pathlib import Path
from functools import partial
from http.server import SimpleHTTPRequestHandler,ThreadingHTTPServer
import threading, subprocess, os, json, argparse
from demos.common import ROOT, config
parser=argparse.ArgumentParser(description='Read-only local static showcase verification')
parser.add_argument('--output',default=str(ROOT/'outputs/showcase-verification'))
args=parser.parse_args()
verification_output=Path(args.output).resolve()
cfg=config(ROOT/'outputs/environment')
class Handler(SimpleHTTPRequestHandler):
 def log_message(self,*args):pass
 def do_GET(self):
  if self.path=='/favicon.ico':self.send_response(204);self.end_headers();return
  super().do_GET()
server=ThreadingHTTPServer(('127.0.0.1',0),partial(Handler,directory=str(ROOT/'showcase')))
thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
env=dict(os.environ)
if cfg.chromium_executable:env['PPT_AGENT_CHROMIUM']=str(cfg.chromium_executable)
try:
 result=subprocess.run([str(cfg.node_executable),str(ROOT/'tools/verify_showcase.mjs'),f'http://127.0.0.1:{server.server_address[1]}',str(verification_output)],env=env,cwd=ROOT,capture_output=True,text=True,timeout=60)
 print(result.stdout);print(result.stderr)
 raise SystemExit(result.returncode)
finally:server.shutdown();server.server_close();thread.join()
