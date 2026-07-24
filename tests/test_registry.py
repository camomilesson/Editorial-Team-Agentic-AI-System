from pathlib import Path
from typing import Any

import pytest

from editorial_agent.agent import AgentRunner, StopReason
from editorial_agent.models import (
    FakeModelClient,
    ModelResponse,
    ToolCall,
    ToolResult,
)
from editorial_agent.registry import (
    ToolOutputError,
    ToolRegistry,
    ToolSpec,
    create_editorial_registry,
)
from editorial_agent.storage import ProjectStore
from editorial_agent.tools import EDITORIAL_TOOL_SCHEMAS


def create_press_release(
    root: Path,
    project_id: str,
    content: str,
) -> None:
    source_dir = root / project_id / "source"
    source_dir.mkdir(parents=True)

    (source_dir / "press_release.md").write_text(
        content,
        encoding="utf-8",
    )


def test_editorial_registry_contains_three_tools(
    tmp_path: Path,
) -> None:
    registry = create_editorial_registry(
        ProjectStore(tmp_path)
    )

    assert registry.names == (
        "read_press_release",
        "save_linkedin_draft",
        "read_linkedin_draft",
    )
    assert registry.schemas == EDITORIAL_TOOL_SCHEMAS


def test_registry_executes_read_press_release(
    tmp_path: Path,
) -> None:
    create_press_release(
        tmp_path,
        "demo",
        "Public press release.",
    )
    registry = create_editorial_registry(
        ProjectStore(tmp_path)
    )

    result = registry.execute(
        ToolCall(
            call_id="call-1",
            name="read_press_release",
            arguments={
                "project_id": "demo",
            },
        )
    )

    assert result == {
        "ok": True,
        "data": {
            "project_id": "demo",
            "content": "Public press release.",
        },
    }


def test_registry_executes_save_linkedin_draft(
    tmp_path: Path,
) -> None:
    registry = create_editorial_registry(
        ProjectStore(tmp_path)
    )

    result = registry.execute(
        ToolCall(
            call_id="call-1",
            name="save_linkedin_draft",
            arguments={
                "project_id": "demo",
                "content": "A LinkedIn post.",
                "stage": "first_draft",
            },
        )
    )

    assert result["ok"] is True
    assert result["data"]["version"] == 1

    saved_path = (
        tmp_path
        / "demo"
        / "linkedin"
        / "001-first_draft.md"
    )

    assert saved_path.read_text(encoding="utf-8") == (
        "A LinkedIn post."
    )


def test_registry_executes_read_linkedin_draft(
    tmp_path: Path,
) -> None:
    store = ProjectStore(tmp_path)
    registry = create_editorial_registry(store)

    store.save_linkedin_draft(
        project_id="demo",
        content="Saved post.",
        stage="revision",
    )

    result = registry.execute(
        ToolCall(
            call_id="call-1",
            name="read_linkedin_draft",
            arguments={
                "project_id": "demo",
                "version": 1,
            },
        )
    )

    assert result == {
        "ok": True,
        "data": {
            "project_id": "demo",
            "version": 1,
            "stage": "revision",
            "content": "Saved post.",
        },
    }


def test_unknown_tool_returns_structured_error(
    tmp_path: Path,
) -> None:
    registry = create_editorial_registry(
        ProjectStore(tmp_path)
    )

    result = registry.execute(
        ToolCall(
            call_id="call-1",
            name="delete_everything",
            arguments={},
        )
    )

    assert result == {
        "ok": False,
        "error": {
            "type": "unknown_tool",
            "message": "Unknown tool: delete_everything",
        },
    }


def test_missing_required_argument_is_rejected(
    tmp_path: Path,
) -> None:
    registry = create_editorial_registry(
        ProjectStore(tmp_path)
    )

    result = registry.execute(
        ToolCall(
            call_id="call-1",
            name="read_press_release",
            arguments={},
        )
    )

    assert result["ok"] is False
    assert result["error"]["type"] == (
        "invalid_tool_arguments"
    )
    assert "project_id" in result["error"]["message"]


def test_invalid_stage_is_rejected_before_execution(
    tmp_path: Path,
) -> None:
    registry = create_editorial_registry(
        ProjectStore(tmp_path)
    )

    result = registry.execute(
        ToolCall(
            call_id="call-1",
            name="save_linkedin_draft",
            arguments={
                "project_id": "demo",
                "content": "Post.",
                "stage": "almost_final",
            },
        )
    )

    assert result["ok"] is False
    assert result["error"]["type"] == (
        "invalid_tool_arguments"
    )

    linkedin_dir = tmp_path / "demo" / "linkedin"

    assert not linkedin_dir.exists()


def test_additional_argument_is_rejected(
    tmp_path: Path,
) -> None:
    registry = create_editorial_registry(
        ProjectStore(tmp_path)
    )

    result = registry.execute(
        ToolCall(
            call_id="call-1",
            name="read_press_release",
            arguments={
                "project_id": "demo",
                "path": "../../secret",
            },
        )
    )

    assert result["ok"] is False
    assert result["error"]["type"] == (
        "invalid_tool_arguments"
    )


def test_invalid_version_is_rejected_by_schema(
    tmp_path: Path,
) -> None:
    registry = create_editorial_registry(
        ProjectStore(tmp_path)
    )

    result = registry.execute(
        ToolCall(
            call_id="call-1",
            name="read_linkedin_draft",
            arguments={
                "project_id": "demo",
                "version": 0,
            },
        )
    )

    assert result["ok"] is False
    assert result["error"]["type"] == (
        "invalid_tool_arguments"
    )


def test_invalid_arguments_do_not_call_handler() -> None:
    schema = {
        "type": "function",
        "name": "validated_tool",
        "description": "Validate before calling.",
        "parameters": {
            "type": "object",
            "properties": {
                "value": {"type": "integer"},
            },
            "required": ["value"],
            "additionalProperties": False,
        },
    }
    handler_called = False

    def handler(*, value: int) -> dict[str, Any]:
        nonlocal handler_called
        handler_called = True
        return {"ok": True, "data": {"value": value}}

    registry = ToolRegistry((ToolSpec(schema=schema, handler=handler),))

    result = registry.execute(
        ToolCall(
            call_id="call-1",
            name="validated_tool",
            arguments={"value": "not-an-integer"},
        )
    )

    assert result["ok"] is False
    assert result["error"]["type"] == "invalid_tool_arguments"
    assert handler_called is False


def test_registered_tools_are_reversible_by_default(
    tmp_path: Path,
) -> None:
    registry = create_editorial_registry(
        ProjectStore(tmp_path)
    )

    for name in registry.names:
        assert registry.requires_approval(name) is False


def test_duplicate_tool_names_are_rejected() -> None:
    schema = {
        "type": "function",
        "name": "duplicate_tool",
        "description": "A test tool.",
        "parameters": {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
    }

    def handler() -> dict[str, Any]:
        return {
            "ok": True,
            "data": {},
        }

    with pytest.raises(
        ValueError,
        match="Duplicate tool name",
    ):
        ToolRegistry(
            (
                ToolSpec(
                    schema=schema,
                    handler=handler,
                ),
                ToolSpec(
                    schema=schema,
                    handler=handler,
                ),
            )
        )


def test_malformed_tool_output_is_rejected() -> None:
    schema = {
        "type": "function",
        "name": "malformed_tool",
        "description": "Return malformed output for a test.",
        "parameters": {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
    }

    def handler() -> dict[str, Any]:
        return {
            "message": "Missing ok field",
        }

    registry = ToolRegistry(
        (
            ToolSpec(
                schema=schema,
                handler=handler,
            ),
        )
    )

    with pytest.raises(
        ToolOutputError,
        match="boolean 'ok'",
    ):
        registry.execute(
            ToolCall(
                call_id="call-1",
                name="malformed_tool",
                arguments={},
            )
        )


def test_non_json_handler_output_is_rejected() -> None:
    schema = {
        "type": "function",
        "name": "non_json_tool",
        "description": "Return non-JSON data for a test.",
        "parameters": {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
    }

    def handler() -> dict[str, Any]:
        return {
            "ok": True,
            "data": {"value": object()},
        }

    registry = ToolRegistry((ToolSpec(schema=schema, handler=handler),))

    with pytest.raises(
        ToolOutputError,
        match="non-JSON-serializable",
    ):
        registry.execute(
            ToolCall(
                call_id="call-1",
                name="non_json_tool",
                arguments={},
            )
        )


def test_unexpected_handler_exception_is_not_swallowed() -> None:
    schema = {
        "type": "function",
        "name": "broken_tool",
        "description": "Raise an exception for a test.",
        "parameters": {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
    }

    def handler() -> dict[str, Any]:
        raise RuntimeError("disk unavailable")

    registry = ToolRegistry(
        (
            ToolSpec(
                schema=schema,
                handler=handler,
            ),
        )
    )

    with pytest.raises(
        RuntimeError,
        match="disk unavailable",
    ):
        registry.execute(
            ToolCall(
                call_id="call-1",
                name="broken_tool",
                arguments={},
            )
        )


def test_handler_exception_reaches_agent_tool_error_branch() -> None:
    schema = {
        "type": "function",
        "name": "broken_tool",
        "description": "Raise an exception for a test.",
        "parameters": {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
    }

    def handler() -> dict[str, Any]:
        raise RuntimeError("disk unavailable")

    registry = ToolRegistry((ToolSpec(schema=schema, handler=handler),))
    model = FakeModelClient(
        (
            ModelResponse(
                text="",
                tool_calls=(
                    ToolCall(
                        call_id="call-1",
                        name="broken_tool",
                        arguments={},
                    ),
                ),
                continuation_token="interaction-1",
            ),
            ModelResponse(
                text="The tool failed.",
                tool_calls=(),
                continuation_token="interaction-2",
            ),
        )
    )

    result = AgentRunner(model=model, executor=registry).run(
        "Run the tool.",
        tools=registry.schemas,
    )

    assert result.stop_reason == StopReason.ANSWERED
    assert model.requests[1].input == (
        ToolResult(
            call_id="call-1",
            name="broken_tool",
            result={
                "ok": False,
                "error": {
                    "type": "tool_execution_failed",
                    "message": "disk unavailable",
                },
            },
        ),
    )
    assert any(event.kind == "tool_error" for event in result.trace)


def test_registry_plugs_into_agent_runner(
    tmp_path: Path,
) -> None:
    create_press_release(
        tmp_path,
        "demo",
        "A public press release.",
    )

    registry = create_editorial_registry(
        ProjectStore(tmp_path)
    )

    model = FakeModelClient(
        (
            ModelResponse(
                text="",
                tool_calls=(
                    ToolCall(
                        call_id="call-1",
                        name="read_press_release",
                        arguments={
                            "project_id": "demo",
                        },
                    ),
                ),
                continuation_token="interaction-1",
            ),
            ModelResponse(
                text="The release was read.",
                tool_calls=(),
                continuation_token="interaction-2",
            ),
        )
    )

    runner = AgentRunner(
        model=model,
        executor=registry,
        max_steps=4,
    )

    result = runner.run(
        "Read the press release.",
        tools=registry.schemas,
    )

    assert result.stop_reason == StopReason.ANSWERED
    assert result.text == "The release was read."
    assert result.steps == 2

    assert model.requests[0].tools == registry.schemas
    second_request = model.requests[1]

    assert second_request.input == (
        ToolResult(
            call_id="call-1",
            name="read_press_release",
            result={
                "ok": True,
                "data": {
                    "project_id": "demo",
                    "content": "A public press release.",
                },
            },
        ),
    )
