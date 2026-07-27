"""Provider-neutral role agents with tool turns and strict final parsing."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from editorial_agent.contracts.workflow import AgentOutcome, AgentRole
from editorial_agent.models import (
    ModelClient,
    ModelClientError,
    ModelRequest,
    ToolCall,
    ToolResult,
)
from editorial_agent.registry import ToolRegistry
from editorial_agent.role_results import (
    RoleOutputError,
    parse_critic_outcome,
    parse_executor_outcome,
)

ToolCallback = Callable[[AgentRole, ToolCall, dict[str, object] | None], None]
ModelTurnCallback = Callable[[AgentRole, int, int], None]


class RoleAgentError(RuntimeError):
    """A role cannot produce a valid structured outcome."""

    def __init__(self, message: str, *, code: str = "structured_output") -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class RoleAgent:
    """Run one explicit role with its own model, tools, and parser."""

    role: AgentRole
    model: ModelClient
    tools: ToolRegistry
    max_steps: int = 6
    required_tools: frozenset[str] = frozenset()

    def run(
        self,
        prompt: str,
        *,
        on_tool_requested: ToolCallback | None = None,
        on_tool_completed: ToolCallback | None = None,
        on_model_turn: ModelTurnCallback | None = None,
    ) -> AgentOutcome:
        """Run tool turns until strict structured JSON is returned."""

        if self.role not in {AgentRole.EXECUTOR, AgentRole.CRITIC}:
            raise ValueError("RoleAgent supports only Executor or Critic")
        request = ModelRequest(input=prompt, tools=self.tools.schemas)
        used_tools: set[str] = set()
        for step in range(1, self.max_steps + 1):
            try:
                response = self.model.respond(request)
            except ModelClientError as exc:
                raise RoleAgentError(
                    "Model could not produce a role response.",
                    code="model_request",
                ) from exc
            if on_model_turn is not None:
                on_model_turn(self.role, step, len(response.tool_calls))
            if not response.tool_calls:
                if self.required_tools - used_tools:
                    raise RoleAgentError(
                        "Role completed before required retrieval.",
                        code="required_tool_missing",
                    )
                try:
                    if self.role is AgentRole.EXECUTOR:
                        return parse_executor_outcome(response.text)
                    return parse_critic_outcome(response.text)
                except RoleOutputError as exc:
                    raise RoleAgentError(
                        "Model returned invalid structured output.",
                        code="structured_output",
                    ) from exc

            results: list[ToolResult] = []
            for tool_call in response.tool_calls:
                used_tools.add(tool_call.name)
                if on_tool_requested is not None:
                    on_tool_requested(self.role, tool_call, None)
                try:
                    result = self.tools.execute(tool_call)
                except Exception as exc:
                    raise RoleAgentError(
                        "Role retrieval tool failed.",
                        code="retrieval",
                    ) from exc
                if on_tool_completed is not None:
                    on_tool_completed(self.role, tool_call, result)
                if result.get("ok") is not True:
                    raise RoleAgentError(
                        "Role retrieval tool returned an error.",
                        code="retrieval",
                    )
                results.append(
                    ToolResult(
                        call_id=tool_call.call_id,
                        name=tool_call.name,
                        result=result,
                    )
                )
            request = ModelRequest(
                input=tuple(results),
                tools=self.tools.schemas,
                continuation_token=response.continuation_token,
            )
        raise RoleAgentError(
            "Role exceeded its maximum model-step budget.",
            code="tool_selection",
        )
