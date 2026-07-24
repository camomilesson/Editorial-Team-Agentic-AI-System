"""Reversible editorial tools and their provider-neutral schemas."""

from __future__ import annotations

from typing import Any, TypeAlias

from editorial_agent.storage import (
    ALLOWED_DRAFT_STAGES,
    DraftNotFoundError,
    InvalidDraftError,
    InvalidProjectIdError,
    InvalidVersionError,
    PressReleaseNotFoundError,
    ProjectStore,
    StorageError,
)

ToolOutput: TypeAlias = dict[str, Any]


READ_PRESS_RELEASE_SCHEMA: dict[str, Any] = {
    "type": "function",
    "name": "read_press_release",
    "description": (
        "Read the press release stored for a project. "
        "Use when the original source text is required before drafting, "
        "revising, or checking a LinkedIn post. "
        "Do not use when the complete press release is already available "
        "in the current context."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "project_id": {
                "type": "string",
                "pattern": "^[a-z0-9][a-z0-9_-]{0,63}$",
                "description": (
                    "The safe project identifier used inside the workspace."
                ),
            }
        },
        "required": ["project_id"],
        "additionalProperties": False,
    },
}


SAVE_LINKEDIN_DRAFT_SCHEMA: dict[str, Any] = {
    "type": "function",
    "name": "save_linkedin_draft",
    "description": (
        "Save a new version of a LinkedIn post without overwriting earlier "
        "versions. Use after creating or revising copy that must be "
        "persisted. Do not use merely to discuss wording, suggest options, "
        "or preview unsaved copy."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "project_id": {
                "type": "string",
                "pattern": "^[a-z0-9][a-z0-9_-]{0,63}$",
                "description": (
                    "The safe project identifier used inside the workspace."
                ),
            },
            "content": {
                "type": "string",
                "minLength": 1,
                "description": "The complete LinkedIn post to save.",
            },
            "stage": {
                "type": "string",
                "enum": list(ALLOWED_DRAFT_STAGES),
                "description": (
                    "The editorial stage of this saved post version."
                ),
            },
        },
        "required": [
            "project_id",
            "content",
            "stage",
        ],
        "additionalProperties": False,
    },
}


READ_LINKEDIN_DRAFT_SCHEMA: dict[str, Any] = {
    "type": "function",
    "name": "read_linkedin_draft",
    "description": (
        "Read a specific saved LinkedIn post version. "
        "Use when the exact persisted content is needed for verification, "
        "revision, or user review. "
        "Do not use when the relevant draft content is already available "
        "in the current context."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "project_id": {
                "type": "string",
                "pattern": "^[a-z0-9][a-z0-9_-]{0,63}$",
                "description": (
                    "The safe project identifier used inside the workspace."
                ),
            },
            "version": {
                "type": "integer",
                "minimum": 1,
                "description": "The saved draft version to read.",
            },
        },
        "required": [
            "project_id",
            "version",
        ],
        "additionalProperties": False,
    },
}


EDITORIAL_TOOL_SCHEMAS: tuple[dict[str, Any], ...] = (
    READ_PRESS_RELEASE_SCHEMA,
    SAVE_LINKEDIN_DRAFT_SCHEMA,
    READ_LINKEDIN_DRAFT_SCHEMA,
)


def read_press_release(
    store: ProjectStore,
    *,
    project_id: str,
) -> ToolOutput:
    """Read a stored press release and return a structured tool result."""

    try:
        content = store.read_press_release(project_id)
    except PressReleaseNotFoundError as exc:
        return _error(
            error_type="press_release_not_found",
            message=str(exc),
        )
    except InvalidProjectIdError as exc:
        return _error(
            error_type="invalid_project_id",
            message=str(exc),
        )
    except (StorageError, OSError) as exc:
        return _error(
            error_type="storage_error",
            message=str(exc),
        )

    return _success(
        {
            "project_id": project_id,
            "content": content,
        }
    )


def save_linkedin_draft(
    store: ProjectStore,
    *,
    project_id: str,
    content: str,
    stage: str,
) -> ToolOutput:
    """Save a new LinkedIn draft version and return structured metadata."""

    try:
        draft = store.save_linkedin_draft(
            project_id=project_id,
            content=content,
            stage=stage,
        )
    except InvalidProjectIdError as exc:
        return _error(
            error_type="invalid_project_id",
            message=str(exc),
        )
    except InvalidDraftError as exc:
        return _error(
            error_type="invalid_draft",
            message=str(exc),
        )
    except (StorageError, OSError) as exc:
        return _error(
            error_type="storage_error",
            message=str(exc),
        )

    return _success(
        {
            "project_id": draft.project_id,
            "version": draft.version,
            "stage": draft.stage,
            "content": draft.content,
        }
    )


def read_linkedin_draft(
    store: ProjectStore,
    *,
    project_id: str,
    version: int,
) -> ToolOutput:
    """Read one saved LinkedIn draft and return a structured result."""

    try:
        draft = store.read_linkedin_draft(
            project_id=project_id,
            version=version,
        )
    except InvalidProjectIdError as exc:
        return _error(
            error_type="invalid_project_id",
            message=str(exc),
        )
    except InvalidVersionError as exc:
        return _error(
            error_type="invalid_version",
            message=str(exc),
        )
    except DraftNotFoundError as exc:
        return _error(
            error_type="draft_not_found",
            message=str(exc),
        )
    except (StorageError, OSError) as exc:
        return _error(
            error_type="storage_error",
            message=str(exc),
        )

    return _success(
        {
            "project_id": draft.project_id,
            "version": draft.version,
            "stage": draft.stage,
            "content": draft.content,
        }
    )


def _success(data: dict[str, Any]) -> ToolOutput:
    """Build a structured successful tool result."""

    return {
        "ok": True,
        "data": data,
    }


def _error(
    *,
    error_type: str,
    message: str,
) -> ToolOutput:
    """Build a structured failed tool result."""

    return {
        "ok": False,
        "error": {
            "type": error_type,
            "message": message,
        },
    }
