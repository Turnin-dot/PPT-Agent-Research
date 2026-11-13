"""Fixed offline responses, including failed model calls and session replay."""
import json

from agent_harness.core.context import ContextManager
from agent_harness.core.events import MODEL_CALL, RUN_END
from agent_harness.core.loop import Agent
from agent_harness.core.messages import AIMessage, HumanMessage, ToolCall, ToolMessage, Usage
from agent_harness.core.metering import capture_model_calls, invoke_metered
from agent_harness.core.models import BaseChatModel
from agent_harness.core.tools import run_tool_calls, tool
from agent_harness.runtime.session import Session


class FixedModel(BaseChatModel):
    model='fixed-offline'

    def __init__(self,script):self.script=list(script)

    def invoke(self,messages):
        response=self.script.pop(0)
        if isinstance(response,Exception):raise response
        return response


def test_compaction_and_internal_usage_accounted_once_and_replayed(tmp_path):
    internal=FixedModel([AIMessage(content='image analysis',usage=Usage(7,1,0,2))])

    @tool
    def inspect_fixture() -> str:
        invoke_metered(internal,[HumanMessage(content='fixture image')])
        return 'result includes only a summary'

    model=FixedModel([
        AIMessage(content='compressed task',usage=Usage(10,2,1,3)),
        AIMessage(tool_calls=[ToolCall('inspect_fixture',{})],usage=Usage(20,3,1,5)),
        AIMessage(content='done',usage=Usage(30,4,1,6)),
    ])
    prior=[HumanMessage(content='task_id=t'),AIMessage(tool_calls=[ToolCall('prior',{},id='old')]),
           ToolMessage(name='prior',tool_call_id='old',content='old large output '*4000),
           HumanMessage(content='continue'),AIMessage(content='recent')]
    agent=Agent(model=model,tools=[inspect_fixture],context=ContextManager(max_context_tokens=1000,keep_recent=2),stream_text=False)
    session=Session(str(tmp_path/'session.jsonl'))
    events=list(session.record(agent.run('finish',prior_messages=prior)))
    calls=[e for e in events if e.type==MODEL_CALL]
    assert len(calls)==4
    end=next(e for e in events if e.type==RUN_END).data
    # Legacy run usage = main + compaction; internal tool usage is separate.
    assert end['usage']['input_tokens']==60 and end['usage']['output_tokens']==9
    metrics=end['metrics']
    assert metrics['total_known_usage']['input_tokens']==67
    assert metrics['total_known_usage']['output_tokens']==10
    assert metrics['total_known_usage']['cached_tokens']==16
    assert metrics['usage_by_category']['context_compaction']['calls']==1
    assert metrics['usage_by_category']['main_agent']['calls']==2
    assert metrics['usage_by_category']['internal_vision']['calls']==1
    assert metrics['tool_calls']==1 and metrics['tool_failures']==0
    assert metrics['tool_elapsed_seconds_sum']>=0
    restored=Session(str(tmp_path/'session.jsonl')).events()
    assert len([e for e in restored if e.type==MODEL_CALL])==4
    assert next(e for e in restored if e.type==RUN_END).data['metrics']==metrics


def test_failed_then_retried_internal_calls_preserve_usage_unknown(tmp_path):
    model=FixedModel([TimeoutError('fixture timeout'),AIMessage(content='ok',usage=Usage(9,2,1,3))])

    @tool
    def retry_fixture() -> str:
        try:invoke_metered(model,[],attempt=1)
        except TimeoutError:pass
        invoke_metered(model,[],attempt=2)
        return 'ok'

    result=run_tool_calls([ToolCall('retry_fixture',{})],{'retry_fixture':retry_fixture})[0]
    calls=result.result_meta['metrics']['internal_model_calls']
    assert [c['status'] for c in calls]==['failed','succeeded']
    assert calls[0]['usage'] is None and calls[1]['is_retry']
    assert calls[1]['usage']['cached_tokens']==3
    assert result.result_meta['metrics']['elapsed_seconds']>=0


def test_tool_error_still_has_timing_and_failed_model_record():
    @tool
    def broken_fixture() -> str:
        invoke_metered(FixedModel([ValueError('fixture')]),[])
        return 'unreachable'

    result=run_tool_calls([ToolCall('broken_fixture',{})],{'broken_fixture':broken_fixture})[0]
    assert result.is_error and result.result_meta['metrics']['failed']
    assert result.result_meta['metrics']['internal_model_calls'][0]['status']=='failed'


def test_thread_context_propagation_records_parallel_review_workers():
    from concurrent.futures import ThreadPoolExecutor
    from contextvars import copy_context
    with capture_model_calls() as calls:
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures=[pool.submit(copy_context().run,invoke_metered,
                FixedModel([AIMessage(content='ok',usage=Usage(1,1))]),[]) for _ in range(3)]
            for future in futures:future.result()
    assert len(calls)==3 and sum(c['usage']['input_tokens'] for c in calls)==3
