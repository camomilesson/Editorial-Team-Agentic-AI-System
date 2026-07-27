"""Interfaces separating structured data, private facts, and trusted rules."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol

from editorial_agent.contracts.common import (
    parse_utc_timestamp,
    require_non_blank,
    require_utc_timestamp,
    timestamp_to_json,
)
from editorial_agent.contracts.events import RunEvent
from editorial_agent.contracts.handoffs import AgentHandoff
from editorial_agent.contracts.identity import (
    CommentId,
    DocumentId,
    DocumentVersionId,
    FactId,
    RunId,
    UserId,
    WorkflowRequestContext,
    validate_identifier,
)
from editorial_agent.contracts.trust import SharedComment, TrustClassification
from editorial_agent.contracts.workflow import AgentRole, RunStatus


class AccessLevel(StrEnum):
    """Document access levels constrained by the domain schema."""

    READ = "read"
    EDIT = "edit"
    OWNER = "owner"


@dataclass(frozen=True)
class UserRecord:
    """One structured user."""

    user_id: UserId
    display_name: str
    created_at: datetime

    def __post_init__(self) -> None:
        validate_identifier(self.user_id, "user_id")
        require_non_blank(self.display_name, "display_name")
        require_utc_timestamp(self.created_at, "created_at")


@dataclass(frozen=True)
class DocumentRecord:
    """One structured document."""

    document_id: DocumentId
    owner_user_id: UserId
    title: str
    created_at: datetime

    def __post_init__(self) -> None:
        validate_identifier(self.document_id, "document_id")
        validate_identifier(self.owner_user_id, "owner_user_id")
        require_non_blank(self.title, "title")
        require_utc_timestamp(self.created_at, "created_at")


@dataclass(frozen=True)
class DocumentVersionRecord:
    """One immutable structured document version."""

    document_version_id: DocumentVersionId
    document_id: DocumentId
    version_number: int
    content: str
    created_by_actor: AgentRole
    created_by_user_id: UserId | None
    run_id: RunId | None
    created_at: datetime

    def __post_init__(self) -> None:
        validate_identifier(self.document_version_id, "document_version_id")
        validate_identifier(self.document_id, "document_id")
        if isinstance(self.version_number, bool) or self.version_number < 1:
            raise ValueError("version_number must be a positive integer")
        require_non_blank(self.content, "content")
        if self.created_by_user_id is not None:
            validate_identifier(self.created_by_user_id, "created_by_user_id")
        if self.run_id is not None:
            validate_identifier(self.run_id, "run_id")
        require_utc_timestamp(self.created_at, "created_at")


@dataclass(frozen=True)
class PrivateFact:
    """One durable free-form fact scoped to exactly one user."""

    fact_id: FactId
    user_id: UserId
    content: str
    cue: str
    created_at: datetime
    source: str
    trust: TrustClassification = TrustClassification.PRIVATE_USER_FACT

    def __post_init__(self) -> None:
        validate_identifier(self.fact_id, "fact_id")
        validate_identifier(self.user_id, "user_id")
        require_non_blank(self.content, "content")
        require_non_blank(self.cue, "cue")
        require_non_blank(self.source, "source")
        require_utc_timestamp(self.created_at, "created_at")
        if self.trust is not TrustClassification.PRIVATE_USER_FACT:
            raise ValueError("private facts must use the private_user_fact trust label")

    def to_dict(self) -> dict[str, str]:
        """Return a JSON-compatible private fact."""

        return {
            "fact_id": self.fact_id,
            "user_id": self.user_id,
            "content": self.content,
            "cue": self.cue,
            "created_at": timestamp_to_json(self.created_at),
            "source": self.source,
            "trust": self.trust.value,
        }

    @classmethod
    def from_dict(cls, value: dict[str, str]) -> PrivateFact:
        """Validate a decoded private fact."""

        if value.get("trust") != TrustClassification.PRIVATE_USER_FACT.value:
            raise ValueError("private fact trust classification is invalid")
        return cls(
            fact_id=FactId(value["fact_id"]),
            user_id=UserId(value["user_id"]),
            content=value["content"],
            cue=value["cue"],
            created_at=parse_utc_timestamp(value["created_at"], "created_at"),
            source=value["source"],
        )


class RuleKind(StrEnum):
    """Trusted Markdown documents loaded as operating context."""

    GLOBAL_OPERATING_RULES = "global_operating_rules"
    EXECUTOR_DELEGATION_BRIEF = "executor_delegation_brief"
    CRITIC_DELEGATION_BRIEF = "critic_delegation_brief"
    MONITOR_RUBRIC = "monitor_rubric"


@dataclass(frozen=True)
class RuleDocument:
    """Trusted Markdown content with stable source metadata."""

    kind: RuleKind
    source_name: str
    version: str
    content: str
    trust: TrustClassification = TrustClassification.TRUSTED_OPERATING_RULE

    def __post_init__(self) -> None:
        require_non_blank(self.source_name, "source_name")
        require_non_blank(self.version, "version")
        require_non_blank(self.content, "content")
        if self.trust is not TrustClassification.TRUSTED_OPERATING_RULE:
            raise ValueError("rule documents must use the trusted rule label")

    def to_dict(self) -> dict[str, str]:
        """Return trusted content and stable metadata."""

        return {
            "kind": self.kind.value,
            "source_name": self.source_name,
            "version": self.version,
            "content": self.content,
            "trust": self.trust.value,
        }


class DomainRepository(Protocol):
    """Boundary for future SQLite-backed structured domain storage."""

    def user_can_access_document(
        self,
        *,
        user_id: UserId,
        document_id: DocumentId,
    ) -> bool:
        """Resolve explicit document authorization."""
        ...

    def create_user(self, *, user: UserRecord) -> None:
        """Create one user or reject a conflicting identifier."""
        ...

    def get_user(self, *, user_id: UserId) -> UserRecord:
        """Retrieve one user."""
        ...

    def create_document(self, *, document: DocumentRecord) -> None:
        """Create a document and owner access atomically."""
        ...

    def get_document(
        self,
        *,
        user_id: UserId,
        document_id: DocumentId,
    ) -> DocumentRecord:
        """Retrieve a document only inside an authorized user scope."""
        ...

    def grant_document_access(
        self,
        *,
        grantor_user_id: UserId,
        document_id: DocumentId,
        grantee_user_id: UserId,
        access_level: AccessLevel,
        created_at: datetime,
    ) -> None:
        """Grant explicit document access through owner authority."""
        ...

    def create_document_version(
        self,
        *,
        user_id: UserId,
        version: DocumentVersionRecord,
    ) -> DocumentVersionRecord:
        """Allocate and persist the next immutable version."""
        ...

    def get_document_version(
        self,
        *,
        user_id: UserId,
        document_id: DocumentId,
        version_number: int,
    ) -> DocumentVersionRecord:
        """Retrieve one authorized version."""
        ...

    def get_latest_document_version(
        self,
        *,
        user_id: UserId,
        document_id: DocumentId,
    ) -> DocumentVersionRecord:
        """Retrieve the latest authorized version."""
        ...

    def add_shared_comment(
        self,
        *,
        user_id: UserId,
        comment_id: CommentId,
        document_id: DocumentId,
        body: str,
        created_at: datetime,
    ) -> None:
        """Add untrusted shared content for an authorized user."""
        ...

    def list_shared_comments(
        self,
        *,
        user_id: UserId,
        document_id: DocumentId,
    ) -> tuple[SharedComment, ...]:
        """Return authorized shared comments in deterministic order."""
        ...

    def create_run(self, *, context: WorkflowRequestContext) -> None:
        """Persist a new identity-scoped workflow run."""
        ...

    def append_event(
        self,
        *,
        user_id: UserId,
        document_id: DocumentId,
        event: RunEvent,
    ) -> None:
        """Append an event after authorization has been resolved."""
        ...

    def append_handoff(
        self,
        *,
        user_id: UserId,
        document_id: DocumentId,
        handoff: AgentHandoff,
    ) -> None:
        """Append a handoff after authorization has been resolved."""
        ...

    def run_exists_for_scope(
        self,
        *,
        run_id: RunId,
        user_id: UserId,
        document_id: DocumentId,
    ) -> bool:
        """Check run ownership without inferring access from an ID alone."""
        ...

    def set_run_status(
        self,
        *,
        run_id: RunId,
        user_id: UserId,
        document_id: DocumentId,
        status: RunStatus,
        completed_at: datetime | None,
    ) -> None:
        """Advance the persisted run lifecycle."""
        ...


class PrivateFactStore(Protocol):
    """Boundary for future user-scoped document-style memory."""

    def save_fact(self, *, user_id: UserId, fact: PrivateFact) -> None:
        """Save a fact only within the explicitly supplied user scope."""
        ...

    def retrieve_facts(
        self,
        *,
        user_id: UserId,
        cue: str,
    ) -> tuple[PrivateFact, ...]:
        """Retrieve relevant facts for exactly one user."""
        ...


class RulesLoader(Protocol):
    """Boundary for trusted, manually editable Markdown rules."""

    def load(self, *, kind: RuleKind) -> RuleDocument:
        """Load a versioned trusted rule document by application-known kind."""
        ...
