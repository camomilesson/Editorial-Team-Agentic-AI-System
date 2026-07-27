"""Interfaces separating structured data, private facts, and trusted rules."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol

from editorial_agent.contracts.common import (
    require_non_blank,
    require_utc_timestamp,
)
from editorial_agent.contracts.events import RunEvent
from editorial_agent.contracts.handoffs import AgentHandoff
from editorial_agent.contracts.identity import (
    DocumentId,
    FactId,
    RunId,
    UserId,
    WorkflowRequestContext,
    validate_identifier,
)
from editorial_agent.contracts.trust import TrustClassification


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


class RuleKind(StrEnum):
    """Trusted Markdown documents loaded as operating context."""

    GLOBAL_OPERATING_RULES = "global_operating_rules"
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
