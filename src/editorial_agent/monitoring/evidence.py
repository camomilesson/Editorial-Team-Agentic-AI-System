"""Deterministic, qualitative-judgment-free Monitor evidence indexing."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from editorial_agent.contracts import CompletedRunBundle
from editorial_agent.contracts.events import EventType
from editorial_agent.contracts.workflow import AgentRole, OutcomeStatus


@dataclass(frozen=True)
class EvidenceIndex:
    """Stable references and observable facts derived only from a bundle."""

    references: frozenset[str]
    summary: dict[str, Any]


def build_evidence_index(bundle: CompletedRunBundle) -> EvidenceIndex:
    """Index real references and summarize evidence presence deterministically."""

    event_types = [event.event_type for event in bundle.events]
    critic_reviews = [
        event for event in bundle.events if event.event_type is EventType.CRITIC_REVIEW_COMPLETED
    ]
    review_verdicts = [
        str(event.payload.get("verdict", "unknown")) for event in critic_reviews
    ]
    approval_events = [
        event for event in bundle.events if event.event_type is EventType.APPROVAL_RESOLVED
    ]
    approval_values = [
        event.payload.get("approved")
        for event in approval_events
        if isinstance(event.payload.get("approved"), bool)
    ]
    executor_versions = [
        version
        for version in bundle.document_versions
        if version.created_by_actor is AgentRole.EXECUTOR
    ]
    source_versions = [
        version
        for version in bundle.document_versions
        if version.created_by_actor is not AgentRole.EXECUTOR
    ]
    revision_handoffs = [
        handoff
        for handoff in bundle.handoffs
        if handoff.status is OutcomeStatus.REVISE
    ]

    references = {
        str(bundle.run.run_id),
        str(bundle.run.document_id),
        bundle.operating_rules.version,
        bundle.critic_rubric.version,
    }
    references.update(str(event.event_id) for event in bundle.events)
    references.update(str(handoff.handoff_id) for handoff in bundle.handoffs)
    references.update(
        str(version.document_version_id) for version in bundle.document_versions
    )

    missing: list[str] = []
    if not source_versions:
        missing.append("source_document_version")
    if not executor_versions:
        missing.append("executor_document_versions")
    if not critic_reviews:
        missing.append("critic_review_events")
    if not any(verdict == "accept" for verdict in review_verdicts):
        missing.append("critic_acceptance")
    if EventType.APPROVAL_REQUESTED not in event_types:
        missing.append("approval_request")
    if not approval_events:
        missing.append("approval_resolution")

    terminal = bundle.events[-1]
    summary = {
        "run_id": bundle.run.run_id,
        "document_id": bundle.run.document_id,
        "run_status": bundle.run.status.value,
        "terminal_event": {
            "event_id": terminal.event_id,
            "event_type": terminal.event_type.value,
        },
        "source_available": bool(source_versions),
        "source_version_ids": [
            version.document_version_id for version in source_versions
        ],
        "document_version_ids_in_order": [
            version.document_version_id for version in bundle.document_versions
        ],
        "executor_created_version_count": len(executor_versions),
        "critic_review_outcomes": review_verdicts,
        "critic_revision_request_count": sum(
            verdict == "revise" for verdict in review_verdicts
        ),
        "critic_revision_handoff_count": len(revision_handoffs),
        "critic_acceptance_present": any(
            verdict == "accept" for verdict in review_verdicts
        ),
        "approval_requested": EventType.APPROVAL_REQUESTED in event_types,
        "approval_granted": True in approval_values,
        "approval_declined": False in approval_values,
        "revision_count": _revision_count(bundle, executor_versions),
        "event_ids_in_order": [event.event_id for event in bundle.events],
        "handoff_ids_in_order": [handoff.handoff_id for handoff in bundle.handoffs],
        "operating_rules_version": bundle.operating_rules.version,
        "critic_rubric_version": bundle.critic_rubric.version,
        "missing_evidence_classes": missing,
    }
    return EvidenceIndex(references=frozenset(references), summary=summary)


def _revision_count(
    bundle: CompletedRunBundle, executor_versions: list[Any]
) -> int | None:
    terminal_count = bundle.events[-1].payload.get("revision_count")
    if isinstance(terminal_count, int) and not isinstance(terminal_count, bool):
        return terminal_count
    if executor_versions:
        return max(0, len(executor_versions) - 1)
    return None
