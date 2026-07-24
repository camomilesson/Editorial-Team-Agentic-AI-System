"""Core observe-reason-act-verify agent loop."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol

from editorial_agent.approval import ApprovalGate
from editorial_agent.models import (
    ModelClient,
    ModelClientError,
    ModelRequest,
    ToolCall,
    ToolResult,
    ToolSchema,
)


class StopReason(StrEnum):
    """Why an agent run ended."""

    ANSWERED = "answered"
    MAX_STEPS = "max_steps"
    MODEL_ERROR = "model_error"


@dataclass(frozen=True)
class TraceEvent:
    """One observable event from an agent run."""

    step: int
    kind: str
    payload: dict[str, Any]


@dataclass(frozen=True)
class AgentResult:
    """Final result of one agent run."""

    text: str
    stop_reason: StopReason
    steps: int
    trace: tuple[TraceEvent, ...]


class ToolExecutor(Protocol):
    """Validate and execute normalized model tool calls."""

    def execute(self, tool_call: ToolCall) -> Any:
        """Execute one tool call and return its result."""
        ...

    def requires_approval(self, tool_name: str) -> bool:
        """Return whether a tool requires explicit human approval."""
        ...


class AgentRunner:
    """Run a model until it answers or a stopping condition fires."""

    def __init__(
        self,
        *,
        model: ModelClient,
        executor: ToolExecutor,
        approval_gate: ApprovalGate | None = None,
        max_steps: int = 8,
    ) -> None:
        if max_steps < 1:
            raise ValueError("max_steps must be positive")

        self._model = model
        self._executor = executor
        self._approval_gate = approval_gate
        self._max_steps = max_steps

    def run(
        self,
        user_input: str,
        tools: tuple[ToolSchema, ...] = (),
    ) -> AgentResult:
        """Run the observe-reason-act-verify loop."""

        if not user_input.strip():
            raise ValueError("user_input must not be empty")

        request = ModelRequest(
            input=user_input,
            tools=tools,
        )
        trace: list[TraceEvent] = []

        for step in range(1, self._max_steps + 1):
            try:
                response = self._model.respond(request)
            except ModelClientError as exc:
                trace.append(
                    TraceEvent(
                        step=step,
                        kind="model_error",
                        payload={
                            "type": type(exc).__name__,
                            "message": str(exc),
                        },
                    )
                )
                self._record_stop(
                    trace=trace,
                    step=step,
                    reason=StopReason.MODEL_ERROR,
                )

                return AgentResult(
                    text="",
                    stop_reason=StopReason.MODEL_ERROR,
                    steps=step,
                    trace=tuple(trace),
                )

            trace.append(
                TraceEvent(
                    step=step,
                    kind="model_response",
                    payload={
                        "text": response.text,
                        "tool_call_count": len(response.tool_calls),
                    },
                )
            )

            if not response.tool_calls:
                self._record_stop(
                    trace=trace,
                    step=step,
                    reason=StopReason.ANSWERED,
                )

                return AgentResult(
                    text=response.text,
                    stop_reason=StopReason.ANSWERED,
                    steps=step,
                    trace=tuple(trace),
                )

            tool_results: list[ToolResult] = []

            for tool_call in response.tool_calls:
                trace.append(
                    TraceEvent(
                        step=step,
                        kind="tool_request",
                        payload={
                            "call_id": tool_call.call_id,
                            "name": tool_call.name,
                            "arguments": tool_call.arguments,
                        },
                    )
                )

                approval_result = self._request_approval(
                    tool_call=tool_call,
                    step=step,
                    trace=trace,
                )

                if approval_result is not None:
                    self._record_tool_result(
                        tool_call=tool_call,
                        result=approval_result,
                        step=step,
                        trace=trace,
                    )
                    tool_results.append(
                        ToolResult(
                            call_id=tool_call.call_id,
                            name=tool_call.name,
                            result=approval_result,
                        )
                    )
                    continue

                try:
                    result = self._executor.execute(tool_call)
                except Exception as exc:
                    result = {
                        "ok": False,
                        "error": {
                            "type": "tool_execution_failed",
                            "message": str(exc),
                        },
                    }

                    trace.append(
                        TraceEvent(
                            step=step,
                            kind="tool_error",
                            payload={
                                "call_id": tool_call.call_id,
                                "name": tool_call.name,
                                "error": result["error"],
                            },
                        )
                    )
                else:
                    self._record_tool_result(
                        tool_call=tool_call,
                        result=result,
                        step=step,
                        trace=trace,
                    )

                tool_results.append(
                    ToolResult(
                        call_id=tool_call.call_id,
                        name=tool_call.name,
                        result=result,
                    )
                )

            request = ModelRequest(
                input=tuple(tool_results),
                tools=tools,
                continuation_token=response.continuation_token,
            )

        self._record_stop(
            trace=trace,
            step=self._max_steps,
            reason=StopReason.MAX_STEPS,
        )

        return AgentResult(
            text="",
            stop_reason=StopReason.MAX_STEPS,
            steps=self._max_steps,
            trace=tuple(trace),
        )

    def _request_approval(
        self,
        *,
        tool_call: ToolCall,
        step: int,
        trace: list[TraceEvent],
    ) -> dict[str, Any] | None:
        """Return an error result when a gated action is not approved."""

        if not self._executor.requires_approval(tool_call.name):
            return None

        trace.append(
            TraceEvent(
                step=step,
                kind="approval_requested",
                payload={
                    "call_id": tool_call.call_id,
                    "name": tool_call.name,
                    "arguments": tool_call.arguments,
                },
            )
        )

        if self._approval_gate is None:
            trace.append(
                TraceEvent(
                    step=step,
                    kind="approval_declined",
                    payload={
                        "call_id": tool_call.call_id,
                        "name": tool_call.name,
                        "reason": "no_approval_gate",
                    },
                )
            )

            return {
                "ok": False,
                "error": {
                    "type": "approval_required",
                    "message": (
                        f"Tool {tool_call.name} requires explicit "
                        "human approval."
                    ),
                },
            }

        approved = self._approval_gate.request(tool_call)

        if not approved:
            trace.append(
                TraceEvent(
                    step=step,
                    kind="approval_declined",
                    payload={
                        "call_id": tool_call.call_id,
                        "name": tool_call.name,
                        "reason": "declined_by_user",
                    },
                )
            )

            return {
                "ok": False,
                "error": {
                    "type": "declined_by_user",
                    "message": (
                        f"The user declined tool {tool_call.name}."
                    ),
                },
            }

        trace.append(
            TraceEvent(
                step=step,
                kind="approval_granted",
                payload={
                    "call_id": tool_call.call_id,
                    "name": tool_call.name,
                },
            )
        )

        return None

    @staticmethod
    def _record_tool_result(
        *,
        tool_call: ToolCall,
        result: Any,
        step: int,
        trace: list[TraceEvent],
    ) -> None:
        """Record a normal tool result in the execution trace."""

        trace.append(
            TraceEvent(
                step=step,
                kind="tool_result",
                payload={
                    "call_id": tool_call.call_id,
                    "name": tool_call.name,
                    "result": result,
                },
            )
        )

    @staticmethod
    def _record_stop(
        *,
        trace: list[TraceEvent],
        step: int,
        reason: StopReason,
    ) -> None:
        """Record why the agent run stopped."""

        trace.append(
            TraceEvent(
                step=step,
                kind="run_stopped",
                payload={
                    "reason": reason,
                },
            )
        )