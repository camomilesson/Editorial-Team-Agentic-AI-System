"""Atomic, user-separated JSON persistence for private facts."""

from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path

from editorial_agent.contracts.identity import UserId, validate_identifier
from editorial_agent.contracts.storage import PrivateFact
from editorial_agent.errors import (
    DuplicateEntityError,
    PrivateMemoryError,
    UnsupportedMemorySchemaError,
)

PRIVATE_MEMORY_SCHEMA_VERSION = "1"
_TOKEN_PATTERN = re.compile(r"[a-z0-9]+")


class JsonPrivateFactStore:
    """Persist append-only private facts in one file per validated user."""

    def __init__(self, root: Path) -> None:
        self._root = root.resolve(strict=False)

    def save_fact(self, *, user_id: UserId, fact: PrivateFact) -> None:
        """Atomically append one validated fact to its matching user file."""

        self._validate_scope(user_id, fact)
        facts = list(self.get_all_facts(user_id=user_id))
        if any(existing.fact_id == fact.fact_id for existing in facts):
            raise DuplicateEntityError("Private fact identifier already exists.")
        facts.append(fact)
        facts.sort(key=lambda item: (item.created_at, item.fact_id))
        self._write_user_file(user_id, facts)

    def get_all_facts(self, *, user_id: UserId) -> tuple[PrivateFact, ...]:
        """Return only the explicitly selected user's facts."""

        path = self._user_path(user_id)
        if not path.exists():
            return ()
        try:
            decoded = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise PrivateMemoryError("Private memory file is malformed.") from exc
        if not isinstance(decoded, dict):
            raise PrivateMemoryError("Private memory file is malformed.")
        if decoded.get("schema_version") != PRIVATE_MEMORY_SCHEMA_VERSION:
            raise UnsupportedMemorySchemaError(
                "Private memory schema version is unsupported."
            )
        if decoded.get("user_id") != user_id:
            raise PrivateMemoryError("Private memory scope is invalid.")
        raw_facts = decoded.get("facts")
        if not isinstance(raw_facts, list):
            raise PrivateMemoryError("Private memory file is malformed.")
        try:
            facts = tuple(PrivateFact.from_dict(item) for item in raw_facts)
        except (KeyError, TypeError, ValueError) as exc:
            raise PrivateMemoryError("Private memory file contains invalid facts.") from exc
        if any(fact.user_id != user_id for fact in facts):
            raise PrivateMemoryError("Private memory scope is invalid.")
        return tuple(sorted(facts, key=lambda item: (item.created_at, item.fact_id)))

    def retrieve_facts(
        self,
        *,
        user_id: UserId,
        cue: str,
        limit: int | None = None,
    ) -> tuple[PrivateFact, ...]:
        """Rank user-local facts by cue overlap, then content overlap.

        Matching is case-insensitive word-token overlap. Facts with no overlap
        are excluded. Ties use creation time and fact ID for stable ordering.
        """

        query_tokens = self._tokens(cue)
        if not query_tokens:
            return ()
        if limit is not None and (isinstance(limit, bool) or limit < 1):
            raise ValueError("limit must be a positive integer")

        ranked: list[tuple[int, int, PrivateFact]] = []
        for fact in self.get_all_facts(user_id=user_id):
            cue_overlap = len(query_tokens & self._tokens(fact.cue))
            content_overlap = len(query_tokens & self._tokens(fact.content))
            if cue_overlap == 0 and content_overlap == 0:
                continue
            ranked.append((cue_overlap, content_overlap, fact))

        ranked.sort(
            key=lambda item: (
                -item[0],
                -item[1],
                item[2].created_at,
                item[2].fact_id,
            )
        )
        facts = tuple(item[2] for item in ranked)
        return facts[:limit] if limit is not None else facts

    def _write_user_file(
        self,
        user_id: UserId,
        facts: list[PrivateFact],
    ) -> None:
        self._root.mkdir(parents=True, exist_ok=True)
        destination = self._user_path(user_id)
        document = {
            "schema_version": PRIVATE_MEMORY_SCHEMA_VERSION,
            "user_id": user_id,
            "facts": [fact.to_dict() for fact in facts],
        }
        try:
            serialized = json.dumps(
                document,
                ensure_ascii=False,
                sort_keys=True,
                indent=2,
                allow_nan=False,
            )
        except (TypeError, ValueError) as exc:
            raise PrivateMemoryError("Private memory data is not serializable.") from exc

        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self._root,
                prefix=f".{user_id}.",
                suffix=".tmp",
                delete=False,
            ) as temporary:
                temporary.write(serialized)
                temporary.write("\n")
                temporary.flush()
                os.fsync(temporary.fileno())
                temporary_path = Path(temporary.name)
            os.replace(temporary_path, destination)
        except OSError as exc:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
            raise PrivateMemoryError("Private memory write failed.") from exc

    def _user_path(self, user_id: UserId) -> Path:
        safe_user_id = validate_identifier(user_id, "user_id")
        path = (self._root / f"{safe_user_id}.json").resolve(strict=False)
        if not path.is_relative_to(self._root):
            raise PrivateMemoryError("Private memory scope is invalid.")
        return path

    @staticmethod
    def _validate_scope(user_id: UserId, fact: PrivateFact) -> None:
        validate_identifier(user_id, "user_id")
        if fact.user_id != user_id:
            raise PrivateMemoryError("Private fact does not match the current user.")

    @staticmethod
    def _tokens(value: str) -> set[str]:
        if not isinstance(value, str):
            raise ValueError("cue must be text")
        return set(_TOKEN_PATTERN.findall(value.casefold()))
