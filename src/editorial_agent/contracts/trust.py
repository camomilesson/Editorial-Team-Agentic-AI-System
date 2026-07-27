"""Trust classifications for rules, memory, and shared editorial data."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any

from editorial_agent.contracts.common import (
    parse_utc_timestamp,
    require_non_blank,
    require_utc_timestamp,
    timestamp_to_json,
)
from editorial_agent.contracts.identity import (
    CommentId,
    DocumentId,
    UserId,
    validate_identifier,
)


class TrustClassification(StrEnum):
    """Application-assigned trust of context content."""

    UNTRUSTED_SHARED_CONTENT = "untrusted_shared_content"
    TRUSTED_OPERATING_RULE = "trusted_operating_rule"
    PRIVATE_USER_FACT = "private_user_fact"
    SYSTEM_GENERATED_RECORD = "system_generated_record"


@dataclass(frozen=True, init=False)
class SharedComment:
    """A shared comment whose body is always untrusted data."""

    comment_id: CommentId
    document_id: DocumentId
    author_user_id: UserId
    body: str
    trust: TrustClassification
    created_at: datetime

    def __init__(
        self,
        *,
        comment_id: CommentId,
        document_id: DocumentId,
        author_user_id: UserId,
        body: str,
        created_at: datetime,
    ) -> None:
        validate_identifier(comment_id, "comment_id")
        validate_identifier(document_id, "document_id")
        validate_identifier(author_user_id, "author_user_id")
        require_non_blank(body, "body")
        require_utc_timestamp(created_at, "created_at")
        object.__setattr__(self, "comment_id", comment_id)
        object.__setattr__(self, "document_id", document_id)
        object.__setattr__(self, "author_user_id", author_user_id)
        object.__setattr__(self, "body", body)
        object.__setattr__(
            self,
            "trust",
            TrustClassification.UNTRUSTED_SHARED_CONTENT,
        )
        object.__setattr__(self, "created_at", created_at)

    def to_dict(self) -> dict[str, Any]:
        """Return comment data; body remains data rather than instructions."""

        return {
            "comment_id": self.comment_id,
            "document_id": self.document_id,
            "author_user_id": self.author_user_id,
            "body": self.body,
            "trust": self.trust.value,
            "created_at": timestamp_to_json(self.created_at),
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> SharedComment:
        """Deserialize only an application-classified shared comment."""

        supplied_trust = value.get(
            "trust",
            TrustClassification.UNTRUSTED_SHARED_CONTENT.value,
        )
        if supplied_trust != TrustClassification.UNTRUSTED_SHARED_CONTENT.value:
            raise ValueError("shared comments cannot claim a trusted classification")
        return cls(
            comment_id=CommentId(value["comment_id"]),
            document_id=DocumentId(value["document_id"]),
            author_user_id=UserId(value["author_user_id"]),
            body=value["body"],
            created_at=parse_utc_timestamp(value["created_at"], "created_at"),
        )
