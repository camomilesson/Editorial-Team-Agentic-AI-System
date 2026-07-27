"""SQLite implementation of the structured domain repository."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime

from editorial_agent.contracts.common import (
    parse_utc_timestamp,
    require_utc_timestamp,
    timestamp_to_json,
)
from editorial_agent.contracts.events import RunEvent
from editorial_agent.contracts.handoffs import AgentHandoff
from editorial_agent.contracts.identity import (
    CommentId,
    DocumentId,
    DocumentVersionId,
    RunId,
    UserId,
    WorkflowRequestContext,
    validate_identifier,
)
from editorial_agent.contracts.monitor import (
    CompletedRunBundle,
    DocumentVersionSnapshot,
    MonitorReferenceDocument,
    WorkflowRunRecord,
)
from editorial_agent.contracts.storage import (
    AccessLevel,
    DocumentRecord,
    DocumentVersionRecord,
    UserRecord,
)
from editorial_agent.contracts.trust import SharedComment
from editorial_agent.contracts.workflow import AgentRole, RunStatus
from editorial_agent.errors import (
    AuthorizationError,
    DuplicateEntityError,
    EntityNotFoundError,
    InvalidAccessGrantError,
    PersistedDataError,
    SequenceConflictError,
)
from editorial_agent.sqlite_database import SQLiteDatabase

_ACCESS_RANK = {
    AccessLevel.READ: 1,
    AccessLevel.EDIT: 2,
    AccessLevel.OWNER: 3,
}


class SQLiteDomainRepository:
    """Persist structured editorial state with explicit authorization."""

    def __init__(self, database: SQLiteDatabase) -> None:
        self._database = database

    def create_user(self, *, user: UserRecord) -> None:
        try:
            with self._database.transaction() as connection:
                connection.execute(
                    "INSERT INTO users (id, display_name, created_at) VALUES (?, ?, ?)",
                    (
                        user.user_id,
                        user.display_name,
                        timestamp_to_json(user.created_at),
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise DuplicateEntityError("User identifier already exists.") from exc

    def get_user(self, *, user_id: UserId) -> UserRecord:
        validate_identifier(user_id, "user_id")
        with self._database.connect() as connection:
            row = connection.execute(
                "SELECT id, display_name, created_at FROM users WHERE id = ?",
                (user_id,),
            ).fetchone()
        if row is None:
            raise EntityNotFoundError("User was not found.")
        return self._user_from_row(row)

    def create_document(self, *, document: DocumentRecord) -> None:
        try:
            with self._database.transaction() as connection:
                if not self._user_exists(connection, document.owner_user_id):
                    raise EntityNotFoundError("Document owner was not found.")
                timestamp = timestamp_to_json(document.created_at)
                connection.execute(
                    """
                    INSERT INTO documents (id, owner_user_id, title, created_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        document.document_id,
                        document.owner_user_id,
                        document.title,
                        timestamp,
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO document_access
                        (document_id, user_id, access_level, created_at)
                    VALUES (?, ?, 'owner', ?)
                    """,
                    (document.document_id, document.owner_user_id, timestamp),
                )
        except sqlite3.IntegrityError as exc:
            raise DuplicateEntityError("Document identifier already exists.") from exc

    def get_document(
        self,
        *,
        user_id: UserId,
        document_id: DocumentId,
    ) -> DocumentRecord:
        with self._database.connect() as connection:
            self._require_access(
                connection,
                user_id=user_id,
                document_id=document_id,
                minimum=AccessLevel.READ,
            )
            row = connection.execute(
                """
                SELECT id, owner_user_id, title, created_at
                FROM documents
                WHERE id = ?
                """,
                (document_id,),
            ).fetchone()
        if row is None:
            raise EntityNotFoundError("Document was not found.")
        return self._document_from_row(row)

    def user_can_access_document(
        self,
        *,
        user_id: UserId,
        document_id: DocumentId,
    ) -> bool:
        validate_identifier(user_id, "user_id")
        validate_identifier(document_id, "document_id")
        with self._database.connect() as connection:
            return self._access_level(connection, user_id, document_id) is not None

    def user_can_edit_document(
        self,
        *,
        user_id: UserId,
        document_id: DocumentId,
    ) -> bool:
        """Return whether the explicit access record permits mutation."""

        validate_identifier(user_id, "user_id")
        validate_identifier(document_id, "document_id")
        with self._database.connect() as connection:
            level = self._access_level(connection, user_id, document_id)
        return level is not None and _ACCESS_RANK[level] >= _ACCESS_RANK[AccessLevel.EDIT]

    def grant_document_access(
        self,
        *,
        grantor_user_id: UserId,
        document_id: DocumentId,
        grantee_user_id: UserId,
        access_level: AccessLevel,
        created_at: datetime,
    ) -> None:
        require_utc_timestamp(created_at, "created_at")
        if access_level is AccessLevel.OWNER:
            raise InvalidAccessGrantError("Ownership cannot be granted as collaboration.")
        try:
            with self._database.transaction() as connection:
                self._require_access(
                    connection,
                    user_id=grantor_user_id,
                    document_id=document_id,
                    minimum=AccessLevel.OWNER,
                )
                if not self._user_exists(connection, grantee_user_id):
                    raise EntityNotFoundError("Access recipient was not found.")
                owner_row = connection.execute(
                    "SELECT owner_user_id FROM documents WHERE id = ?",
                    (document_id,),
                ).fetchone()
                if owner_row["owner_user_id"] == grantee_user_id:
                    raise InvalidAccessGrantError(
                        "Document owner access cannot be changed."
                    )
                connection.execute(
                    """
                    INSERT INTO document_access
                        (document_id, user_id, access_level, created_at)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(document_id, user_id) DO UPDATE SET
                        access_level = excluded.access_level,
                        created_at = excluded.created_at
                    """,
                    (
                        document_id,
                        grantee_user_id,
                        access_level.value,
                        timestamp_to_json(created_at),
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise InvalidAccessGrantError("Document access grant failed.") from exc

    def create_document_version(
        self,
        *,
        user_id: UserId,
        version: DocumentVersionRecord,
    ) -> DocumentVersionRecord:
        if version.created_by_user_id not in {None, user_id}:
            raise AuthorizationError("Version creator does not match the current user.")
        try:
            with self._database.transaction(immediate=True) as connection:
                self._require_access(
                    connection,
                    user_id=user_id,
                    document_id=version.document_id,
                    minimum=AccessLevel.EDIT,
                )
                if version.run_id is not None:
                    self._require_run_scope(
                        connection,
                        run_id=version.run_id,
                        user_id=user_id,
                        document_id=version.document_id,
                    )
                next_number = connection.execute(
                    """
                    SELECT COALESCE(MAX(version_number), 0) + 1
                    FROM document_versions
                    WHERE document_id = ?
                    """,
                    (version.document_id,),
                ).fetchone()[0]
                if version.version_number != next_number:
                    raise DuplicateEntityError(
                        "Document version number is not the next available number."
                    )
                connection.execute(
                    """
                    INSERT INTO document_versions (
                        id, document_id, version_number, content,
                        created_by_actor, created_by_user_id, run_id, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        version.document_version_id,
                        version.document_id,
                        version.version_number,
                        version.content,
                        version.created_by_actor.value,
                        version.created_by_user_id,
                        version.run_id,
                        timestamp_to_json(version.created_at),
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise DuplicateEntityError("Document version already exists.") from exc
        return version

    def get_document_version(
        self,
        *,
        user_id: UserId,
        document_id: DocumentId,
        version_number: int,
    ) -> DocumentVersionRecord:
        if isinstance(version_number, bool) or version_number < 1:
            raise ValueError("version_number must be a positive integer")
        with self._database.connect() as connection:
            self._require_access(
                connection,
                user_id=user_id,
                document_id=document_id,
                minimum=AccessLevel.READ,
            )
            row = connection.execute(
                """
                SELECT * FROM document_versions
                WHERE document_id = ? AND version_number = ?
                """,
                (document_id, version_number),
            ).fetchone()
        if row is None:
            raise EntityNotFoundError("Document version was not found.")
        return self._version_from_row(row)

    def get_latest_document_version(
        self,
        *,
        user_id: UserId,
        document_id: DocumentId,
    ) -> DocumentVersionRecord:
        with self._database.connect() as connection:
            self._require_access(
                connection,
                user_id=user_id,
                document_id=document_id,
                minimum=AccessLevel.READ,
            )
            row = connection.execute(
                """
                SELECT * FROM document_versions
                WHERE document_id = ?
                ORDER BY version_number DESC
                LIMIT 1
                """,
                (document_id,),
            ).fetchone()
        if row is None:
            raise EntityNotFoundError("Document has no versions.")
        return self._version_from_row(row)

    def add_shared_comment(
        self,
        *,
        user_id: UserId,
        comment_id: CommentId,
        document_id: DocumentId,
        body: str,
        created_at: datetime,
    ) -> None:
        comment = SharedComment(
            comment_id=comment_id,
            document_id=document_id,
            author_user_id=user_id,
            body=body,
            created_at=created_at,
        )
        try:
            with self._database.transaction() as connection:
                self._require_access(
                    connection,
                    user_id=user_id,
                    document_id=document_id,
                    minimum=AccessLevel.READ,
                )
                connection.execute(
                    """
                    INSERT INTO shared_comments
                        (id, document_id, author_user_id, body, trust, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        comment.comment_id,
                        comment.document_id,
                        comment.author_user_id,
                        comment.body,
                        comment.trust.value,
                        timestamp_to_json(comment.created_at),
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise DuplicateEntityError("Shared comment identifier already exists.") from exc

    def list_shared_comments(
        self,
        *,
        user_id: UserId,
        document_id: DocumentId,
    ) -> tuple[SharedComment, ...]:
        with self._database.connect() as connection:
            self._require_access(
                connection,
                user_id=user_id,
                document_id=document_id,
                minimum=AccessLevel.READ,
            )
            rows = connection.execute(
                """
                SELECT id, document_id, author_user_id, body, trust, created_at
                FROM shared_comments
                WHERE document_id = ?
                ORDER BY created_at, id
                """,
                (document_id,),
            ).fetchall()
        try:
            return tuple(
                SharedComment.from_dict(
                    {
                        "comment_id": row["id"],
                        "document_id": row["document_id"],
                        "author_user_id": row["author_user_id"],
                        "body": row["body"],
                        "trust": row["trust"],
                        "created_at": row["created_at"],
                    }
                )
                for row in rows
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise PersistedDataError("Stored shared comment is invalid.") from exc

    def create_run(self, *, context: WorkflowRequestContext) -> None:
        try:
            with self._database.transaction() as connection:
                self._require_access(
                    connection,
                    user_id=context.user_id,
                    document_id=context.document_id,
                    minimum=AccessLevel.READ,
                )
                connection.execute(
                    """
                    INSERT INTO workflow_runs (
                        id, user_id, session_id, document_id, request, status,
                        started_at, completed_at, schema_version
                    ) VALUES (?, ?, ?, ?, ?, 'running', ?, NULL, '1')
                    """,
                    (
                        context.run_id,
                        context.user_id,
                        context.session_id,
                        context.document_id,
                        context.request,
                        timestamp_to_json(context.requested_at),
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise DuplicateEntityError("Workflow run identifier already exists.") from exc

    def run_exists_for_scope(
        self,
        *,
        run_id: RunId,
        user_id: UserId,
        document_id: DocumentId,
    ) -> bool:
        with self._database.connect() as connection:
            row = connection.execute(
                """
                SELECT 1 FROM workflow_runs
                WHERE id = ? AND user_id = ? AND document_id = ?
                """,
                (run_id, user_id, document_id),
            ).fetchone()
        return row is not None

    def set_run_status(
        self,
        *,
        run_id: RunId,
        user_id: UserId,
        document_id: DocumentId,
        status: RunStatus,
        completed_at: datetime | None,
    ) -> None:
        if completed_at is not None:
            require_utc_timestamp(completed_at, "completed_at")
        if status.is_terminal != (completed_at is not None):
            raise ValueError("Terminal status and completed_at must agree.")
        with self._database.transaction() as connection:
            self._require_run_scope(
                connection,
                run_id=run_id,
                user_id=user_id,
                document_id=document_id,
            )
            connection.execute(
                """
                UPDATE workflow_runs
                SET status = ?, completed_at = ?
                WHERE id = ?
                """,
                (
                    status.value,
                    timestamp_to_json(completed_at) if completed_at else None,
                    run_id,
                ),
            )

    def append_event(
        self,
        *,
        user_id: UserId,
        document_id: DocumentId,
        event: RunEvent,
    ) -> None:
        try:
            with self._database.transaction() as connection:
                self._require_run_scope(
                    connection,
                    run_id=event.run_id,
                    user_id=user_id,
                    document_id=document_id,
                )
                self._require_version_reference(
                    connection,
                    document_id=document_id,
                    version_id=event.document_version_id,
                )
                connection.execute(
                    """
                    INSERT INTO run_events (
                        id, run_id, sequence, timestamp, actor, event_type,
                        payload_json, document_version_id, schema_version
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event.event_id,
                        event.run_id,
                        event.sequence,
                        timestamp_to_json(event.timestamp),
                        event.actor.value,
                        event.event_type.value,
                        self._stable_json(event.payload),
                        event.document_version_id,
                        event.schema_version,
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise SequenceConflictError("Run event sequence or identifier conflicts.") from exc

    def append_handoff(
        self,
        *,
        user_id: UserId,
        document_id: DocumentId,
        handoff: AgentHandoff,
    ) -> None:
        try:
            with self._database.transaction() as connection:
                self._require_run_scope(
                    connection,
                    run_id=handoff.run_id,
                    user_id=user_id,
                    document_id=document_id,
                )
                self._require_version_reference(
                    connection,
                    document_id=document_id,
                    version_id=handoff.document_version_id,
                )
                connection.execute(
                    """
                    INSERT INTO agent_handoffs (
                        id, run_id, sequence, round_number, from_agent, to_agent,
                        status, payload_json, document_version_id, created_at,
                        schema_version
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        handoff.handoff_id,
                        handoff.run_id,
                        handoff.sequence,
                        handoff.round_number,
                        handoff.from_agent.value,
                        handoff.to_agent.value,
                        handoff.status.value,
                        self._stable_json(handoff.payload),
                        handoff.document_version_id,
                        timestamp_to_json(handoff.created_at),
                        handoff.schema_version,
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise SequenceConflictError(
                "Agent handoff sequence or identifier conflicts."
            ) from exc

    def get_workflow_run(
        self,
        *,
        run_id: RunId,
        user_id: UserId,
        document_id: DocumentId,
    ) -> WorkflowRunRecord:
        with self._database.connect() as connection:
            self._require_run_scope(
                connection,
                run_id=run_id,
                user_id=user_id,
                document_id=document_id,
            )
            row = connection.execute(
                "SELECT * FROM workflow_runs WHERE id = ?",
                (run_id,),
            ).fetchone()
        return self._run_from_row(row)

    def list_run_events(
        self,
        *,
        run_id: RunId,
        user_id: UserId,
        document_id: DocumentId,
    ) -> tuple[RunEvent, ...]:
        with self._database.connect() as connection:
            self._require_run_scope(
                connection,
                run_id=run_id,
                user_id=user_id,
                document_id=document_id,
            )
            rows = connection.execute(
                "SELECT * FROM run_events WHERE run_id = ? ORDER BY sequence",
                (run_id,),
            ).fetchall()
        try:
            return tuple(
                RunEvent.from_dict(
                    {
                        "schema_version": row["schema_version"],
                        "event_id": row["id"],
                        "run_id": row["run_id"],
                        "sequence": row["sequence"],
                        "timestamp": row["timestamp"],
                        "actor": row["actor"],
                        "event_type": row["event_type"],
                        "payload": json.loads(row["payload_json"]),
                        "document_version_id": row["document_version_id"],
                    }
                )
                for row in rows
            )
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            raise PersistedDataError("Stored run event is invalid.") from exc

    def list_run_handoffs(
        self,
        *,
        run_id: RunId,
        user_id: UserId,
        document_id: DocumentId,
    ) -> tuple[AgentHandoff, ...]:
        with self._database.connect() as connection:
            self._require_run_scope(
                connection,
                run_id=run_id,
                user_id=user_id,
                document_id=document_id,
            )
            rows = connection.execute(
                "SELECT * FROM agent_handoffs WHERE run_id = ? ORDER BY sequence",
                (run_id,),
            ).fetchall()
        try:
            return tuple(
                AgentHandoff.from_dict(
                    {
                        "schema_version": row["schema_version"],
                        "handoff_id": row["id"],
                        "run_id": row["run_id"],
                        "sequence": row["sequence"],
                        "round_number": row["round_number"],
                        "from_agent": row["from_agent"],
                        "to_agent": row["to_agent"],
                        "status": row["status"],
                        "payload": json.loads(row["payload_json"]),
                        "document_version_id": row["document_version_id"],
                        "created_at": row["created_at"],
                    }
                )
                for row in rows
            )
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            raise PersistedDataError("Stored agent handoff is invalid.") from exc

    def build_completed_run_bundle(
        self,
        *,
        run_id: RunId,
        user_id: UserId,
        document_id: DocumentId,
        operating_rules: MonitorReferenceDocument,
        critic_rubric: MonitorReferenceDocument,
    ) -> CompletedRunBundle:
        """Collect a terminal run without implementing Monitor judgment."""

        run = self.get_workflow_run(
            run_id=run_id,
            user_id=user_id,
            document_id=document_id,
        )
        events = self.list_run_events(
            run_id=run_id,
            user_id=user_id,
            document_id=document_id,
        )
        handoffs = self.list_run_handoffs(
            run_id=run_id,
            user_id=user_id,
            document_id=document_id,
        )
        with self._database.connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM document_versions
                WHERE run_id = ? AND document_id = ?
                ORDER BY version_number
                """,
                (run_id, document_id),
            ).fetchall()
        versions = tuple(
            DocumentVersionSnapshot(
                document_version_id=DocumentVersionId(row["id"]),
                document_id=DocumentId(row["document_id"]),
                version_number=row["version_number"],
                content=row["content"],
                created_by_actor=AgentRole(row["created_by_actor"]),
                created_at=parse_utc_timestamp(row["created_at"], "created_at"),
            )
            for row in rows
        )
        return CompletedRunBundle(
            run=run,
            events=events,
            handoffs=handoffs,
            document_versions=versions,
            operating_rules=operating_rules,
            critic_rubric=critic_rubric,
        )

    @staticmethod
    def _stable_json(payload: dict[str, object]) -> str:
        try:
            return json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
        except (TypeError, ValueError) as exc:
            raise PersistedDataError("Persisted payload is not JSON-compatible.") from exc

    @staticmethod
    def _user_exists(connection: sqlite3.Connection, user_id: UserId) -> bool:
        return (
            connection.execute(
                "SELECT 1 FROM users WHERE id = ?",
                (user_id,),
            ).fetchone()
            is not None
        )

    @staticmethod
    def _access_level(
        connection: sqlite3.Connection,
        user_id: UserId,
        document_id: DocumentId,
    ) -> AccessLevel | None:
        row = connection.execute(
            """
            SELECT access_level FROM document_access
            WHERE user_id = ? AND document_id = ?
            """,
            (user_id, document_id),
        ).fetchone()
        return AccessLevel(row["access_level"]) if row else None

    def _require_access(
        self,
        connection: sqlite3.Connection,
        *,
        user_id: UserId,
        document_id: DocumentId,
        minimum: AccessLevel,
    ) -> None:
        validate_identifier(user_id, "user_id")
        validate_identifier(document_id, "document_id")
        if not self._user_exists(connection, user_id):
            raise EntityNotFoundError("User was not found.")
        document_exists = connection.execute(
            "SELECT 1 FROM documents WHERE id = ?",
            (document_id,),
        ).fetchone()
        if document_exists is None:
            raise EntityNotFoundError("Document was not found.")
        level = self._access_level(connection, user_id, document_id)
        if level is None or _ACCESS_RANK[level] < _ACCESS_RANK[minimum]:
            raise AuthorizationError("User is not authorized for this document.")

    def _require_run_scope(
        self,
        connection: sqlite3.Connection,
        *,
        run_id: RunId,
        user_id: UserId,
        document_id: DocumentId,
    ) -> None:
        validate_identifier(run_id, "run_id")
        self._require_access(
            connection,
            user_id=user_id,
            document_id=document_id,
            minimum=AccessLevel.READ,
        )
        row = connection.execute(
            """
            SELECT 1 FROM workflow_runs
            WHERE id = ? AND user_id = ? AND document_id = ?
            """,
            (run_id, user_id, document_id),
        ).fetchone()
        if row is None:
            raise EntityNotFoundError("Workflow run was not found for this scope.")

    @staticmethod
    def _require_version_reference(
        connection: sqlite3.Connection,
        *,
        document_id: DocumentId,
        version_id: DocumentVersionId | None,
    ) -> None:
        if version_id is None:
            return
        row = connection.execute(
            """
            SELECT 1 FROM document_versions
            WHERE id = ? AND document_id = ?
            """,
            (version_id, document_id),
        ).fetchone()
        if row is None:
            raise EntityNotFoundError("Referenced document version was not found.")

    @staticmethod
    def _user_from_row(row: sqlite3.Row) -> UserRecord:
        return UserRecord(
            user_id=UserId(row["id"]),
            display_name=row["display_name"],
            created_at=parse_utc_timestamp(row["created_at"], "created_at"),
        )

    @staticmethod
    def _document_from_row(row: sqlite3.Row) -> DocumentRecord:
        return DocumentRecord(
            document_id=DocumentId(row["id"]),
            owner_user_id=UserId(row["owner_user_id"]),
            title=row["title"],
            created_at=parse_utc_timestamp(row["created_at"], "created_at"),
        )

    @staticmethod
    def _version_from_row(row: sqlite3.Row) -> DocumentVersionRecord:
        try:
            return DocumentVersionRecord(
                document_version_id=DocumentVersionId(row["id"]),
                document_id=DocumentId(row["document_id"]),
                version_number=row["version_number"],
                content=row["content"],
                created_by_actor=AgentRole(row["created_by_actor"]),
                created_by_user_id=(
                    UserId(row["created_by_user_id"])
                    if row["created_by_user_id"] is not None
                    else None
                ),
                run_id=RunId(row["run_id"]) if row["run_id"] is not None else None,
                created_at=parse_utc_timestamp(row["created_at"], "created_at"),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise PersistedDataError("Stored document version is invalid.") from exc

    @staticmethod
    def _run_from_row(row: sqlite3.Row) -> WorkflowRunRecord:
        try:
            return WorkflowRunRecord(
                run_id=RunId(row["id"]),
                user_id=UserId(row["user_id"]),
                session_id=row["session_id"],
                document_id=DocumentId(row["document_id"]),
                request=row["request"],
                status=RunStatus(row["status"]),
                started_at=parse_utc_timestamp(row["started_at"], "started_at"),
                completed_at=(
                    parse_utc_timestamp(row["completed_at"], "completed_at")
                    if row["completed_at"] is not None
                    else None
                ),
                schema_version=row["schema_version"],
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise PersistedDataError("Stored workflow run is invalid.") from exc
