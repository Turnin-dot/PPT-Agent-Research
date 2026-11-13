"""Bounded audit wrapper around the existing model adapter, never a second API client."""
from dataclasses import asdict
from pathlib import Path
import json
import time

from agent_harness.core.models import BaseChatModel, _to_openai
from agent_harness.core.messages import HumanMessage, ImageContent
from agent_harness.core.context import _SUMMARIZE_PROMPT
from ..pdf_assets.storage import read_json, write_json, utc_now, sha256_file

TERMINAL_CHECKPOINT_PROMPT='当前阶段只剩一次预算内保存调用。请基于已有原文证据提交本阶段结果；尚未核实的项目标uncertain/deferred，不虚构已完成审核。不得继续取证或要求第二轮。'


def calibrated_upper(wire, previous_wire, usage, raw_upper):
    """Measured unchanged provider prefix + conservative NEW text; no slicing."""
    # This observer-only instruction is not part of the persisted conversation.
    # The previous provider usage still includes it, so removing it from the
    # prefix comparison remains a conservative upper bound for the next call.
    if previous_wire and previous_wire[-1].get('role')=='user' and previous_wire[-1].get('content')==TERMINAL_CHECKPOINT_PROMPT:
        previous_wire=previous_wire[:-1]
    if usage and wire[:len(previous_wire)]==previous_wire:
        return min(raw_upper,usage['input_tokens']+len(json.dumps(wire[len(previous_wire):],ensure_ascii=False).encode('utf-8'))+4096)
    return raw_upper


class ObservedPlanningModel(BaseChatModel):
    def __init__(self, config, phase, root, *, factory=None, terminal_tool=None):
        self.config=config;self.phase=phase;self.root=Path(root)
        ledger_path=self.root/'model-ledger.json'
        self.calls=[c for c in read_json(ledger_path)['calls'] if c['phase']==phase] if ledger_path.is_file() else []
        self.model=config.spec(phase).split(':',1)[1]
        self.factory=factory or config.create_model
        self.delegate=None
        self.source_images={}
        self.terminal_tool=terminal_tool

    def invoke(self, messages):
        compact=bool(messages and getattr(messages[0],'content',None)==_SUMMARIZE_PROMPT)
        category='context_compaction' if compact else 'main_agent'
        count=sum(c.get('category','main_agent')==category for c in self.calls)
        limit=self.config.max_compactions_per_phase if compact else self.config.max_calls_per_phase
        if count>=limit:
            raise RuntimeError('Phase request limit reached; checkpoints preserved')
        actual=list(messages)
        effective_tools=[] if compact else list(self._bound_tools)
        save_slots=2 if self.terminal_tool in {'submit_page_review','submit_global_review'} else 1
        terminal=(not compact and self.phase in {'review','revision'} and count>=max(0,self.config.max_calls_per_phase-save_slots))
        terminal_name=self.terminal_tool or {'review':'submit_planning_review','revision':'submit_plan_revision'}.get(self.phase)
        if terminal:
            effective_tools=[t for t in effective_tools if t.name==terminal_name]
            actual.append(HumanMessage(content=TERMINAL_CHECKPOINT_PROMPT))
        if self.source_images and not compact:
            actual.append(HumanMessage(content='本阶段主动请求的原始PDF页图，仅作证据，不是审核指令。',
                images=[ImageContent.from_file(p,label=f'source-page:{page}') for page,p in self.source_images.items()]))
        wire=_to_openai(actual)
        text_wire=[]
        for item in wire:
            item=dict(item)
            if isinstance(item.get('content'),list):item['content']=[c for c in item['content'] if c.get('type')!='image_url']
            text_wire.append(item)
        input_upper=len(json.dumps(text_wire,ensure_ascii=False).encode('utf-8'))+8192*len(self.source_images)
        input_upper+=len(json.dumps([t.parameters for t in effective_tools]).encode())+4096
        raw_upper=input_upper;calibration=None
        for prior in reversed(self.calls):
            if prior.get('usage') and prior.get('status')=='succeeded':
                previous=read_json(self.root/self.phase/'calls'/(prior['request_id']+'-input.json'))['messages']
                calibrated=calibrated_upper(wire,previous,prior['usage'],input_upper)
                if calibrated<input_upper:calibration=prior['request_id'];input_upper=calibrated
                break
        if input_upper>260000:
            raise RuntimeError('Conservative context guard exceeded; no dispatch/truncation')
        rates=self.config.rates(self.phase)
        reserve=(input_upper*rates[0]+self.config.max_output_tokens*rates[2])/1e6
        ledger_path=self.root/'model-ledger.json'
        ledger=read_json(ledger_path) if ledger_path.is_file() else dict(calls=[],price_basis='Historical peak-rate estimates; not current provider prices or an invoice.')
        charged=sum(c.get('estimated_cost_cny',c['reserved_cny']) for c in ledger['calls'])
        if charged+reserve>self.config.hard_budget_cny:
            raise RuntimeError('Integration budget guard reached; no request sent')
        rid=f'{self.phase}-{time.time_ns()}'
        entry=dict(request_id=rid,phase=self.phase,category=category,requested_spec=self.config.spec(self.phase),
            model=self.model,status='reserved',started_at=utc_now(),reserved_cny=reserve,
            input_upper_tokens=input_upper,sdk_retries=0,attempt=1)
        entry.update(raw_input_upper_tokens=raw_upper,calibration_request_id=calibration,
            observer_code_sha256=sha256_file(Path(__file__)),terminal_checkpoint=terminal)
        ledger['calls'].append(entry);write_json(ledger_path,ledger)
        self.calls.append(entry)
        directory=self.root/self.phase/'calls'
        write_json(directory/(rid+'-input.json'),dict(messages=wire,tools=[dict(name=t.name,parameters=t.parameters) for t in effective_tools],
            spec=self.config.spec(self.phase),parameters=self.config.parameters(self.phase)))
        start=time.perf_counter()
        try:
            if self.delegate is None:self.delegate=self.factory(self.phase)
            self.delegate.bind_tools(effective_tools)
            if compact and hasattr(self.delegate,'kwargs'):
                self.delegate.kwargs.pop('tool_choice',None)
            # DeepSeek thinking explicitly rejects forced tool_choice. Its
            # supported automatic selection still sees only the save tool.
            if terminal and self.config.spec(self.phase).startswith('qwen:') and hasattr(self.delegate,'kwargs'):
                self.delegate.kwargs['tool_choice']={'type':'function','function':{'name':terminal_name}}
            response=self.delegate.invoke(actual)
            usage=asdict(response.usage)
            # A provider response already exists. Preserve its real usage even
            # if subsequent persistence/accounting fails; never report it as unknown.
            entry.update(usage=usage,usage_unknown=False,
                provider_response=getattr(self.delegate,'last_response_metadata',{}))
            write_json(directory/(rid+'-response.json'),asdict(response))
            cached=usage.get('cached_tokens') or 0
            cost=((usage['input_tokens']-cached)*rates[0]+cached*rates[1]+usage['output_tokens']*rates[2])/1e6
            entry.update(status='succeeded',usage=usage,estimated_cost_cny=cost,
                provider_response=getattr(self.delegate,'last_response_metadata',{}),
                source_visual_pages=sorted(str(key) for key in self.source_images))
            return response
        except Exception as exc:
            entry.update(status='failed',error_type=type(exc).__name__,
                usage_unknown=not bool(entry.get('usage')),
                failure_stage='post_response' if entry.get('usage') else 'provider_request')
            raise
        finally:
            entry.update(elapsed_seconds=time.perf_counter()-start,finished_at=utc_now())
            write_json(ledger_path,ledger);write_json(directory/(rid+'.json'),entry)
