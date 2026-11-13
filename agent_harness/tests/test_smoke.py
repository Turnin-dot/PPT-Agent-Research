from __future__ import annotations

import tempfile
import threading
import unittest

from pydantic import BaseModel, Field

from agent_harness.core import Agent, FakeModel, ToolCall, final_text, tool
from agent_harness.core.tools import run_tool_calls
from agent_harness.core import events as ev
from agent_harness.runtime import Harness, HarnessConfig


class CoreLoopTests(unittest.TestCase):
    def test_tool_result_returns_to_model(self) -> None:
        @tool
        def add(a: int, b: int) -> int:
            """Add two integers."""

            return a + b

        model = FakeModel(
            [
                [ToolCall("add", {"a": 2, "b": 3})],
                lambda messages: f"result={messages[-1].content}",
            ]
        )
        agent = Agent(model=model, tools=[add])

        agent.invoke("calculate")

        self.assertEqual(final_text(agent.last_messages), "result=5")
        self.assertEqual(len(model.calls), 2)

    def test_pydantic_tool_schema_and_validation_error_return_to_model(self) -> None:
        class AddInput(BaseModel):
            a: int = Field(ge=0, description="first non-negative integer")
            b: int = Field(ge=0, description="second non-negative integer")

        @tool(args_schema=AddInput)
        def add(a: int, b: int) -> int:
            """Add two validated integers."""

            return a + b

        self.assertEqual(add.parameters["properties"]["a"]["minimum"], 0)
        self.assertEqual(
            add.parameters["properties"]["a"]["description"],
            "first non-negative integer",
        )
        model = FakeModel(
            [
                [ToolCall("add", {"a": -1, "b": 2})],
                lambda messages: (
                    "correctable=" + str(messages[-1].is_error).lower()
                    if "a:" in messages[-1].content
                    else "missing-detail"
                ),
            ]
        )
        agent = Agent(model=model, tools=[add], parallel_tools=False)
        agent.invoke("calculate")
        self.assertEqual(final_text(agent.last_messages), "correctable=true")

    def test_parallel_safe_tools_overlap_but_serial_tools_do_not(self) -> None:
        barrier = threading.Barrier(2)

        @tool
        def parallel_probe(label: str) -> str:
            """Wait for another read-only probe."""

            barrier.wait(timeout=1)
            return label

        active = 0
        max_active = 0
        lock = threading.Lock()

        @tool(parallel_safe=False)
        def serial_probe(label: str) -> str:
            """Record whether serial calls overlap."""

            nonlocal active, max_active
            with lock:
                active += 1
                max_active = max(max_active, active)
            threading.Event().wait(0.02)
            with lock:
                active -= 1
            return label

        tools = {parallel_probe.name: parallel_probe, serial_probe.name: serial_probe}
        parallel_results = run_tool_calls(
            [
                ToolCall("parallel_probe", {"label": "a"}),
                ToolCall("parallel_probe", {"label": "b"}),
            ],
            tools,
        )
        serial_results = run_tool_calls(
            [
                ToolCall("serial_probe", {"label": "a"}),
                ToolCall("serial_probe", {"label": "b"}),
            ],
            tools,
        )
        self.assertEqual([item.content for item in parallel_results], ["a", "b"])
        self.assertEqual([item.content for item in serial_results], ["a", "b"])
        self.assertEqual(max_active, 1)


class HarnessTests(unittest.TestCase):
    def test_run_emits_events_and_persists_session(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            cfg = HarnessConfig(
                model=FakeModel(["done"]),
                workspace=root,
                session_root=f"{root}/sessions",
                permission_mode="readonly",
                enable_bash=False,
            )
            harness = Harness(cfg)

            events = list(harness.run("hello"))

            self.assertEqual(events[0].type, ev.RUN_START)
            self.assertEqual(events[-1].type, ev.RUN_END)
            self.assertEqual(events[-1].data["final_text"], "done")
            self.assertTrue(harness.last_session.messages())
            harness.close()


if __name__ == "__main__":
    unittest.main()
