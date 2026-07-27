"""Persistent, provider-neutral run event envelope."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
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
    EventId,
    RunId,
    validate_identifier,
)
from editorial_agent.contracts.workflow import AgentRole

EVENT_SCHEMA_VERSION = "1"


class EventType(StrEnum):
    """Initial closed event vocabulary for reconstructing workflow runs."""

    RUN_STARTED = "run_started"
    CONTEXT_ATTACHED = "context_attached"
    MEMORY_RETRIEVAL_REQUESTED = "memory_retrieval_requested"
    MEMORY_RETRIEVAL_COMPLETED = "memory_retrieval_completed"
    SHARED_COMMENTS_RETRIEVED = "shared_comments_retrieved"
    MODEL_TURN_COMPLETED = "model_turn_completed"
    TOOL_REQUESTED = "tool_requested"
    TOOL_COMPLETED = "tool_completed"
    APPROVAL_REQUESTED = "approval_requested"
    APPROVAL_RESOLVED = "approval_resolved"
    DOCUMENT_VERSION_CREATED = "document_version_created"
    HANDOFF_CREATED = "handoff_created"
    REVISION_REQUESTED = "revision_requested"
    RUN_COMPLETED = "run_completed"
    RUN_BLOCKED = "run_blocked"
    RUN_FAILED = "run_failed"


@dataclass(frozen=True)
class RunEvent:
    """One immutable event in an append-only run history.

    Payload redaction and content policy are deliberately deferred. Callers
    must not place secrets or unnecessary private content in this envelope.
    """

    event_id: EventId
    run_id: RunId
    sequence: int
    timestamp: datetime
    actor: AgentRole
    event_type: EventType
    payload: dict[str, Any]
    document_version_id: DocumentVersionId | None = None
    schema_version: str = EVENT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        validate_identifier(self.event_id, "event_id")
        validate_identifier(self.run_id, "run_id")
        if self.document_version_id is not None:
            validate_identifier(self.document_version_id, "document_version_id")
        if isinstance(self.sequence, bool) or self.sequence < 1:
            raise ValueError("sequence must be a positive integer")
        require_utc_timestamp(self.timestamp, "timestamp")
        require_non_blank(self.schema_version, "schema_version")
        require_json_object(self.payload, "payload")

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-compatible event."""

        return {
            "schema_version": self.schema_version,
            "event_id": self.event_id,
            "run_id": self.run_id,
            "sequence": self.sequence,
            "timestamp": timestamp_to_json(self.timestamp),
            "actor": self.actor.value,
            "event_type": self.event_type.value,
            "payload": self.payload,
            "document_version_id": self.document_version_id,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> RunEvent:
        """Validate and deserialize one event."""

        return cls(
            schema_version=value["schema_version"],
            event_id=EventId(value["event_id"]),
            run_id=RunId(value["run_id"]),
            sequence=value["sequence"],
            timestamp=parse_utc_timestamp(value["timestamp"], "timestamp"),
            actor=AgentRole(value["actor"]),
            event_type=EventType(value["event_type"]),
            payload=value["payload"],
            document_version_id=(
                DocumentVersionId(value["document_version_id"])
                if value.get("document_version_id") is not None
                else None
            ),
        )


def validate_event_order(events: tuple[RunEvent, ...], run_id: RunId) -> None:
    """Require deterministic, contiguous ordering for one run."""

    expected = list(range(1, len(events) + 1))
    actual = [event.sequence for event in events]
    if actual != expected:
        raise ValueError("events must be ordered with contiguous sequence numbers")
    if any(event.run_id != run_id for event in events):
        raise ValueError("all events must belong to the bundle run")
