"""Deadline supervisor only. It starts the formal CLI; no parsing, planning or page tools here."""
import argparse, os, subprocess, sys, time
from pathlib import Path
from demos.common import dump

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--pdf',required=True);p.add_argument('--output',required=True)
    p.add_argument('--seconds',type=float,default=900,help='Wall-clock deadline in seconds; default/maximum 900 (15 minutes)');p.add_argument('--export',action='store_true')
    a=p.parse_args()
    if not 0<a.seconds<=900:raise ValueError('Deadline must be in (0, 900] seconds')
    w=Path(a.output).resolve();w.mkdir(parents=True,exist_ok=True)
    command=[sys.executable,'-u','-m','demos.single_page','--run','--max-turns','100000','--pdf',str(Path(a.pdf).resolve()),'--output',str(w)]
    if a.export:command.append('--export')
    flags=(subprocess.CREATE_NEW_PROCESS_GROUP|subprocess.CREATE_NO_WINDOW) if os.name=='nt' else 0
    started=time.perf_counter();timed_out=False
    with (w/'console.log').open('x',encoding='utf8') as log:
        process=subprocess.Popen(command,stdout=log,stderr=subprocess.STDOUT,creationflags=flags)
        dump(w/'launch.json',dict(command=command,deadline_seconds=a.seconds,process_id=process.pid,start_unix=time.time(),note='No task tools are invoked by the supervisor; round safety limit is deliberately nonbinding.'))
        try:process.wait(timeout=a.seconds)
        except subprocess.TimeoutExpired:
            timed_out=True
            if os.name=='nt':subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,check=False)
            else:process.terminate()
            try:process.wait(timeout=3)
            except subprocess.TimeoutExpired:process.kill()
    value=dict(deadline_seconds=a.seconds,wall_seconds=time.perf_counter()-started,timed_out=timed_out,exit_code=process.returncode,
        status='deadline_reached_partial_artifacts_retained' if timed_out else 'formal_cli_ended',
        billing='In-flight provider requests may still be billed after local cancellation; no false zero usage claim')
    dump(w/'timed-execution.json',value);print(value)
    raise SystemExit(124 if timed_out else process.returncode)
if __name__=='__main__':main()
