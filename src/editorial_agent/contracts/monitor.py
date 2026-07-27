"""Read-only completed-run input contract for the independent Monitor."""

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
from editorial_agent.contracts.events import EventType, RunEvent, validate_event_order
from editorial_agent.contracts.handoffs import AgentHandoff, validate_handoff_order
from editorial_agent.contracts.identity import (
    DocumentId,
    DocumentVersionId,
    RunId,
    SessionId,
    UserId,
    validate_identifier,
)
from editorial_agent.contracts.workflow import AgentRole, RunStatus

MONITOR_BUNDLE_SCHEMA_VERSION = "1"
MONITOR_REPORT_SCHEMA_VERSION = "1"


@dataclass(frozen=True)
class WorkflowRunRecord:
    """Sanitized persisted state for exactly one workflow run."""

    run_id: RunId
    user_id: UserId
    session_id: SessionId
    document_id: DocumentId
    request: str
    status: RunStatus
    started_at: datetime
    completed_at: datetime | None
    schema_version: str = "1"

    def __post_init__(self) -> None:
        validate_identifier(self.run_id, "run_id")
        validate_identifier(self.user_id, "user_id")
        validate_identifier(self.session_id, "session_id")
        validate_identifier(self.document_id, "document_id")
        require_non_blank(self.request, "request")
        require_non_blank(self.schema_version, "schema_version")
        require_utc_timestamp(self.started_at, "started_at")
        if self.completed_at is not None:
            require_utc_timestamp(self.completed_at, "completed_at")
            if self.completed_at < self.started_at:
                raise ValueError("completed_at cannot precede started_at")
        if self.status.is_terminal != (self.completed_at is not None):
            raise ValueError(
                "terminal runs require completed_at; live runs must omit it"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "user_id": self.user_id,
            "session_id": self.session_id,
            "document_id": self.document_id,
            "request": self.request,
            "status": self.status.value,
            "started_at": timestamp_to_json(self.started_at),
            "completed_at": (
                timestamp_to_json(self.completed_at) if self.completed_at else None
            ),
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> WorkflowRunRecord:
        return cls(
            schema_version=value["schema_version"],
            run_id=RunId(value["run_id"]),
            user_id=UserId(value["user_id"]),
            session_id=SessionId(value["session_id"]),
            document_id=DocumentId(value["document_id"]),
            request=value["request"],
            status=RunStatus(value["status"]),
            started_at=parse_utc_timestamp(value["started_at"], "started_at"),
            completed_at=(
                parse_utc_timestamp(value["completed_at"], "completed_at")
                if value.get("completed_at") is not None
                else None
            ),
        )


@dataclass(frozen=True)
class DocumentVersionSnapshot:
    """Sanitized document version included for retrospective evaluation."""

    document_version_id: DocumentVersionId
    document_id: DocumentId
    version_number: int
    content: str
    created_by_actor: AgentRole
    created_at: datetime

    def __post_init__(self) -> None:
        validate_identifier(self.document_version_id, "document_version_id")
        validate_identifier(self.document_id, "document_id")
        if isinstance(self.version_number, bool) or self.version_number < 1:
            raise ValueError("version_number must be a positive integer")
        require_non_blank(self.content, "content")
        require_utc_timestamp(self.created_at, "created_at")

    def to_dict(self) -> dict[str, Any]:
        return {
            "document_version_id": self.document_version_id,
            "document_id": self.document_id,
            "version_number": self.version_number,
            "content": self.content,
            "created_by_actor": self.created_by_actor.value,
            "created_at": timestamp_to_json(self.created_at),
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> DocumentVersionSnapshot:
        return cls(
            document_version_id=DocumentVersionId(value["document_version_id"]),
            document_id=DocumentId(value["document_id"]),
            version_number=value["version_number"],
            content=value["content"],
            created_by_actor=AgentRole(value["created_by_actor"]),
            created_at=parse_utc_timestamp(value["created_at"], "created_at"),
        )


@dataclass(frozen=True)
class MonitorReferenceDocument:
    """Versioned trusted rules or rubric supplied to the Monitor."""

    source_name: str
    version: str
    content: str

    def __post_init__(self) -> None:
        require_non_blank(self.source_name, "source_name")
        require_non_blank(self.version, "version")
        require_non_blank(self.content, "content")

    def to_dict(self) -> dict[str, str]:
        return {
            "source_name": self.source_name,
            "version": self.version,
            "content": self.content,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> MonitorReferenceDocument:
        return cls(
            source_name=value["source_name"],
            version=value["version"],
            content=value["content"],
        )


@dataclass(frozen=True)
class CompletedRunBundle:
    """Provider-neutral, read-only input for post-run monitoring."""

    run: WorkflowRunRecord
    events: tuple[RunEvent, ...]
    handoffs: tuple[AgentHandoff, ...]
    document_versions: tuple[DocumentVersionSnapshot, ...]
    operating_rules: MonitorReferenceDocument
    critic_rubric: MonitorReferenceDocument
    schema_version: str = MONITOR_BUNDLE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        require_non_blank(self.schema_version, "schema_version")
        if not self.run.status.is_terminal:
            raise ValueError("Monitor bundles require a terminal run")
        validate_event_order(self.events, self.run.run_id)
        validate_handoff_order(self.handoffs, self.run.run_id)
        version_numbers = [version.version_number for version in self.document_versions]
        if version_numbers != sorted(version_numbers) or len(version_numbers) != len(
            set(version_numbers)
        ):
            raise ValueError("document versions must be uniquely ordered")
        if any(
            version.document_id != self.run.document_id
            for version in self.document_versions
        ):
            raise ValueError("document versions must belong to the run document")
        if not self.events or self.events[0].event_type is not EventType.RUN_STARTED:
            raise ValueError("completed run history must begin with run_started")
        terminal_events = {
            RunStatus.COMPLETED: EventType.RUN_COMPLETED,
            RunStatus.BLOCKED: EventType.RUN_BLOCKED,
            RunStatus.FAILED: EventType.RUN_FAILED,
        }
        if self.events[-1].event_type is not terminal_events[self.run.status]:
            raise ValueError("last event must match the terminal run status")

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-compatible bundle with deterministic list ordering."""

        return {
            "schema_version": self.schema_version,
            "run": self.run.to_dict(),
            "events": [event.to_dict() for event in self.events],
            "handoffs": [handoff.to_dict() for handoff in self.handoffs],
            "document_versions": [
                version.to_dict() for version in self.document_versions
            ],
            "operating_rules": self.operating_rules.to_dict(),
            "critic_rubric": self.critic_rubric.to_dict(),
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> CompletedRunBundle:
        """Validate a decoded fixture or repository export."""

        return cls(
            schema_version=value["schema_version"],
            run=WorkflowRunRecord.from_dict(value["run"]),
            events=tuple(RunEvent.from_dict(item) for item in value["events"]),
            handoffs=tuple(
                AgentHandoff.from_dict(item) for item in value["handoffs"]
            ),
            document_versions=tuple(
                DocumentVersionSnapshot.from_dict(item)
                for item in value["document_versions"]
            ),
            operating_rules=MonitorReferenceDocument.from_dict(
                value["operating_rules"]
            ),
            critic_rubric=MonitorReferenceDocument.from_dict(
                value["critic_rubric"]
            ),
        )


class MonitorAxis(StrEnum):
    """Stable evaluation dimensions for independent post-run review."""

    SOURCE_FIDELITY = "source_fidelity"
    INSTRUCTION_ADHERENCE = "instruction_adherence"
    TASK_COMPLETION = "task_completion"
    CRITIC_CONSISTENCY = "critic_consistency"
    REVISION_QUALITY = "revision_quality"
    APPROVAL_AND_TERMINAL_STATE = "approval_and_terminal_state"
    TRACE_COMPLETENESS = "trace_completeness"


class MonitorJudgment(StrEnum):
    """Named finding outcomes that do not imply numeric scoring."""

    PASS = "pass"
    PARTIAL = "partial"
    FAIL = "fail"
    UNKNOWN = "unknown"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


@dataclass(frozen=True)
class MonitorRationale:
    """Explain expected and observed behavior plus consequence."""

    expected: str
    observed: str
    reason: str
    impact: str

    def __post_init__(self) -> None:
        require_non_blank(self.expected, "rationale.expected")
        require_non_blank(self.observed, "rationale.observed")
        require_non_blank(self.reason, "rationale.reason")
        require_non_blank(self.impact, "rationale.impact")

    def to_dict(self) -> dict[str, str]:
        return {
            "expected": self.expected,
            "observed": self.observed,
            "reason": self.reason,
            "impact": self.impact,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> MonitorRationale:
        return cls(
            expected=value["expected"],
            observed=value["observed"],
            reason=value["reason"],
            impact=value["impact"],
        )


@dataclass(frozen=True)
class MonitorFinding:
    """One evidence-linked judgment on a named Monitor axis."""

    finding_id: str
    axis: MonitorAxis
    judgment: MonitorJudgment
    rationale: MonitorRationale
    evidence_references: tuple[str, ...]

    def __post_init__(self) -> None:
        validate_identifier(self.finding_id, "finding_id")
        for reference in self.evidence_references:
            validate_identifier(reference, "evidence_reference")

    def to_dict(self) -> dict[str, Any]:
        return {
            "finding_id": self.finding_id,
            "axis": self.axis.value,
            "judgment": self.judgment.value,
            "rationale": self.rationale.to_dict(),
            "evidence_references": list(self.evidence_references),
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> MonitorFinding:
        return cls(
            finding_id=value["finding_id"],
            axis=MonitorAxis(value["axis"]),
            judgment=MonitorJudgment(value["judgment"]),
            rationale=MonitorRationale.from_dict(value["rationale"]),
            evidence_references=tuple(value["evidence_references"]),
        )


@dataclass(frozen=True)
class MonitorReport:
    """Provider-neutral output of one independent Monitor evaluation."""

    report_id: str
    run_id: RunId
    created_at: datetime
    summary: str
    findings: tuple[MonitorFinding, ...]
    schema_version: str = MONITOR_REPORT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        validate_identifier(self.report_id, "report_id")
        validate_identifier(self.run_id, "run_id")
        require_utc_timestamp(self.created_at, "created_at")
        require_non_blank(self.summary, "summary")
        require_non_blank(self.schema_version, "schema_version")
        finding_ids = [finding.finding_id for finding in self.findings]
        if len(finding_ids) != len(set(finding_ids)):
            raise ValueError("Monitor finding identifiers must be unique")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "report_id": self.report_id,
            "run_id": self.run_id,
            "created_at": timestamp_to_json(self.created_at),
            "summary": self.summary,
            "findings": [finding.to_dict() for finding in self.findings],
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> MonitorReport:
        return cls(
            schema_version=value["schema_version"],
            report_id=value["report_id"],
            run_id=RunId(value["run_id"]),
            created_at=parse_utc_timestamp(value["created_at"], "created_at"),
            summary=value["summary"],
            findings=tuple(
                MonitorFinding.from_dict(item) for item in value["findings"]
            ),
        )
