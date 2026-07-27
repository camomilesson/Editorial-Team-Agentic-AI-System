"""Strict role-specific result payloads and model-output parsing."""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from editorial_agent.contracts.common import require_non_blank
from editorial_agent.contracts.workflow import (
    AgentOutcome,
    BlockedReason,
    OutcomeStatus,
    PendingApproval,
    RevisionFeedback,
    SanitizedError,
)

_FORBIDDEN_MODEL_KEYS = {
    "user_id",
    "document_id",
    "document_version_id",
    "run_id",
    "fact_id",
    "path",
    "memory_root",
    "storage_root",
    "database",
    "database_path",
}


class RoleOutputError(ValueError):
    """A model response cannot be accepted as a structured role outcome."""


@dataclass(frozen=True)
class MemoryDecision:
    """Executor decision about a possible durable user fact."""

    should_save: bool
    reason: str
    content: str | None = None
    cue: str | None = None

    def __post_init__(self) -> None:
        require_non_blank(self.reason, "memory_decision.reason")
        if self.should_save:
            if self.content is None or self.cue is None:
                raise ValueError("save decisions require content and cue")
            require_non_blank(self.content, "memory_decision.content")
            require_non_blank(self.cue, "memory_decision.cue")
        elif self.content is not None or self.cue is not None:
            raise ValueError("no-save decisions must not include content or cue")

    def to_dict(self) -> dict[str, Any]:
        return {
            "should_save": self.should_save,
            "content": self.content,
            "cue": self.cue,
            "reason": self.reason,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> MemoryDecision:
        _require_exact_keys(
            value,
            required={"should_save", "reason"},
            optional={"content", "cue"},
            field_name="memory_decision",
        )
        if not isinstance(value["should_save"], bool):
            raise RoleOutputError("memory_decision.should_save must be boolean")
        try:
            return cls(
                should_save=value["should_save"],
                reason=value["reason"],
                content=value.get("content"),
                cue=value.get("cue"),
            )
        except (TypeError, ValueError) as exc:
            raise RoleOutputError("memory decision is invalid") from exc


@dataclass(frozen=True)
class ExecutorResult:
    """Validated successful Executor payload."""

    draft: str
    summary: str
    memory_decision: MemoryDecision

    def __post_init__(self) -> None:
        require_non_blank(self.draft, "draft")
        require_non_blank(self.summary, "summary")

    def to_dict(self) -> dict[str, Any]:
        return {
            "draft": self.draft,
            "summary": self.summary,
            "memory_decision": self.memory_decision.to_dict(),
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> ExecutorResult:
        _reject_identity_fields(value)
        _require_exact_keys(
            value,
            required={"draft", "summary", "memory_decision"},
            optional=set(),
            field_name="Executor result",
        )
        if not isinstance(value["memory_decision"], dict):
            raise RoleOutputError("memory_decision must be an object")
        try:
            return cls(
                draft=value["draft"],
                summary=value["summary"],
                memory_decision=MemoryDecision.from_dict(value["memory_decision"]),
            )
        except (TypeError, ValueError) as exc:
            if isinstance(exc, RoleOutputError):
                raise
            raise RoleOutputError("Executor result is invalid") from exc


class CriticVerdict(StrEnum):
    """Explicit Critic decision, never inferred from prose."""

    ACCEPT = "accept"
    REVISE = "revise"


class CriticIssueType(StrEnum):
    """How a Critic issue relates to the exact reviewed draft."""

    PRESENT_CONTENT = "present_content"
    MISSING_REQUIRED_CONTENT = "missing_required_content"
    CONFLICT = "conflict"
    STYLE = "style"


class RuleCompatibility(StrEnum):
    """Critic declaration that an omitted requirement respects trusted rules."""

    SUPPORTED = "supported"


@dataclass(frozen=True)
class CriticIssue:
    """One concrete rubric issue requiring a change."""

    issue_type: CriticIssueType
    category: str
    summary: str
    source_evidence: str
    required_change: str
    draft_excerpt: str | None = None
    request_evidence: str | None = None
    required_content: str | None = None
    rule_compatibility: RuleCompatibility | None = None

    def __post_init__(self) -> None:
        require_non_blank(self.category, "issue.category")
        require_non_blank(self.summary, "issue.summary")
        require_non_blank(self.source_evidence, "issue.source_evidence")
        require_non_blank(self.required_change, "issue.required_change")
        if self.issue_type is CriticIssueType.PRESENT_CONTENT:
            if self.draft_excerpt is None:
                raise ValueError("present-content issues require draft_excerpt")
            require_non_blank(self.draft_excerpt, "issue.draft_excerpt")
        elif self.issue_type is CriticIssueType.MISSING_REQUIRED_CONTENT:
            if (
                self.request_evidence is None
                or self.required_content is None
                or self.rule_compatibility is None
            ):
                raise ValueError(
                    "missing-content issues require request evidence, "
                    "required content, and rule compatibility"
                )
            require_non_blank(self.request_evidence, "issue.request_evidence")
            require_non_blank(self.required_content, "issue.required_content")
        elif self.draft_excerpt is not None:
            require_non_blank(self.draft_excerpt, "issue.draft_excerpt")

    def to_dict(self) -> dict[str, str | None]:
        return {
            "issue_type": self.issue_type.value,
            "category": self.category,
            "summary": self.summary,
            "draft_excerpt": self.draft_excerpt,
            "source_evidence": self.source_evidence,
            "required_change": self.required_change,
            "request_evidence": self.request_evidence,
            "required_content": self.required_content,
            "rule_compatibility": (
                self.rule_compatibility.value
                if self.rule_compatibility is not None
                else None
            ),
        }

    def revision_instruction(self) -> str:
        """Return feedback constrained to validated source-backed content."""

        if self.issue_type is CriticIssueType.MISSING_REQUIRED_CONTENT:
            return f"Add the source-backed content: {self.required_content}"
        return self.required_change

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> CriticIssue:
        _require_exact_keys(
            value,
            required={
                "issue_type",
                "category",
                "summary",
                "source_evidence",
                "required_change",
            },
            optional={
                "draft_excerpt",
                "request_evidence",
                "required_content",
                "rule_compatibility",
            },
            field_name="Critic issue",
        )
        try:
            return cls(
                issue_type=CriticIssueType(value["issue_type"]),
                category=value["category"],
                summary=value["summary"],
                source_evidence=value["source_evidence"],
                required_change=value["required_change"],
                draft_excerpt=value.get("draft_excerpt"),
                request_evidence=value.get("request_evidence"),
                required_content=value.get("required_content"),
                rule_compatibility=(
                    RuleCompatibility(value["rule_compatibility"])
                    if value.get("rule_compatibility") is not None
                    else None
                ),
            )
        except (TypeError, ValueError) as exc:
            raise RoleOutputError("Critic issue is invalid") from exc


@dataclass(frozen=True)
class CriticResult:
    """Validated Critic assessment payload."""

    verdict: CriticVerdict
    issues: tuple[CriticIssue, ...]
    summary: str

    def __post_init__(self) -> None:
        require_non_blank(self.summary, "Critic summary")
        if self.verdict is CriticVerdict.ACCEPT and self.issues:
            raise ValueError("accepted drafts must not include revision issues")
        if self.verdict is CriticVerdict.REVISE and not self.issues:
            raise ValueError("revision verdicts require at least one issue")

    def to_dict(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict.value,
            "issues": [issue.to_dict() for issue in self.issues],
            "summary": self.summary,
        }

    def to_executor_feedback_dict(self) -> dict[str, Any]:
        """Return Critic feedback with trusted omission instructions."""

        value = self.to_dict()
        for issue_value, issue in zip(value["issues"], self.issues, strict=True):
            issue_value["required_change"] = issue.revision_instruction()
        return value

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> CriticResult:
        _reject_identity_fields(value)
        _require_exact_keys(
            value,
            required={"verdict", "issues", "summary"},
            optional=set(),
            field_name="Critic result",
        )
        if not isinstance(value["issues"], list):
            raise RoleOutputError("Critic issues must be an array")
        try:
            return cls(
                verdict=CriticVerdict(value["verdict"]),
                issues=tuple(CriticIssue.from_dict(item) for item in value["issues"]),
                summary=value["summary"],
            )
        except (TypeError, ValueError) as exc:
            if isinstance(exc, RoleOutputError):
                raise
            raise RoleOutputError("Critic result is invalid") from exc


def parse_executor_outcome(text: str) -> AgentOutcome:
    """Parse one strict Executor JSON envelope."""

    value = _parse_envelope(text)
    status = _parse_status(value)
    if status is OutcomeStatus.COMPLETE:
        result = ExecutorResult.from_dict(_require_result(value))
        needs_approval, approval = _parse_approval(value)
        return AgentOutcome(
            status=status,
            result=result.to_dict(),
            needs_approval=needs_approval,
            approval=approval,
        )
    return _parse_non_complete(value, status)


def parse_critic_outcome(text: str) -> AgentOutcome:
    """Parse one strict Critic JSON envelope."""

    value = _parse_envelope(text)
    status = _parse_status(value)
    if status in {OutcomeStatus.COMPLETE, OutcomeStatus.REVISE}:
        result = CriticResult.from_dict(_require_result(value))
        expected = (
            CriticVerdict.ACCEPT
            if status is OutcomeStatus.COMPLETE
            else CriticVerdict.REVISE
        )
        if result.verdict is not expected:
            raise RoleOutputError("Critic status and verdict do not agree")
        needs_approval, approval = _parse_approval(value)
        if status is OutcomeStatus.COMPLETE:
            return AgentOutcome(
                status=status,
                result=result.to_dict(),
                needs_approval=needs_approval,
                approval=approval,
            )
        revision = RevisionFeedback(
            summary=result.summary,
            required_changes=tuple(
                issue.revision_instruction() for issue in result.issues
            ),
        )
        return AgentOutcome(
            status=status,
            result=result.to_dict(),
            needs_approval=needs_approval,
            approval=approval,
            revision=revision,
        )
    return _parse_non_complete(value, status)


def _parse_envelope(text: str) -> dict[str, Any]:
    try:
        value = json.loads(text)
    except (TypeError, json.JSONDecodeError) as exc:
        raise RoleOutputError("Role output must be valid JSON.") from exc
    if not isinstance(value, dict):
        raise RoleOutputError("Role output must be a JSON object.")
    _reject_identity_fields(value)
    _require_exact_keys(
        value,
        required={"status"},
        optional={"result", "needs_approval", "approval", "blocked", "error"},
        field_name="role outcome",
    )
    return value


def _parse_status(value: dict[str, Any]) -> OutcomeStatus:
    try:
        return OutcomeStatus(value["status"])
    except (TypeError, ValueError) as exc:
        raise RoleOutputError("Role outcome status is unknown.") from exc


def _parse_non_complete(
    value: dict[str, Any],
    status: OutcomeStatus,
) -> AgentOutcome:
    needs_approval, approval = _parse_approval(value)

    try:
        if status is OutcomeStatus.BLOCKED:
            blocked = value.get("blocked")
            if not isinstance(blocked, dict):
                raise RoleOutputError("blocked outcome requires blocked details")
            _require_exact_keys(
                blocked,
                required={"code", "message"},
                optional=set(),
                field_name="blocked",
            )
            return AgentOutcome(
                status=status,
                needs_approval=needs_approval,
                approval=approval,
                blocked=BlockedReason(**blocked),
            )
        if status is OutcomeStatus.ERROR:
            error = value.get("error")
            if not isinstance(error, dict):
                raise RoleOutputError("error outcome requires error details")
            _require_exact_keys(
                error,
                required={"code", "message"},
                optional={"retryable"},
                field_name="error",
            )
            return AgentOutcome(
                status=status,
                error=SanitizedError(**error),
            )
    except (TypeError, ValueError) as exc:
        if isinstance(exc, RoleOutputError):
            raise
        raise RoleOutputError("Role outcome details are invalid") from exc
    raise RoleOutputError(f"{status.value} is not valid for this role response")


def _parse_approval(
    value: dict[str, Any],
) -> tuple[bool, PendingApproval | None]:
    needs_approval = value.get("needs_approval", False)
    if not isinstance(needs_approval, bool):
        raise RoleOutputError("needs_approval must be boolean")
    approval = None
    if value.get("approval") is not None:
        approval_value = value["approval"]
        if not isinstance(approval_value, dict):
            raise RoleOutputError("approval must be an object")
        _require_exact_keys(
            approval_value,
            required={"action", "summary"},
            optional=set(),
            field_name="approval",
        )
        try:
            approval = PendingApproval(**approval_value)
        except (TypeError, ValueError) as exc:
            raise RoleOutputError("approval details are invalid") from exc
    if needs_approval != (approval is not None):
        raise RoleOutputError("needs_approval and approval details must agree")
    return needs_approval, approval


def _require_result(value: dict[str, Any]) -> dict[str, Any]:
    result = value.get("result")
    if not isinstance(result, dict):
        raise RoleOutputError("complete or revise outcome requires a result object")
    return result


def _require_exact_keys(
    value: dict[str, Any],
    *,
    required: set[str],
    optional: set[str],
    field_name: str,
) -> None:
    missing = required - value.keys()
    unknown = value.keys() - required - optional
    if missing:
        raise RoleOutputError(f"{field_name} is missing required fields")
    if unknown:
        raise RoleOutputError(f"{field_name} contains unsupported fields")


def _reject_identity_fields(value: Any) -> None:
    if isinstance(value, dict):
        forbidden = _FORBIDDEN_MODEL_KEYS & value.keys()
        if forbidden:
            raise RoleOutputError("Model output must not supply trusted identity fields")
        for item in value.values():
            _reject_identity_fields(item)
    elif isinstance(value, list):
        for item in value:
            _reject_identity_fields(item)
