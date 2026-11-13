from dataclasses import asdict

import pytest

from agent_harness.core.messages import AIMessage, HumanMessage, ToolCall, Usage
from agent_harness.core.models import BaseChatModel
from ppt_agent_domain.pdf_assets.storage import read_json, sha256_file
from ppt_agent_domain.presentation.planning_config import PlanningConfig
from ppt_agent_domain.presentation.planning_observer import ObservedPlanningModel


class CompletedProvider(BaseChatModel):
    def __init__(self):
        self.calls=[]
        self.response=AIMessage(content='',tool_calls=[ToolCall('save_slide_binding',{'slide_id':'slide-01'})],
            usage=Usage(input_tokens=321,output_tokens=42,cached_tokens=64,reasoning_tokens=12))

    def invoke(self,messages):
        self.calls.append(messages)
        return self.response


def test_mixed_source_labels_do_not_discard_completed_response_or_mutate_sources(tmp_path):
    from PIL import Image
    first=tmp_path/'source-page.png';second=tmp_path/'figure.png'
    Image.new('RGB',(8,8),'white').save(first);Image.new('RGB',(8,8),'blue').save(second)
    hashes=[sha256_file(p) for p in (first,second)]
    provider=CompletedProvider()
    observer=ObservedPlanningModel(PlanningConfig(),'planning',tmp_path/'run',factory=lambda phase:provider)
    source_images={1:str(first),'figure-2':str(second)};observer.source_images=source_images
    response=observer.invoke([HumanMessage(content='Use the current source evidence.')])
    assert response is provider.response and len(provider.calls)==1
    assert response.tool_calls[0].args=={'slide_id':'slide-01'}
    entry=read_json(tmp_path/'run/model-ledger.json')['calls'][0]
    assert entry['status']=='succeeded' and entry['usage']==asdict(response.usage)
    assert entry['source_visual_pages']==['1','figure-2']
    assert observer.source_images is source_images and set(source_images)=={1,'figure-2'}
    assert hashes==[sha256_file(p) for p in (first,second)]
    assert len(provider.calls[0][-1].images)==2


def test_post_response_storage_failure_keeps_real_usage_and_still_fails(tmp_path,monkeypatch):
    import ppt_agent_domain.presentation.planning_observer as module
    original=module.write_json
    def fail_response(path,value):
        if path.name.endswith('-response.json'):raise OSError('simulated response storage failure')
        original(path,value)
    monkeypatch.setattr(module,'write_json',fail_response)
    provider=CompletedProvider()
    observer=ObservedPlanningModel(PlanningConfig(),'planning',tmp_path/'run',factory=lambda phase:provider)
    with pytest.raises(OSError,match='simulated response storage failure'):
        observer.invoke([HumanMessage(content='source')])
    entry=read_json(tmp_path/'run/model-ledger.json')['calls'][0]
    assert len(provider.calls)==1 and entry['status']=='failed'
    assert entry['usage']==asdict(provider.response.usage) and entry['usage_unknown'] is False
    assert entry['failure_stage']=='post_response'


def test_compaction_guard_counts_only_dispatched_tools(tmp_path):
    from types import SimpleNamespace
    from agent_harness.core.context import _SUMMARIZE_PROMPT
    from agent_harness.core.messages import SystemMessage
    provider = CompletedProvider()
    observer = ObservedPlanningModel(PlanningConfig(), 'planning', tmp_path / 'run', factory=lambda phase: provider)
    # These schemas are bound to the main Agent but absent from a summary call.
    observer.bind_tools([SimpleNamespace(name='large_tool', parameters={'description': 'x' * 270000})])
    response = observer.invoke([SystemMessage(content=_SUMMARIZE_PROMPT), HumanMessage(content='summarize the existing log')])
    assert response is provider.response and len(provider.calls) == 1
    assert provider._bound_tools == []
    assert len(observer._bound_tools) == 1
    entry = read_json(tmp_path / 'run/model-ledger.json')['calls'][0]
    assert entry['category'] == 'context_compaction' and entry['input_upper_tokens'] < 10000
    assert read_json(tmp_path / 'run/planning/calls' / (entry['request_id'] + '-input.json'))['tools'] == []
