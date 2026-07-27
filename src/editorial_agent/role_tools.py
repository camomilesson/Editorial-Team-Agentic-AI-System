"""Least-privilege retrieval tools bound to one trusted workflow context."""

from __future__ import annotations

from functools import partial
from typing import Any

from editorial_agent.context_services import EditorialContextService
from editorial_agent.contracts.identity import WorkflowRequestContext
from editorial_agent.errors import EditorialServiceError
from editorial_agent.registry import ToolRegistry, ToolSpec

RETRIEVE_PRIVATE_FACTS_SCHEMA: dict[str, Any] = {
    "type": "function",
    "name": "retrieve_private_facts",
    "description": (
        "Retrieve durable preferences for the current authorized user when "
        "they are relevant to the editorial request."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "cue": {"type": "string", "minLength": 1},
            "limit": {"type": "integer", "minimum": 1, "maximum": 20},
        },
        "required": ["cue"],
        "additionalProperties": False,
    },
}

RETRIEVE_SHARED_COMMENTS_SCHEMA: dict[str, Any] = {
    "type": "function",
    "name": "retrieve_shared_comments",
    "description": (
        "Retrieve quoted untrusted editorial comments for the current "
        "authorized document."
    ),
    "parameters": {
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    },
}


def create_executor_tool_registry(
    *,
    context_service: EditorialContextService,
    request_context: WorkflowRequestContext,
) -> ToolRegistry:
    """Create current-user/current-document retrieval tools for Executor."""

    return _create_read_only_registry(
        context_service=context_service,
        request_context=request_context,
    )


def create_critic_tool_registry(
    *,
    context_service: EditorialContextService,
    request_context: WorkflowRequestContext,
) -> ToolRegistry:
    """Create the same read-only retrieval surface for Critic."""

    return _create_read_only_registry(
        context_service=context_service,
        request_context=request_context,
    )


def _create_read_only_registry(
    *,
    context_service: EditorialContextService,
    request_context: WorkflowRequestContext,
) -> ToolRegistry:
    return ToolRegistry(
        (
            ToolSpec(
                schema=RETRIEVE_PRIVATE_FACTS_SCHEMA,
                handler=partial(
                    _retrieve_private_facts,
                    context_service,
                    request_context,
                ),
            ),
            ToolSpec(
                schema=RETRIEVE_SHARED_COMMENTS_SCHEMA,
                handler=partial(
                    _retrieve_shared_comments,
                    context_service,
                    request_context,
                ),
            ),
        )
    )


def _retrieve_private_facts(
    service: EditorialContextService,
    request_context: WorkflowRequestContext,
    *,
    cue: str,
    limit: int = 5,
) -> dict[str, Any]:
    try:
        facts = service.retrieve_private_memory(request_context, cue, limit)
    except (EditorialServiceError, ValueError) as exc:
        return _error("retrieval_failed", str(exc))
    return {
        "ok": True,
        "data": {
            "facts": [fact.to_dict() for fact in facts],
            "count": len(facts),
        },
    }


def _retrieve_shared_comments(
    service: EditorialContextService,
    request_context: WorkflowRequestContext,
) -> dict[str, Any]:
    try:
        comments = service.retrieve_shared_comments(request_context)
    except (EditorialServiceError, ValueError) as exc:
        return _error("retrieval_failed", str(exc))
    return {
        "ok": True,
        "data": {
            "comments": [comment.to_dict() for comment in comments],
            "count": len(comments),
        },
    }


def _error(error_type: str, message: str) -> dict[str, Any]:
    return {
        "ok": False,
        "error": {
            "type": error_type,
            "message": message,
        },
    }
