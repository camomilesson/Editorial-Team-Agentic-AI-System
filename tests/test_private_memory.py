from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from editorial_agent.contracts.identity import FactId, UserId
from editorial_agent.contracts.storage import PrivateFact
from editorial_agent.errors import (
    PrivateMemoryError,
    UnsupportedMemorySchemaError,
)
from editorial_agent.private_memory import JsonPrivateFactStore

NOW = datetime(2026, 2, 1, tzinfo=UTC)


def fact(
    fact_id: str,
    user_id: str,
    cue: str,
    content: str,
    minute: int = 0,
) -> PrivateFact:
    return PrivateFact(
        fact_id=FactId(fact_id),
        user_id=UserId(user_id),
        content=content,
        cue=cue,
        created_at=NOW + timedelta(minutes=minute),
        source="synthetic_test",
    )


def test_private_fact_persists_across_store_instances_and_users(
    tmp_path: Path,
) -> None:
    root = tmp_path / "private-memory"
    store = JsonPrivateFactStore(root)
    saved = fact(
        "fact_1",
        "user_a",
        "executive posts",
        "Use US English for executive posts.",
    )
    store.save_fact(user_id=UserId("user_a"), fact=saved)

    reloaded = JsonPrivateFactStore(root)
    assert reloaded.retrieve_facts(
        user_id=UserId("user_a"),
        cue="executive post language",
    ) == (saved,)
    assert reloaded.retrieve_facts(
        user_id=UserId("user_b"),
        cue="executive post language",
    ) == ()
    assert sorted(path.name for path in root.iterdir()) == ["user_a.json"]
    assert not hasattr(reloaded, "retrieve_all_users")


def test_irrelevant_cue_is_excluded(tmp_path: Path) -> None:
    store = JsonPrivateFactStore(tmp_path)
    assert store.retrieve_facts(user_id=UserId("unused_user"), cue="anything") == ()


def test_private_fact_ranking_and_limit_are_deterministic(tmp_path: Path) -> None:
    store = JsonPrivateFactStore(tmp_path)
    first = fact("fact_1", "user_a", "executive posts language", "Use US English.", 1)
    second = fact("fact_2", "user_a", "executive posts", "Formal language.", 2)
    third = fact("fact_3", "user_a", "social posts", "Executive voice.", 3)
    for item in (third, second, first):
        store.save_fact(user_id=UserId("user_a"), fact=item)

    assert store.retrieve_facts(
        user_id=UserId("user_a"),
        cue="executive posts language",
        limit=2,
    ) == (first, second)


@pytest.mark.parametrize(
    "query",
    [
        "executive LinkedIn style",
        "LinkedIn post formatting",
        "LinkedIn closing preference",
        "recurring LinkedIn ending",
    ],
)
def test_linkedin_closing_fact_matches_reasonable_cue_variants(
    tmp_path: Path,
    query: str,
) -> None:
    store = JsonPrivateFactStore(tmp_path)
    closing = fact(
        "fact_closing",
        "user_a",
        "LinkedIn post footer closing ending format executive preference",
        "Use the user's durable closing sentence.",
    )
    store.save_fact(user_id=UserId("user_a"), fact=closing)

    assert store.retrieve_facts(user_id=UserId("user_a"), cue=query) == (
        closing,
    )


def test_mismatched_user_scope_is_rejected_without_content_leak(
    tmp_path: Path,
) -> None:
    store = JsonPrivateFactStore(tmp_path)
    private_content = "Synthetic confidential preference."

    with pytest.raises(PrivateMemoryError) as error:
        store.save_fact(
            user_id=UserId("user_b"),
            fact=fact("fact_1", "user_a", "preference", private_content),
        )

    assert private_content not in str(error.value)


def test_malformed_and_unsupported_files_fail_safely(tmp_path: Path) -> None:
    malformed_content = "not-json synthetic private content"
    (tmp_path / "user_a.json").write_text(malformed_content, encoding="utf-8")
    store = JsonPrivateFactStore(tmp_path)

    with pytest.raises(PrivateMemoryError) as error:
        store.get_all_facts(user_id=UserId("user_a"))
    assert malformed_content not in str(error.value)

    (tmp_path / "user_a.json").write_text(
        json.dumps({"schema_version": "999", "user_id": "user_a", "facts": []}),
        encoding="utf-8",
    )
    with pytest.raises(UnsupportedMemorySchemaError):
        store.get_all_facts(user_id=UserId("user_a"))


def test_failed_atomic_replace_preserves_existing_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = JsonPrivateFactStore(tmp_path)
    existing = fact("fact_1", "user_a", "posts", "Use US English.")
    store.save_fact(user_id=UserId("user_a"), fact=existing)
    original = (tmp_path / "user_a.json").read_text(encoding="utf-8")

    def fail_replace(source: object, destination: object) -> None:
        del source, destination
        raise OSError("synthetic replace failure")

    monkeypatch.setattr("editorial_agent.private_memory.os.replace", fail_replace)

    with pytest.raises(PrivateMemoryError, match="write failed"):
        store.save_fact(
            user_id=UserId("user_a"),
            fact=fact("fact_2", "user_a", "tone", "Use a neutral tone."),
        )
    assert (tmp_path / "user_a.json").read_text(encoding="utf-8") == original
