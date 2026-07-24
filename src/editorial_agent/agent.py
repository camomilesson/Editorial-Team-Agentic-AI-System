"""Core observe-reason-act-verify agent loop."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol

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
    """Executes normalized model tool calls."""

    def execute(self, tool_call: ToolCall) -> Any:
        """Execute one tool call and return its result."""
        ...


class AgentRunner:
    """Run a model until it answers or a stopping condition fires."""

    def __init__(
        self,
        *,
        model: ModelClient,
        executor: ToolExecutor,
        max_steps: int = 8,
    ) -> None:
        if max_steps < 1:
            raise ValueError("max_steps must be positive")

        self._model = model
        self._executor = executor
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
                trace.append(
                    TraceEvent(
                        step=step,
                        kind="run_stopped",
                        payload={"reason": StopReason.MODEL_ERROR},
                    )
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
                trace.append(
                    TraceEvent(
                        step=step,
                        kind="run_stopped",
                        payload={"reason": StopReason.ANSWERED},
                    )
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

        trace.append(
            TraceEvent(
                step=self._max_steps,
                kind="run_stopped",
                payload={"reason": StopReason.MAX_STEPS},
            )
        )
        return AgentResult(
            text="",
            stop_reason=StopReason.MAX_STEPS,
            steps=self._max_steps,
            trace=tuple(trace),
        )
