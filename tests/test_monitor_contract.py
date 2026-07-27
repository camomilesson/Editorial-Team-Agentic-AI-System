from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from editorial_agent.contracts.events import EventType, RunEvent
from editorial_agent.contracts.identity import DocumentId, EventId, RunId, SessionId, UserId
from editorial_agent.contracts.monitor import (
    CompletedRunBundle,
    MonitorAxis,
    MonitorFinding,
    MonitorJudgment,
    MonitorRationale,
    MonitorReferenceDocument,
    MonitorReport,
    WorkflowRunRecord,
)
from editorial_agent.contracts.workflow import AgentRole, RunStatus

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "completed_run_v1.json"
RICH_FIXTURE_PATH = (
    Path(__file__).parent / "fixtures" / "completed_run_monitor_v1.json"
)
BLOCKED_FIXTURE_PATH = (
    Path(__file__).parent / "fixtures" / "blocked_run_monitor_v1.json"
)
NOW = datetime(2026, 1, 1, tzinfo=UTC)


def reference(name: str) -> MonitorReferenceDocument:
    return MonitorReferenceDocument(name, "1", "Synthetic evaluation guidance.")


def test_completed_run_fixture_validates_and_round_trips() -> None:
    decoded = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))

    bundle = CompletedRunBundle.from_dict(decoded)

    assert bundle.run.status is RunStatus.COMPLETED
    assert [event.sequence for event in bundle.events] == [1, 2, 3, 4, 5]
    assert [handoff.sequence for handoff in bundle.handoffs] == [1, 2]
    assert [handoff.round_number for handoff in bundle.handoffs] == [0, 1]
    assert bundle.to_dict() == decoded
    assert "private" not in json.dumps(decoded).lower()


def test_monitor_bundle_rejects_non_terminal_run() -> None:
    run = WorkflowRunRecord(
        run_id=RunId("run_1"),
        user_id=UserId("user_1"),
        session_id=SessionId("session_1"),
        document_id=DocumentId("document_1"),
        request="Edit.",
        status=RunStatus.RUNNING,
        started_at=NOW,
        completed_at=None,
    )
    start = RunEvent(
        event_id=EventId("event_1"),
        run_id=run.run_id,
        sequence=1,
        timestamp=NOW,
        actor=AgentRole.ORCHESTRATOR,
        event_type=EventType.RUN_STARTED,
        payload={},
    )

    with pytest.raises(ValueError, match="terminal run"):
        CompletedRunBundle(
            run=run,
            events=(start,),
            handoffs=(),
            document_versions=(),
            operating_rules=reference("rules.md"),
            critic_rubric=reference("rubric.md"),
        )


def test_monitor_bundle_rejects_nondeterministic_event_order() -> None:
    decoded = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    decoded["events"][1], decoded["events"][2] = (
        decoded["events"][2],
        decoded["events"][1],
    )

    with pytest.raises(ValueError, match="contiguous"):
        CompletedRunBundle.from_dict(decoded)


def test_terminal_run_requires_completion_timestamp() -> None:
    with pytest.raises(ValueError, match="require completed_at"):
        WorkflowRunRecord(
            run_id=RunId("run_1"),
            user_id=UserId("user_1"),
            session_id=SessionId("session_1"),
            document_id=DocumentId("document_1"),
            request="Edit.",
            status=RunStatus.COMPLETED,
            started_at=NOW,
            completed_at=None,
        )


def load_bundle(path: Path) -> tuple[CompletedRunBundle, dict[str, object]]:
    decoded = json.loads(path.read_text(encoding="utf-8"))
    return CompletedRunBundle.from_dict(decoded), decoded


def assert_sanitized_fixture(decoded: dict[str, object]) -> None:
    encoded = json.dumps(decoded).casefold()
    for forbidden in (
        "gemini_api_key",
        "continuation_token",
        "dragonfruit",
        "private-memory/",
        "/users/",
        "live-evidence/",
    ):
        assert forbidden not in encoded


def test_rich_monitor_fixture_validates_complete_revision_history() -> None:
    bundle, decoded = load_bundle(RICH_FIXTURE_PATH)

    assert bundle.to_dict() == decoded
    assert bundle.run.status is RunStatus.COMPLETED
    assert [version.version_number for version in bundle.document_versions] == [
        1,
        2,
        3,
    ]
    assert bundle.document_versions[0].created_by_actor is AgentRole.HUMAN
    assert any(
        handoff.from_agent is AgentRole.CRITIC
        and handoff.to_agent is AgentRole.EXECUTOR
        and handoff.status.value == "revise"
        for handoff in bundle.handoffs
    )
    assert any(
        handoff.from_agent is AgentRole.CRITIC
        and handoff.to_agent is AgentRole.ORCHESTRATOR
        and handoff.payload.get("verdict") == "accept"
        for handoff in bundle.handoffs
    )
    assert any(
        event.event_type is EventType.APPROVAL_RESOLVED
        and event.payload.get("approved") is True
        for event in bundle.events
    )
    assert bundle.events[-1].event_type is EventType.RUN_COMPLETED
    assert_sanitized_fixture(decoded)


def test_blocked_monitor_fixture_validates_declined_finalization() -> None:
    bundle, decoded = load_bundle(BLOCKED_FIXTURE_PATH)

    assert bundle.to_dict() == decoded
    assert bundle.run.status is RunStatus.BLOCKED
    assert [version.version_number for version in bundle.document_versions] == [
        1,
        2,
    ]
    assert bundle.document_versions[0].created_by_actor is AgentRole.HUMAN
    assert any(
        handoff.from_agent is AgentRole.CRITIC
        and handoff.to_agent is AgentRole.ORCHESTRATOR
        and handoff.payload.get("verdict") == "accept"
        for handoff in bundle.handoffs
    )
    assert any(
        event.event_type is EventType.APPROVAL_RESOLVED
        and event.payload.get("approved") is False
        for event in bundle.events
    )
    assert not any(
        event.event_type is EventType.RUN_COMPLETED for event in bundle.events
    )
    assert bundle.events[-1].event_type is EventType.RUN_BLOCKED
    assert_sanitized_fixture(decoded)


def test_monitor_report_contract_round_trips_named_evidence_findings() -> None:
    report = MonitorReport(
        report_id="monitor_report_001",
        run_id=RunId("run_monitor_completed_001"),
        created_at=NOW,
        summary="The workflow completed with a grounded revision.",
        findings=(
            MonitorFinding(
                finding_id="finding_001",
                axis=MonitorAxis.SOURCE_FIDELITY,
                judgment=MonitorJudgment.PASS,
                rationale=MonitorRationale(
                    expected="Unsupported adoption claims are absent.",
                    observed="The final version omits the unsupported claim.",
                    reason="The Critic requested a grounded revision.",
                    impact="The approved output remains source-faithful.",
                ),
                evidence_references=(
                    "version_monitor_source_001",
                    "version_monitor_draft_002",
                    "event_monitor_completed_005",
                ),
            ),
        ),
    )

    assert MonitorReport.from_dict(report.to_dict()) == report
