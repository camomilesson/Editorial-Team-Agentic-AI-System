"""Opaque workflow identifiers and request identity."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, NewType

from editorial_agent.contracts.common import (
    parse_utc_timestamp,
    require_non_blank,
    require_utc_timestamp,
    timestamp_to_json,
)

UserId = NewType("UserId", str)
SessionId = NewType("SessionId", str)
DocumentId = NewType("DocumentId", str)
DocumentVersionId = NewType("DocumentVersionId", str)
RunId = NewType("RunId", str)
EventId = NewType("EventId", str)
HandoffId = NewType("HandoffId", str)
CommentId = NewType("CommentId", str)
FactId = NewType("FactId", str)

_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")


def validate_identifier(value: str, field_name: str) -> str:
    """Reject missing, path-like, or traversal-capable identifiers."""

    value = require_non_blank(value, field_name)
    if not _ID_PATTERN.fullmatch(value) or ".." in value:
        raise ValueError(
            f"{field_name} must be an opaque identifier without path syntax"
        )
    return value


@dataclass(frozen=True)
class WorkflowRequestContext:
    """Identity and request data required for every future workflow run."""

    run_id: RunId
    user_id: UserId
    session_id: SessionId
    document_id: DocumentId
    request: str
    requested_at: datetime

    def __post_init__(self) -> None:
        validate_identifier(self.run_id, "run_id")
        validate_identifier(self.user_id, "user_id")
        validate_identifier(self.session_id, "session_id")
        validate_identifier(self.document_id, "document_id")
        require_non_blank(self.request, "request")
        require_utc_timestamp(self.requested_at, "requested_at")

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-compatible representation."""

        return {
            "run_id": self.run_id,
            "user_id": self.user_id,
            "session_id": self.session_id,
            "document_id": self.document_id,
            "request": self.request,
            "requested_at": timestamp_to_json(self.requested_at),
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> WorkflowRequestContext:
        """Validate and deserialize a request context."""

        return cls(
            run_id=RunId(value["run_id"]),
            user_id=UserId(value["user_id"]),
            session_id=SessionId(value["session_id"]),
            document_id=DocumentId(value["document_id"]),
            request=value["request"],
            requested_at=parse_utc_timestamp(value["requested_at"], "requested_at"),
        )
