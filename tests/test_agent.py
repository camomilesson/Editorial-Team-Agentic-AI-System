from typing import Any

import pytest

from editorial_agent.agent import AgentRunner, StopReason
from editorial_agent.approval import (
    AlwaysApproveGate,
    AlwaysDeclineGate,
)
from editorial_agent.models import (
    FakeModelClient,
    ModelRequest,
    ModelResponse,
    ToolCall,
    ToolResult,
)


class RecordingExecutor:
    def __init__(
        self,
        *,
        results: dict[str, Any] | None = None,
        failures: dict[str, Exception] | None = None,
        approval_required: set[str] | None = None,
    ) -> None:
        self.results = results or {}
        self.failures = failures or {}
        self.approval_required = approval_required or set()
        self.calls: list[ToolCall] = []

    def execute(self, tool_call: ToolCall) -> Any:
        self.calls.append(tool_call)

        if tool_call.name in self.failures:
            raise self.failures[tool_call.name]

        return self.results.get(tool_call.name)

    def requires_approval(self, tool_name: str) -> bool:
        return tool_name in self.approval_required


def test_agent_stops_when_model_answers() -> None:
    model = FakeModelClient(
        [
            ModelResponse(
                text="Final answer.",
                tool_calls=(),
                continuation_token="interaction-1",
            )
        ]
    )
    executor = RecordingExecutor()
    runner = AgentRunner(
        model=model,
        executor=executor,
    )

    result = runner.run("Hello")

    assert result.text == "Final answer."
    assert result.stop_reason == StopReason.ANSWERED
    assert result.steps == 1
    assert executor.calls == []
    assert result.trace[-1].kind == "run_stopped"
    assert result.trace[-1].payload == {"reason": StopReason.ANSWERED}


def test_agent_executes_tool_and_returns_result_to_model() -> None:
    tool_call = ToolCall(
        call_id="call-1",
        name="echo_text",
        arguments={"text": "hello"},
    )
    model = FakeModelClient(
        [
            ModelResponse(
                text="",
                tool_calls=(tool_call,),
                continuation_token="interaction-1",
            ),
            ModelResponse(
                text="hello",
                tool_calls=(),
                continuation_token="interaction-2",
            ),
        ]
    )
    executor = RecordingExecutor(
        results={
            "echo_text": {
                "ok": True,
                "echo": "hello",
            }
        }
    )
    runner = AgentRunner(
        model=model,
        executor=executor,
    )

    result = runner.run("Echo hello")

    assert result.text == "hello"
    assert result.stop_reason == StopReason.ANSWERED
    assert result.steps == 2
    assert executor.calls == [tool_call]

    second_request = model.requests[1]

    assert second_request == ModelRequest(
        input=(
            ToolResult(
                call_id="call-1",
                name="echo_text",
                result={
                    "ok": True,
                    "echo": "hello",
                },
            ),
        ),
        tools=(),
        continuation_token="interaction-1",
    )


def test_agent_converts_tool_exception_into_observation() -> None:
    tool_call = ToolCall(
        call_id="call-1",
        name="broken_tool",
        arguments={},
    )
    model = FakeModelClient(
        [
            ModelResponse(
                text="",
                tool_calls=(tool_call,),
                continuation_token="interaction-1",
            ),
            ModelResponse(
                text="The tool failed.",
                tool_calls=(),
                continuation_token="interaction-2",
            ),
        ]
    )
    executor = RecordingExecutor(
        failures={
            "broken_tool": RuntimeError("disk unavailable"),
        }
    )
    runner = AgentRunner(
        model=model,
        executor=executor,
    )

    result = runner.run("Use the broken tool")

    assert result.text == "The tool failed."
    assert result.stop_reason == StopReason.ANSWERED

    second_request = model.requests[1]
    tool_result = second_request.input[0]

    assert isinstance(tool_result, ToolResult)
    assert tool_result.call_id == "call-1"
    assert tool_result.name == "broken_tool"
    assert tool_result.result == {
        "ok": False,
        "error": {
            "type": "tool_execution_failed",
            "message": "disk unavailable",
        },
    }

    assert any(
        event.kind == "tool_error"
        for event in result.trace
    )


def test_agent_handles_multiple_tool_calls_in_one_model_turn() -> None:
    first_call = ToolCall(
        call_id="call-1",
        name="first_tool",
        arguments={"value": 1},
    )
    second_call = ToolCall(
        call_id="call-2",
        name="second_tool",
        arguments={"value": 2},
    )
    model = FakeModelClient(
        [
            ModelResponse(
                text="",
                tool_calls=(first_call, second_call),
                continuation_token="interaction-1",
            ),
            ModelResponse(
                text="Both tools completed.",
                tool_calls=(),
                continuation_token="interaction-2",
            ),
        ]
    )
    executor = RecordingExecutor(
        results={
            "first_tool": {"ok": True, "value": 1},
            "second_tool": {"ok": True, "value": 2},
        }
    )
    runner = AgentRunner(model=model, executor=executor)

    result = runner.run("Run both tools")

    assert result.stop_reason == StopReason.ANSWERED
    assert executor.calls == [first_call, second_call]
    assert model.requests[1].input == (
        ToolResult(
            call_id="call-1",
            name="first_tool",
            result={"ok": True, "value": 1},
        ),
        ToolResult(
            call_id="call-2",
            name="second_tool",
            result={"ok": True, "value": 2},
        ),
    )
    assert model.requests[1].continuation_token == "interaction-1"


def test_agent_stops_at_max_steps() -> None:
    repeating_call = ToolCall(
        call_id="call-1",
        name="repeat_tool",
        arguments={},
    )
    model = FakeModelClient(
        [
            ModelResponse(
                text="",
                tool_calls=(repeating_call,),
                continuation_token="interaction-1",
            ),
            ModelResponse(
                text="",
                tool_calls=(repeating_call,),
                continuation_token="interaction-2",
            ),
        ]
    )
    executor = RecordingExecutor(
        results={
            "repeat_tool": {
                "ok": True,
            }
        }
    )
    runner = AgentRunner(
        model=model,
        executor=executor,
        max_steps=2,
    )

    result = runner.run("Keep going")

    assert result.text == ""
    assert result.stop_reason == StopReason.MAX_STEPS
    assert result.steps == 2
    assert len(model.requests) == 2
    assert len(executor.calls) == 2
    assert result.trace[-1].kind == "run_stopped"
    assert result.trace[-1].payload == {"reason": StopReason.MAX_STEPS}


def test_agent_stops_on_model_error() -> None:
    model = FakeModelClient([])
    executor = RecordingExecutor()
    runner = AgentRunner(
        model=model,
        executor=executor,
    )

    result = runner.run("Hello")

    assert result.text == ""
    assert result.stop_reason == StopReason.MODEL_ERROR
    assert result.steps == 1
    assert result.trace[-2].kind == "model_error"
    assert result.trace[-1].kind == "run_stopped"
    assert result.trace[-1].payload == {"reason": StopReason.MODEL_ERROR}


def test_agent_rejects_empty_user_input() -> None:
    model = FakeModelClient([])
    executor = RecordingExecutor()
    runner = AgentRunner(
        model=model,
        executor=executor,
    )

    with pytest.raises(
        ValueError,
        match="user_input must not be empty",
    ):
        runner.run("   ")


def test_agent_rejects_invalid_max_steps() -> None:
    model = FakeModelClient([])
    executor = RecordingExecutor()

    with pytest.raises(
        ValueError,
        match="max_steps must be positive",
    ):
        AgentRunner(
            model=model,
            executor=executor,
            max_steps=0,
        )


def test_approved_gated_tool_is_executed() -> None:
    tool_call = ToolCall(
        call_id="call-1",
        name="publish_linkedin_post",
        arguments={
            "project_id": "demo",
            "version": 1,
            "visibility": "public",
        },
    )

    model = FakeModelClient(
        (
            ModelResponse(
                text="",
                tool_calls=(tool_call,),
                continuation_token="interaction-1",
            ),
            ModelResponse(
                text="Published.",
                tool_calls=(),
                continuation_token="interaction-2",
            ),
        )
    )

    executor = RecordingExecutor(
        results={
            "publish_linkedin_post": {
                "ok": True,
                "data": {
                    "version": 1,
                },
            }
        },
        approval_required={
            "publish_linkedin_post",
        },
    )

    runner = AgentRunner(
        model=model,
        executor=executor,
        approval_gate=AlwaysApproveGate(),
    )

    result = runner.run("Publish it")

    assert result.text == "Published."
    assert executor.calls == [tool_call]
    assert model.requests[1].input == (
        ToolResult(
            call_id="call-1",
            name="publish_linkedin_post",
            result={
                "ok": True,
                "data": {
                    "version": 1,
                },
            },
        ),
    )
    trace_kinds = [event.kind for event in result.trace]
    assert "approval_requested" in trace_kinds
    assert "approval_granted" in trace_kinds
    assert "tool_result" in trace_kinds
    assert trace_kinds.index("approval_requested") < trace_kinds.index(
        "approval_granted"
    )
    assert trace_kinds.index("approval_granted") < trace_kinds.index(
        "tool_result"
    )


def test_declined_gated_tool_is_not_executed() -> None:
    tool_call = ToolCall(
        call_id="call-1",
        name="publish_linkedin_post",
        arguments={
            "project_id": "demo",
            "version": 1,
            "visibility": "public",
        },
    )

    model = FakeModelClient(
        (
            ModelResponse(
                text="",
                tool_calls=(tool_call,),
                continuation_token="interaction-1",
            ),
            ModelResponse(
                text="Publication was declined.",
                tool_calls=(),
                continuation_token="interaction-2",
            ),
        )
    )

    executor = RecordingExecutor(
        approval_required={
            "publish_linkedin_post",
        },
    )

    runner = AgentRunner(
        model=model,
        executor=executor,
        approval_gate=AlwaysDeclineGate(),
    )

    result = runner.run("Publish it")

    assert executor.calls == []
    assert result.text == "Publication was declined."

    second_request = model.requests[1]
    tool_result = second_request.input[0]

    assert tool_result.call_id == "call-1"
    assert tool_result.name == "publish_linkedin_post"
    assert tool_result.result["ok"] is False
    assert tool_result.result["error"]["type"] == (
        "declined_by_user"
    )
    trace_kinds = [event.kind for event in result.trace]
    assert "approval_requested" in trace_kinds
    assert "approval_declined" in trace_kinds
    assert "approval_granted" not in trace_kinds


def test_gated_tool_without_approval_gate_is_not_executed() -> None:
    tool_call = ToolCall(
        call_id="call-1",
        name="publish_linkedin_post",
        arguments={
            "project_id": "demo",
            "version": 1,
            "visibility": "public",
        },
    )
    model = FakeModelClient(
        (
            ModelResponse(
                text="",
                tool_calls=(tool_call,),
                continuation_token="interaction-1",
            ),
            ModelResponse(
                text="Approval is required.",
                tool_calls=(),
                continuation_token="interaction-2",
            ),
        )
    )
    executor = RecordingExecutor(
        approval_required={"publish_linkedin_post"},
    )
    runner = AgentRunner(
        model=model,
        executor=executor,
        approval_gate=None,
    )

    result = runner.run("Publish it")

    assert executor.calls == []
    assert model.requests[1].input == (
        ToolResult(
            call_id="call-1",
            name="publish_linkedin_post",
            result={
                "ok": False,
                "error": {
                    "type": "approval_required",
                    "message": (
                        "Tool publish_linkedin_post requires explicit "
                        "human approval."
                    ),
                },
            },
        ),
    )
    declined_event = next(
        event
        for event in result.trace
        if event.kind == "approval_declined"
    )
    assert declined_event.payload["reason"] == "no_approval_gate"


def test_reversible_tool_ignores_declining_approval_gate() -> None:
    tool_call = ToolCall(
        call_id="call-1",
        name="read_press_release",
        arguments={"project_id": "demo"},
    )
    model = FakeModelClient(
        (
            ModelResponse(
                text="",
                tool_calls=(tool_call,),
                continuation_token="interaction-1",
            ),
            ModelResponse(
                text="The release was read.",
                tool_calls=(),
                continuation_token="interaction-2",
            ),
        )
    )
    executor = RecordingExecutor(
        results={
            "read_press_release": {
                "ok": True,
                "data": {
                    "project_id": "demo",
                    "content": "Press release.",
                },
            },
        },
    )
    runner = AgentRunner(
        model=model,
        executor=executor,
        approval_gate=AlwaysDeclineGate(),
    )

    result = runner.run("Read the release")

    assert executor.calls == [tool_call]
    assert model.requests[1].input[0].result["ok"] is True
    assert not any(
        event.kind.startswith("approval_")
        for event in result.trace
    )
