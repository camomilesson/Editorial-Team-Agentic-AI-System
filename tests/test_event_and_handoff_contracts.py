from __future__ import annotations

from datetime import UTC, datetime

import pytest

from editorial_agent.contracts.events import EventType, RunEvent, validate_event_order
from editorial_agent.contracts.handoffs import AgentHandoff, validate_handoff_order
from editorial_agent.contracts.identity import EventId, HandoffId, RunId
from editorial_agent.contracts.workflow import AgentRole, OutcomeStatus

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def make_event(sequence: int = 1, **kwargs: object) -> RunEvent:
    values = {
        "event_id": EventId(f"event_{sequence}"),
        "run_id": RunId("run_1"),
        "sequence": sequence,
        "timestamp": NOW,
        "actor": AgentRole.ORCHESTRATOR,
        "event_type": EventType.RUN_STARTED,
        "payload": {"safe_summary": "run began"},
    }
    values.update(kwargs)
    return RunEvent(**values)


def make_handoff(sequence: int = 1, **kwargs: object) -> AgentHandoff:
    values = {
        "handoff_id": HandoffId(f"handoff_{sequence}"),
        "run_id": RunId("run_1"),
        "sequence": sequence,
        "round_number": 0,
        "from_agent": AgentRole.EXECUTOR,
        "to_agent": AgentRole.CRITIC,
        "status": OutcomeStatus.COMPLETE,
        "payload": {"summary": "ready"},
        "created_at": NOW,
    }
    values.update(kwargs)
    return AgentHandoff(**values)


def test_event_serialization_round_trip() -> None:
    event = make_event()

    assert RunEvent.from_dict(event.to_dict()) == event


@pytest.mark.parametrize("sequence", [0, -1, True])
def test_event_requires_positive_sequence(sequence: int) -> None:
    with pytest.raises(ValueError, match="positive"):
        make_event(sequence)


def test_event_payload_must_be_json_compatible() -> None:
    with pytest.raises(ValueError, match="JSON-compatible"):
        make_event(payload={"bad": {1, 2}})


def test_event_order_must_be_contiguous_and_run_scoped() -> None:
    validate_event_order((make_event(1), make_event(2)), RunId("run_1"))

    with pytest.raises(ValueError, match="contiguous"):
        validate_event_order((make_event(2), make_event(1)), RunId("run_1"))
    with pytest.raises(ValueError, match="bundle run"):
        validate_event_order(
            (make_event(1, run_id=RunId("other_run")),),
            RunId("run_1"),
        )


def test_handoff_serialization_round_trip() -> None:
    handoff = make_handoff()

    assert AgentHandoff.from_dict(handoff.to_dict()) == handoff


def test_handoff_sender_and_receiver_must_differ() -> None:
    with pytest.raises(ValueError, match="must differ"):
        make_handoff(to_agent=AgentRole.EXECUTOR)


@pytest.mark.parametrize("field", ["from_agent", "to_agent"])
def test_monitor_cannot_participate_in_live_handoff(field: str) -> None:
    with pytest.raises(ValueError, match="cannot"):
        make_handoff(**{field: AgentRole.MONITOR})


def test_handoff_ordering_invariants() -> None:
    with pytest.raises(ValueError, match="positive"):
        make_handoff(sequence=0)
    with pytest.raises(ValueError, match="non-negative"):
        make_handoff(round_number=-1)

    validate_handoff_order((make_handoff(1), make_handoff(2)), RunId("run_1"))
    with pytest.raises(ValueError, match="contiguous"):
        validate_handoff_order((make_handoff(2),), RunId("run_1"))


def test_handoff_payload_must_be_json_compatible() -> None:
    with pytest.raises(ValueError, match="JSON-compatible"):
        make_handoff(payload={"bad": object()})
