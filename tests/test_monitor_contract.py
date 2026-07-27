from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from editorial_agent.contracts.events import EventType, RunEvent
from editorial_agent.contracts.identity import DocumentId, EventId, RunId, SessionId, UserId
from editorial_agent.contracts.monitor import (
    CompletedRunBundle,
    MonitorReferenceDocument,
    WorkflowRunRecord,
)
from editorial_agent.contracts.workflow import AgentRole, RunStatus

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "completed_run_v1.json"
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
