from agent_harness.core import events as ev
from agent_harness.core.events import Event
from agent_harness.core.messages import AIMessage, HumanMessage, ToolCall, ToolMessage, Usage
from agent_harness.core.models import FakeModel
from agent_harness.runtime import Harness, HarnessConfig
from agent_harness.runtime.session import Session


def test_compaction_checkpoint_replays_exact_active_messages_without_rewriting_log(tmp_path):
    session = Session(str(tmp_path / 'session.jsonl'))
    session.append(Event(ev.USER_MESSAGE, {'message': HumanMessage(content='old evidence' * 2000)}))
    call = ToolCall('lookup', {'id': 'asset-42'})
    checkpoint = [HumanMessage(content='goal + summary'), AIMessage(tool_calls=[call]),
                  ToolMessage(content='source-42', tool_call_id=call.id, name='lookup')]
    session.append(Event(ev.COMPACTION, {'messages': checkpoint, 'before_tokens': 9000, 'after_tokens': 20}))
    answer = AIMessage(content='saved', usage=Usage(input_tokens=30, output_tokens=2))
    session.append(Event(ev.ASSISTANT_MESSAGE, {'message': answer}))
    before = (tmp_path / 'session.jsonl').read_bytes()
    assert session.messages() == checkpoint + [answer]
    assert session.needs_compaction_recovery is False
    assert (tmp_path / 'session.jsonl').read_bytes() == before


def test_harness_persists_compacted_history_and_does_not_compact_again_on_resume(tmp_path):
    model = FakeModel([AIMessage(content='remember source-42'), AIMessage(content='first complete')])
    cfg = HarnessConfig(model=model, workspace=str(tmp_path), session_root=str(tmp_path / 'sessions'),
                        max_context_tokens=500, enable_bash=False)
    first = Harness(cfg)
    events = list(first.run('task-42 ' + 'evidence ' * 700))
    # A single-message initial turn cannot be compacted yet. Create the
    # checkpoint through a real subsequent Harness invocation instead.
    sid = first.last_session.id
    second_model = FakeModel([AIMessage(content='retained task-42'), AIMessage(content='second complete')])
    second = Harness(HarnessConfig(**{**cfg.__dict__, 'model': second_model}))
    second.context.keep_recent = 1
    second_events = list(second.run('continue task-42', session_id=sid))
    checkpoints = [e for e in second_events if e.type == ev.COMPACTION]
    assert checkpoints and checkpoints[-1].data['messages']
    replayed = second.last_session.messages()
    assert replayed[0].content.startswith('[前情提要')
    third_model = FakeModel([AIMessage(content='finished')])
    third = Harness(HarnessConfig(**{**cfg.__dict__, 'model': third_model, 'max_context_tokens': 20000}))
    third_events = list(third.run('finish', session_id=sid))
    assert not any(e.type == ev.COMPACTION for e in third_events)
    assert len(third_model.calls) == 1
    assert 'retained task-42' in third_model.calls[0][1].content


def test_legacy_compaction_forces_metered_recovery_despite_small_latest_usage(tmp_path):
    cfg = HarnessConfig(model=FakeModel([AIMessage(content='recovered goal'), AIMessage(content='done')]),
                        workspace=str(tmp_path), session_root=str(tmp_path / 'sessions'),
                        max_context_tokens=120000, enable_bash=False)
    harness = Harness(cfg)
    session = harness.sessions.create('legacy')
    for i in range(16):
        session.append(Event(ev.USER_MESSAGE, {'message': HumanMessage(content=f'goal-{i}') }))
    session.append(Event(ev.COMPACTION, {'before_tokens': 93000, 'after_tokens': 7000}))
    session.append(Event(ev.ASSISTANT_MESSAGE, {'message': AIMessage(content='later', usage=Usage(input_tokens=100, output_tokens=2))}))
    legacy_bytes = (tmp_path / 'sessions/legacy.jsonl').read_bytes()
    events = list(harness.run('continue', session_id='legacy'))
    assert any(e.type == ev.COMPACTION for e in events)
    assert any(e.type == ev.MODEL_CALL and e.data['category'] == 'context_compaction' for e in events)
    assert harness.last_session.messages()[0].content.startswith('[前情提要')
    assert harness.last_session.needs_compaction_recovery is False
    assert (tmp_path / 'sessions/legacy.jsonl').read_bytes().startswith(legacy_bytes)
