"""Read-only Demo B progress viewer. No model calls, task writes or approval changes."""
from __future__ import annotations
import argparse,json,time
from collections import Counter
from pathlib import Path


def read_json(path):
    try:return json.loads(Path(path).read_text(encoding='utf-8-sig'))
    except (OSError,ValueError):return {}


def snapshot(output):
    root=Path(output).expanduser().resolve()
    if not root.is_dir():return {'运行状态':'等待运行目录创建','阶段':{}}
    prepared=read_json(root/'prepared.json');mode=prepared.get('mode','prepared_assets') if prepared else 'unknown'
    events=[]
    for path in sorted(root.glob('*-events.jsonl')):
        try:lines=path.read_text(encoding='utf8').splitlines()
        except OSError:continue
        for line in lines:
            try:events.append(json.loads(line))
            except ValueError:continue  # A live writer may not have completed the last line.
    events.sort(key=lambda e:e.get('ts',0))
    starts={};results={};success=set();failed=[];calls=[]
    for e in events:
        data=e.get('data',{})
        if e.get('type')=='tool_start':
            call=data.get('call',{})
            if isinstance(call,dict):starts[call.get('id')]=call.get('name','unknown')
        elif e.get('type')=='tool_result':
            msg=data.get('message',{});results[msg.get('tool_call_id')]=msg.get('name','unknown')
            if msg.get('is_error'):failed.append(msg.get('name','unknown'))
            else:success.add(msg.get('name','unknown'))
        elif e.get('type')=='model_call':calls.append(data)
    pending=[name for key,name in starts.items() if key not in results]
    task=read_json(root/'tasks/sample/task.json');slide=task.get('slides',{}).get('slide-01',{})
    version=(slide.get('html')or{}).get('version')
    def report_state(name):
        ref=slide.get(name)or{}
        report=read_json(ref.get('path',''))
        if not ref or not report:return '未保存'
        if ref.get('html_version')!=version or ref.get('applicability')!='current':return '已失效/非当前版本'
        return '正式记录: '+str(report.get('review_verdict','unknown'))
    manifests=[]
    for base in [root/'pdf',root/'pdf_assets',root/'input']:
        if base.is_dir():
            for p in base.rglob('manifest.json'):
                m=read_json(p)
                if m.get('schema_version')=='pdf-assets-prototype/v1':manifests.append((p,m))
    manifest=manifests[-1][1] if manifests else {}
    revision=manifest.get('revision')
    pdf_reviews=[v for v in manifest.get('reviews',[]) if v.get('manifest_revision')==revision and v.get('applicability')=='current']
    pdf_review=pdf_reviews[-1] if pdf_reviews else {}
    if mode=='unknown':parse_state='准备/预检中，尚未确定输入模式'
    elif mode!='raw_pdf':parse_state='跳过：预制/合成资产，不是实际PDF解析'
    elif 'parse_pdf' in success:parse_state='解析工具成功；新解析/复用需查详细日志'
    elif 'prepare_pdf_assets' in success:parse_state='资产准备工具成功；解析详情需查记录'
    else:parse_state='尚无解析成功事件'
    stages={'输入模式':mode,'PDF解析':parse_state,
        '正式资产':f"{len(manifest.get('assets',[]))}项 / revision {revision}" if manifest else '未保存',
        'PDF资产审核':(str(pdf_review.get('review_verdict'))+' / verified='+str(pdf_review.get('is_verified'))+' / full_coverage='+str(pdf_review.get('full_document_coverage'))) if pdf_review else '未保存当前版本报告',
        '页面规划':f"{len(task.get('slide_plans',{}))}页已保存",
        'HTML绑定':f"有HTML v{version}及绑定记录" if version and slide.get('binding') else '未成功绑定',
        'HTML渲染':'有当前版本截图记录' if (slide.get('preview')or{}).get('html_version')==version and version else '未保存当前版本截图',
        '程序布局检查':report_state('layout_report'),'内容审核':report_state('content_review'),
        '视觉审核':report_state('visual_review'),'综合页面审核':report_state('review')}
    exports=task.get('exports',[])
    current=[x for x in exports if x.get('applicability')=='current']
    latest=current[-1] if current else {}
    stages['PPTX导出']='有当前导出记录' if latest else '未保存当前导出'
    stages['PPTX渲染']='有渲染记录' if latest.get('render') else '未保存'
    validation=latest.get('validation')or{}
    stages['导出验收']=str(validation.get('verdict','未保存'))
    delivery=(task.get('delivery')or{}).get('latest_validation')or{}
    stages['最终交付验收']=str(delivery.get('verdict','未保存'))
    last_start=max((e.get('ts',0) for e in events if e.get('type')=='run_start'),default=0)
    timed_path=root/'timed-execution.json';timed=read_json(timed_path)
    if timed and timed_path.stat().st_mtime<last_start:timed={}  # A later direct CLI resume supersedes the old stop record.
    end=next((e['data'] for e in reversed(events) if e.get('type')=='run_end' and e.get('ts',0)>=last_start),None)
    if timed.get('timed_out'):status='超时中止，保留已有产物'
    elif timed:status='入口已退出；退出码 '+str(timed.get('exit_code'))
    elif end:status='本轮已结束: '+str(end.get('stop_reason'))+'（不等于交付通过）'
    elif events:status='等待工具返回' if pending else ('模型响应接收中' if events[-1].get('type')=='text_delta' else '等待模型/下一条事件')
    else:status='等待Agent事件（可能仍在预检）'
    launch=read_json(root/'launch.json');elapsed=(time.time()-launch['start_unix']) if launch.get('start_unix') else None
    if timed:elapsed=timed.get('wall_seconds',elapsed)
    fake=bool(calls) and all(c.get('model')=='FakeModel' for c in calls)
    return {'运行状态':status,'用时秒':round(elapsed,1) if elapsed is not None else None,
        '模式说明':'FakeModel模拟，不是模型自主生成验收' if fake else '只读正式记录概览，不代替版本核验和最终验收',
        '最后事件':events[-1].get('type') if events else None,
        '最后提交工具':list(starts.values())[-1] if starts else None,
        '待返回工具':[] if timed or end else pending,'累计工具失败':len(failed),'最近失败工具':failed[-3:],
        '已完成模型调用':len(calls),'模型分布':dict(Counter(c.get('model') for c in calls)),
        '已返回Token':{k:sum((c.get('usage')or{}).get(k)or 0 for c in calls) for k in ['input_tokens','output_tokens','cached_tokens']},
        '阶段':stages,'说明':'tool_start仅表示已提交；没有新事件不等于卡死，可能在解析/模型思考/排队/网络等待。中止请求用量可能未知。'}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',required=True);p.add_argument('--watch',action='store_true');p.add_argument('--interval',type=float,default=3);p.add_argument('--json',action='store_true');a=p.parse_args()
    if not .5<=a.interval<=60:p.error('--interval must be between 0.5 and 60 seconds')
    try:
        while True:
            state=snapshot(a.output)
            if a.watch and not a.json:print('\033[2J\033[H',end='')
            print(json.dumps(state,ensure_ascii=False,indent=2),flush=True)
            if not a.watch:return
            time.sleep(a.interval)
    except KeyboardInterrupt:return
if __name__=='__main__':main()
