"""Append-only structured agent handoff records."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from editorial_agent.contracts.common import (
    parse_utc_timestamp,
    require_json_object,
    require_non_blank,
    require_utc_timestamp,
    timestamp_to_json,
)
from editorial_agent.contracts.identity import (
    DocumentVersionId,
    HandoffId,
    RunId,
    validate_identifier,
)
from editorial_agent.contracts.workflow import AgentRole, OutcomeStatus

HANDOFF_SCHEMA_VERSION = "1"
_LIVE_HANDOFF_ROLES = {
    AgentRole.ORCHESTRATOR,
    AgentRole.EXECUTOR,
    AgentRole.CRITIC,
    AgentRole.HUMAN,
    AgentRole.TOOL,
}


@dataclass(frozen=True)
class AgentHandoff:
    """One immutable, append-only live-workflow handoff."""

    handoff_id: HandoffId
    run_id: RunId
    sequence: int
    round_number: int
    from_agent: AgentRole
    to_agent: AgentRole
    status: OutcomeStatus
    payload: dict[str, Any]
    created_at: datetime
    document_version_id: DocumentVersionId | None = None
    schema_version: str = HANDOFF_SCHEMA_VERSION

    def __post_init__(self) -> None:
        validate_identifier(self.handoff_id, "handoff_id")
        validate_identifier(self.run_id, "run_id")
        if self.document_version_id is not None:
            validate_identifier(self.document_version_id, "document_version_id")
        if isinstance(self.sequence, bool) or self.sequence < 1:
            raise ValueError("sequence must be a positive integer")
        if isinstance(self.round_number, bool) or self.round_number < 0:
            raise ValueError("round_number must be a non-negative integer")
        if self.from_agent == self.to_agent:
            raise ValueError("handoff sender and receiver must differ")
        if self.from_agent not in _LIVE_HANDOFF_ROLES:
            raise ValueError(f"{self.from_agent.value} cannot send live handoffs")
        if self.to_agent not in _LIVE_HANDOFF_ROLES:
            raise ValueError(f"{self.to_agent.value} cannot receive live handoffs")
        require_json_object(self.payload, "payload")
        require_utc_timestamp(self.created_at, "created_at")
        require_non_blank(self.schema_version, "schema_version")

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-compatible record."""

        return {
            "schema_version": self.schema_version,
            "handoff_id": self.handoff_id,
            "run_id": self.run_id,
            "sequence": self.sequence,
            "round_number": self.round_number,
            "from_agent": self.from_agent.value,
            "to_agent": self.to_agent.value,
            "status": self.status.value,
            "payload": self.payload,
            "document_version_id": self.document_version_id,
            "created_at": timestamp_to_json(self.created_at),
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> AgentHandoff:
        """Validate and deserialize one handoff."""

        return cls(
            schema_version=value["schema_version"],
            handoff_id=HandoffId(value["handoff_id"]),
            run_id=RunId(value["run_id"]),
            sequence=value["sequence"],
            round_number=value["round_number"],
            from_agent=AgentRole(value["from_agent"]),
            to_agent=AgentRole(value["to_agent"]),
            status=OutcomeStatus(value["status"]),
            payload=value["payload"],
            document_version_id=(
                DocumentVersionId(value["document_version_id"])
                if value.get("document_version_id") is not None
                else None
            ),
            created_at=parse_utc_timestamp(value["created_at"], "created_at"),
        )


def validate_handoff_order(
    handoffs: tuple[AgentHandoff, ...],
    run_id: RunId,
) -> None:
    """Require deterministic, contiguous ordering for one run."""

    expected = list(range(1, len(handoffs) + 1))
    actual = [handoff.sequence for handoff in handoffs]
    if actual != expected:
        raise ValueError("handoffs must be ordered with contiguous sequence numbers")
    if any(handoff.run_id != run_id for handoff in handoffs):
        raise ValueError("all handoffs must belong to the bundle run")
