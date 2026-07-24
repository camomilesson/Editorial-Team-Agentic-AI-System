"""Provider-independent model contracts."""

from __future__ import annotations

from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, Protocol, TypeAlias

ToolSchema: TypeAlias = dict[str, Any]


class ModelClientError(RuntimeError):
    """Raised when a model client cannot produce a valid response."""


@dataclass(frozen=True)
class ToolCall:
    """A normalized tool request made by a model."""

    call_id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class ToolResult:
    """A tool result to send back to the model."""

    call_id: str
    name: str
    result: Any


ModelInput: TypeAlias = str | tuple[ToolResult, ...]


@dataclass(frozen=True)
class ModelRequest:
    """One request sent by the agent loop to a model."""

    input: ModelInput
    tools: tuple[ToolSchema, ...] = ()
    continuation_token: str | None = None


@dataclass(frozen=True)
class ModelResponse:
    """A normalized response returned by a model."""

    text: str
    tool_calls: tuple[ToolCall, ...]
    continuation_token: str | None


class ModelClient(Protocol):
    """Interface used by the future agent loop."""

    def respond(self, request: ModelRequest) -> ModelResponse:
        """Return one normalized model response."""
        ...


class FakeModelClient:
    """Return scripted responses for deterministic tests."""

    def __init__(self, responses: Iterable[ModelResponse]) -> None:
        self._responses = deque(responses)
        self.requests: list[ModelRequest] = []

    def respond(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request)

        if not self._responses:
            raise ModelClientError("Fake model has no scripted responses left")

        return self._responses.popleft()