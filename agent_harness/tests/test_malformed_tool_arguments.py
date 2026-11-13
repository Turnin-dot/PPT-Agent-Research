from types import SimpleNamespace

from agent_harness.core.messages import ToolCall
from agent_harness.core.models import _tool_arguments, _openai_usage
from agent_harness.core.tools import tool,run_tool_calls


def test_malformed_json_is_reported_without_running_body_and_usage_survives():
    calls=[]
    @tool
    def save(text:str) -> str:
        calls.append(text)
        return text
    raw='{"text":"an unescaped "quote" here"}'
    args=_tool_arguments(raw)
    result=run_tool_calls([ToolCall('save',args)],{'save':save})[0]
    assert result.is_error and 'INVALID_TOOL_ARGUMENTS_JSON' in result.content and not calls
    assert args['__harness_argument_error__']['raw_arguments']==raw
    usage=_openai_usage(SimpleNamespace(prompt_tokens=9,completion_tokens=3))
    assert usage.input_tokens==9 and usage.output_tokens==3
    fixed=run_tool_calls([ToolCall('save',_tool_arguments('{"text":"fixed"}'))],{'save':save})[0]
    assert not fixed.is_error and calls==['fixed']


def test_nonobject_arguments_cannot_reach_legacy_tool():
    assert '__harness_argument_error__' in _tool_arguments('[1,2]')


def test_actual_openai_adapter_and_agent_loop_keep_usage_and_continue():
    from agent_harness.core.models import OpenAIChatModel
    from agent_harness.core.loop import Agent
    responses=[]
    model=OpenAIChatModel.__new__(OpenAIChatModel)
    model.model='offline-fixture';model.kwargs={}
    usage=SimpleNamespace(prompt_tokens=9,completion_tokens=3)
    bad=SimpleNamespace(name='save',arguments='{"text":"bad "quote""}')
    responses.append(SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='',
        tool_calls=[SimpleNamespace(function=bad,id='bad-call')]),finish_reason='tool_calls')],usage=usage))
    responses.append(SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='handled',
        tool_calls=[]),finish_reason='stop')],usage=usage))
    model.client=SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **kw:responses.pop(0))))
    @tool
    def save(text:str) -> str:
        raise AssertionError('Malformed arguments must not reach the body')
    events=list(Agent(model=model,tools=[save],stream_text=False).run('fixture'))
    result=next(e.data['message'] for e in events if e.type=='tool_result')
    assert result.is_error and 'INVALID_TOOL_ARGUMENTS_JSON' in result.content
    end=next(e.data for e in events if e.type=='run_end')
    assert end['usage']['input_tokens']==18 and end['usage']['output_tokens']==6
    assert end['final_text']=='handled'
