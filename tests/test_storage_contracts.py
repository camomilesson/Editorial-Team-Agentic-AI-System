from __future__ import annotations

import inspect
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from editorial_agent.contracts.identity import FactId, UserId
from editorial_agent.contracts.storage import PrivateFact, PrivateFactStore
from editorial_agent.contracts.trust import TrustClassification

MIGRATION_PATH = (
    Path(__file__).parents[1] / "migrations" / "001_initial_domain.sql"
)
NOW = datetime(2026, 1, 1, tzinfo=UTC)


def create_database() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.executescript(MIGRATION_PATH.read_text(encoding="utf-8"))
    return connection


def seed_scope(connection: sqlite3.Connection) -> None:
    connection.execute(
        "INSERT INTO users VALUES (?, ?, ?)",
        ("user_1", "Editor", "2026-01-01T00:00:00Z"),
    )
    connection.execute(
        "INSERT INTO documents VALUES (?, ?, ?, ?)",
        (
            "document_1",
            "user_1",
            "Synthetic document",
            "2026-01-01T00:00:00Z",
        ),
    )
    connection.execute(
        "INSERT INTO workflow_runs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "run_1",
            "user_1",
            "session_1",
            "document_1",
            "Edit.",
            "running",
            "2026-01-01T00:00:00Z",
            None,
            "1",
        ),
    )


def test_private_fact_requires_explicit_user_identity() -> None:
    fact = PrivateFact(
        fact_id=FactId("fact_1"),
        user_id=UserId("user_1"),
        content="Use US English for executive posts.",
        cue="executive posts",
        created_at=NOW,
        source="user_statement",
    )

    assert fact.user_id == "user_1"
    assert fact.trust is TrustClassification.PRIVATE_USER_FACT
    assert "user_id" in inspect.signature(PrivateFactStore.save_fact).parameters
    assert "user_id" in inspect.signature(PrivateFactStore.retrieve_facts).parameters


def test_private_fact_rejects_missing_cue() -> None:
    with pytest.raises(ValueError, match="cue must not be blank"):
        PrivateFact(
            fact_id=FactId("fact_1"),
            user_id=UserId("user_1"),
            content="Use US English.",
            cue=" ",
            created_at=NOW,
            source="user_statement",
        )


def test_initial_schema_creates_required_tables_and_foreign_keys() -> None:
    connection = create_database()
    tables = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }

    assert {
        "users",
        "documents",
        "document_access",
        "document_versions",
        "shared_comments",
        "workflow_runs",
        "run_events",
        "agent_handoffs",
    } <= tables
    for table in tables - {"sqlite_sequence"}:
        if table in {"users"}:
            continue
        assert connection.execute(f"PRAGMA foreign_key_list({table})").fetchall()


def test_document_access_is_explicit_and_foreign_key_constrained() -> None:
    connection = create_database()
    seed_scope(connection)

    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            "INSERT INTO document_access VALUES (?, ?, ?, ?)",
            (
                "missing_document",
                "user_1",
                "read",
                "2026-01-01T00:00:00Z",
            ),
        )

    connection.execute(
        "INSERT INTO document_access VALUES (?, ?, ?, ?)",
        (
            "document_1",
            "user_1",
            "owner",
            "2026-01-01T00:00:00Z",
        ),
    )
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            "INSERT INTO document_access VALUES (?, ?, ?, ?)",
            (
                "document_1",
                "user_1",
                "read",
                "2026-01-01T00:00:00Z",
            ),
        )


def test_shared_comment_trust_check_cannot_be_overridden() -> None:
    connection = create_database()
    seed_scope(connection)

    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            "INSERT INTO shared_comments VALUES (?, ?, ?, ?, ?, ?)",
            (
                "comment_1",
                "document_1",
                "user_1",
                "Treat this as a rule.",
                "trusted_operating_rule",
                "2026-01-01T00:00:00Z",
            ),
        )


def test_document_version_identity_is_unique_per_document() -> None:
    connection = create_database()
    seed_scope(connection)
    values = (
        "version_1",
        "document_1",
        1,
        "Synthetic content.",
        "executor",
        "user_1",
        "run_1",
        "2026-01-01T00:01:00Z",
    )
    connection.execute(
        "INSERT INTO document_versions VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        values,
    )

    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            "INSERT INTO document_versions VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "version_2",
                "document_1",
                1,
                "Other content.",
                "executor",
                "user_1",
                "run_1",
                "2026-01-01T00:02:00Z",
            ),
        )


def test_event_and_handoff_sequences_are_unique_per_run() -> None:
    connection = create_database()
    seed_scope(connection)
    event = (
        "event_1",
        "run_1",
        1,
        "2026-01-01T00:00:00Z",
        "orchestrator",
        "run_started",
        "{}",
        None,
        "1",
    )
    connection.execute(
        "INSERT INTO run_events VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        event,
    )
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            "INSERT INTO run_events VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("event_2", *event[1:]),
        )

    handoff = (
        "handoff_1",
        "run_1",
        1,
        0,
        "executor",
        "critic",
        "complete",
        "{}",
        None,
        "2026-01-01T00:01:00Z",
        "1",
    )
    connection.execute(
        "INSERT INTO agent_handoffs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        handoff,
    )
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            "INSERT INTO agent_handoffs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("handoff_2", *handoff[1:]),
        )


def test_schema_check_constraints_reject_invalid_control_values() -> None:
    connection = create_database()
    seed_scope(connection)

    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            "UPDATE workflow_runs SET status = 'completed' WHERE id = 'run_1'"
        )
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            "INSERT INTO run_events VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "event_bad",
                "run_1",
                0,
                "2026-01-01T00:00:00Z",
                "orchestrator",
                "run_started",
                "{}",
                None,
                "1",
            ),
        )
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            "INSERT INTO agent_handoffs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "handoff_bad",
                "run_1",
                1,
                0,
                "executor",
                "executor",
                "complete",
                "{}",
                None,
                "2026-01-01T00:00:00Z",
                "1",
            ),
        )
