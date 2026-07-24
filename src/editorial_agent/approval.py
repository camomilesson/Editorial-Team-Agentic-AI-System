"""Human approval gates for irreversible tool calls."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from editorial_agent.models import ToolCall


class ApprovalGate(Protocol):
    """Request explicit human approval for one tool call."""

    def request(self, tool_call: ToolCall) -> bool:
        """Return true only when the user explicitly approves."""
        ...


@dataclass
class TerminalApprovalGate:
    """Ask for explicit approval through the terminal."""

    input_func: Callable[[str], str] = input
    output_func: Callable[[str], None] = print

    def request(self, tool_call: ToolCall) -> bool:
        """Approve only when the user types exactly YES."""

        arguments = json.dumps(
            tool_call.arguments,
            indent=2,
            ensure_ascii=False,
            sort_keys=True,
        )

        self.output_func("")
        self.output_func("Approval required for irreversible action:")
        self.output_func(f"Tool: {tool_call.name}")
        self.output_func("Arguments:")
        self.output_func(arguments)

        response = self.input_func(
            "Type YES to approve: "
        )

        return response == "YES"


class AlwaysApproveGate:
    """Approve every gated action in deterministic tests."""

    def request(self, tool_call: ToolCall) -> bool:
        del tool_call
        return True


class AlwaysDeclineGate:
    """Decline every gated action in deterministic tests."""

    def request(self, tool_call: ToolCall) -> bool:
        del tool_call
        return False
