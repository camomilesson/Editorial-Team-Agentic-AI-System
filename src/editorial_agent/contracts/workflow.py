"""Structured outcomes, roles, run states, and transition validation."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from editorial_agent.contracts.common import require_json_object, require_non_blank

DEFAULT_MAX_CRITIC_REVISIONS = 2


class AgentRole(StrEnum):
    """Actors that may appear in workflow records."""

    EXECUTOR = "executor"
    CRITIC = "critic"
    MONITOR = "monitor"
    ORCHESTRATOR = "orchestrator"
    HUMAN = "human"
    TOOL = "tool"


class OutcomeStatus(StrEnum):
    """Control status shared by Executor and Critic outcomes."""

    COMPLETE = "complete"
    REVISE = "revise"
    BLOCKED = "blocked"
    ERROR = "error"


class RunStatus(StrEnum):
    """Persisted workflow-run lifecycle."""

    PENDING = "pending"
    RUNNING = "running"
    AWAITING_APPROVAL = "awaiting_approval"
    COMPLETED = "completed"
    BLOCKED = "blocked"
    FAILED = "failed"

    @property
    def is_terminal(self) -> bool:
        """Return whether no live workflow work remains."""

        return self in {self.COMPLETED, self.BLOCKED, self.FAILED}


@dataclass(frozen=True)
class RevisionFeedback:
    """Structured changes requested by the Critic."""

    summary: str
    required_changes: tuple[str, ...]

    def __post_init__(self) -> None:
        require_non_blank(self.summary, "revision.summary")
        if not self.required_changes:
            raise ValueError("revision.required_changes must not be empty")
        for change in self.required_changes:
            require_non_blank(change, "revision.required_changes item")

    def to_dict(self) -> dict[str, Any]:
        return {
            "summary": self.summary,
            "required_changes": list(self.required_changes),
        }


@dataclass(frozen=True)
class BlockedReason:
    """Sanitized explanation of why progress cannot continue."""

    code: str
    message: str

    def __post_init__(self) -> None:
        require_non_blank(self.code, "blocked.code")
        require_non_blank(self.message, "blocked.message")

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message}


@dataclass(frozen=True)
class SanitizedError:
    """Provider-neutral error safe for persistence and model context."""

    code: str
    message: str
    retryable: bool = False

    def __post_init__(self) -> None:
        require_non_blank(self.code, "error.code")
        require_non_blank(self.message, "error.message")

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "retryable": self.retryable,
        }


@dataclass(frozen=True)
class PendingApproval:
    """Description of an action paused for a human decision."""

    action: str
    summary: str

    def __post_init__(self) -> None:
        require_non_blank(self.action, "approval.action")
        require_non_blank(self.summary, "approval.summary")

    def to_dict(self) -> dict[str, str]:
        return {"action": self.action, "summary": self.summary}


@dataclass(frozen=True)
class AgentOutcome:
    """Stable control envelope exchanged by Executor and Critic."""

    status: OutcomeStatus
    result: dict[str, Any] | None = None
    needs_approval: bool = False
    approval: PendingApproval | None = None
    revision: RevisionFeedback | None = None
    blocked: BlockedReason | None = None
    error: SanitizedError | None = None

    def __post_init__(self) -> None:
        if self.result is not None:
            require_json_object(self.result, "result")
        if self.status is OutcomeStatus.COMPLETE:
            if not self.result:
                raise ValueError("complete outcomes require a usable result")
        elif self.status is OutcomeStatus.REVISE:
            if self.revision is None:
                raise ValueError("revise outcomes require revision feedback")
        elif self.status is OutcomeStatus.BLOCKED:
            if self.blocked is None:
                raise ValueError("blocked outcomes require a blocked reason")
        elif self.status is OutcomeStatus.ERROR:
            if self.error is None:
                raise ValueError("error outcomes require a sanitized error")

        if self.needs_approval != (self.approval is not None):
            raise ValueError(
                "needs_approval must exactly match the presence of approval details"
            )
        if self.status is not OutcomeStatus.ERROR and self.error is not None:
            raise ValueError("only error outcomes may include an error")
        if self.status is not OutcomeStatus.REVISE and self.revision is not None:
            raise ValueError("only revise outcomes may include revision feedback")
        if self.status is not OutcomeStatus.BLOCKED and self.blocked is not None:
            raise ValueError("only blocked outcomes may include a blocked reason")

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-compatible control envelope."""

        return {
            "status": self.status.value,
            "result": self.result,
            "needs_approval": self.needs_approval,
            "approval": self.approval.to_dict() if self.approval else None,
            "revision": self.revision.to_dict() if self.revision else None,
            "blocked": self.blocked.to_dict() if self.blocked else None,
            "error": self.error.to_dict() if self.error else None,
        }


class TransitionAction(StrEnum):
    """High-level result of one validated workflow transition."""

    DISPATCH_EXECUTOR = "dispatch_executor"
    DISPATCH_CRITIC = "dispatch_critic"
    COMPLETE_WORKFLOW = "complete_workflow"
    PAUSE_FOR_APPROVAL = "pause_for_approval"
    BLOCK_WORKFLOW = "block_workflow"
    FAIL_WORKFLOW = "fail_workflow"


def validate_transition(
    *,
    actor: AgentRole,
    outcome: AgentOutcome,
    critic_revisions_used: int,
    max_critic_revisions: int = DEFAULT_MAX_CRITIC_REVISIONS,
) -> TransitionAction:
    """Validate one explicit Executor–Critic transition."""

    if critic_revisions_used < 0:
        raise ValueError("critic_revisions_used must not be negative")
    if max_critic_revisions < 0:
        raise ValueError("max_critic_revisions must not be negative")
    if actor not in {AgentRole.ORCHESTRATOR, AgentRole.EXECUTOR, AgentRole.CRITIC}:
        raise ValueError(f"{actor.value} cannot drive the live workflow")
    if outcome.needs_approval:
        return TransitionAction.PAUSE_FOR_APPROVAL
    if outcome.status is OutcomeStatus.ERROR:
        return TransitionAction.FAIL_WORKFLOW
    if outcome.status is OutcomeStatus.BLOCKED:
        return TransitionAction.BLOCK_WORKFLOW
    if actor is AgentRole.ORCHESTRATOR:
        if outcome.status is not OutcomeStatus.COMPLETE:
            raise ValueError("orchestrator dispatch requires a complete setup outcome")
        return TransitionAction.DISPATCH_EXECUTOR
    if actor is AgentRole.EXECUTOR:
        if outcome.status is not OutcomeStatus.COMPLETE:
            raise ValueError("Executor may hand off only a complete result")
        return TransitionAction.DISPATCH_CRITIC
    if outcome.status is OutcomeStatus.COMPLETE:
        return TransitionAction.COMPLETE_WORKFLOW
    if outcome.status is OutcomeStatus.REVISE:
        if critic_revisions_used >= max_critic_revisions:
            return TransitionAction.BLOCK_WORKFLOW
        return TransitionAction.DISPATCH_EXECUTOR
    raise ValueError("unsupported workflow transition")
