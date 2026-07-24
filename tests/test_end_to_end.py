from pathlib import Path

from editorial_agent.agent import AgentRunner, StopReason
from editorial_agent.approval import (
    AlwaysApproveGate,
    AlwaysDeclineGate,
)
from editorial_agent.models import (
    FakeModelClient,
    ModelResponse,
    ToolCall,
)
from editorial_agent.publication import PublicationOutbox
from editorial_agent.registry import create_editorial_registry
from editorial_agent.storage import ProjectStore

POST_CONTENT = """A better route is not always the fastest one.

Northstar Maps has launched CoolRoute, a feature designed to help pedestrians
find more comfortable routes during extreme heat.

It considers factors such as tree cover, shaded streets, drinking fountains,
indoor passageways, and cooling centers.

A suggested route may take a few minutes longer, but reduce the time spent in direct sunlight.

The feature is initially being tested in Barcelona, Madrid, Valencia, Seville, and Lisbon.
Navigation should respond not only to where people are going,
but also to the conditions in which they are travelling."""


def write_press_release(
    workspace: Path,
    *,
    project_id: str,
) -> None:
    source_directory = (
        workspace
        / project_id
        / "source"
    )
    source_directory.mkdir(
        parents=True
    )

    (
        source_directory
        / "press_release.md"
    ).write_text(
        (
            "# Northstar Maps Launches CoolRoute\n\n"
            "Northstar Maps launched CoolRoute, a "
            "walking-navigation feature for periods "
            "of extreme heat. It considers tree cover, "
            "drinking fountains, shaded streets, "
            "indoor passageways, and cooling centers. "
            "It is initially being tested in Barcelona, "
            "Madrid, Valencia, Seville, and Lisbon."
        ),
        encoding="utf-8",
    )


def assert_subsequence(
    expected: list[str],
    actual: list[str],
) -> None:
    """Assert that expected values appear in order."""

    position = 0

    for value in actual:
        if (
            position < len(expected)
            and value == expected[position]
        ):
            position += 1

    assert position == len(expected)


def make_approved_model() -> FakeModelClient:
    return FakeModelClient(
        (
            ModelResponse(
                text="",
                tool_calls=(
                    ToolCall(
                        call_id="read-source",
                        name="read_press_release",
                        arguments={
                            "project_id": "demo",
                        },
                    ),
                ),
                continuation_token="turn-1",
            ),
            ModelResponse(
                text="",
                tool_calls=(
                    ToolCall(
                        call_id="save-draft",
                        name="save_linkedin_draft",
                        arguments={
                            "project_id": "demo",
                            "content": POST_CONTENT,
                            "stage": "first_draft",
                        },
                    ),
                ),
                continuation_token="turn-2",
            ),
            ModelResponse(
                text="",
                tool_calls=(
                    ToolCall(
                        call_id="verify-draft",
                        name="read_linkedin_draft",
                        arguments={
                            "project_id": "demo",
                            "version": 1,
                        },
                    ),
                ),
                continuation_token="turn-3",
            ),
            ModelResponse(
                text="",
                tool_calls=(
                    ToolCall(
                        call_id="save-final",
                        name="save_linkedin_draft",
                        arguments={
                            "project_id": "demo",
                            "content": POST_CONTENT,
                            "stage": "final",
                        },
                    ),
                ),
                continuation_token="turn-4",
            ),
            ModelResponse(
                text="",
                tool_calls=(
                    ToolCall(
                        call_id="publish-final",
                        name="publish_linkedin_post",
                        arguments={
                            "project_id": "demo",
                            "version": 2,
                            "visibility": "public",
                        },
                    ),
                ),
                continuation_token="turn-5",
            ),
            ModelResponse(
                text="Published final version 2.",
                tool_calls=(),
                continuation_token="turn-6",
            ),
        )
    )


def test_complete_approved_editorial_workflow(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    published = tmp_path / "published"

    write_press_release(
        workspace,
        project_id="demo",
    )

    store = ProjectStore(workspace)
    outbox = PublicationOutbox(
        root=published,
        store=store,
    )
    registry = create_editorial_registry(
        store,
        outbox,
    )
    model = make_approved_model()

    runner = AgentRunner(
        model=model,
        executor=registry,
        approval_gate=AlwaysApproveGate(),
        max_steps=8,
    )

    result = runner.run(
        "Create, verify, finalize, and publish the post.",
        tools=registry.schemas,
    )

    assert result.stop_reason == StopReason.ANSWERED
    assert result.text == (
        "Published final version 2."
    )
    assert result.steps == 6

    source_path = (
        workspace
        / "demo"
        / "source"
        / "press_release.md"
    )
    draft_path = (
        workspace
        / "demo"
        / "linkedin"
        / "001-first_draft.md"
    )
    final_path = (
        workspace
        / "demo"
        / "linkedin"
        / "002-final.md"
    )
    published_path = (
        published
        / "demo"
        / "002-public.md"
    )

    assert source_path.exists()
    assert draft_path.exists()
    assert final_path.exists()
    assert published_path.exists()

    assert draft_path.read_text(
        encoding="utf-8"
    ) == POST_CONTENT
    assert final_path.read_text(
        encoding="utf-8"
    ) == POST_CONTENT
    assert published_path.read_text(
        encoding="utf-8"
    ) == POST_CONTENT

    event_kinds = [
        event.kind
        for event in result.trace
    ]

    assert_subsequence(
        [
            "tool_request",
            "tool_result",
            "tool_request",
            "tool_result",
            "tool_request",
            "tool_result",
            "tool_request",
            "tool_result",
            "tool_request",
            "approval_requested",
            "approval_granted",
            "tool_result",
            "run_stopped",
        ],
        event_kinds,
    )


def test_declined_publication_creates_no_outbox_file(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    published = tmp_path / "published"

    store = ProjectStore(workspace)

    final = store.save_linkedin_draft(
        project_id="demo",
        content=POST_CONTENT,
        stage="final",
    )

    outbox = PublicationOutbox(
        root=published,
        store=store,
    )
    registry = create_editorial_registry(
        store,
        outbox,
    )

    model = FakeModelClient(
        (
            ModelResponse(
                text="",
                tool_calls=(
                    ToolCall(
                        call_id="publish-final",
                        name="publish_linkedin_post",
                        arguments={
                            "project_id": "demo",
                            "version": final.version,
                            "visibility": "public",
                        },
                    ),
                ),
                continuation_token="turn-1",
            ),
            ModelResponse(
                text="Publication was declined.",
                tool_calls=(),
                continuation_token="turn-2",
            ),
        )
    )

    runner = AgentRunner(
        model=model,
        executor=registry,
        approval_gate=AlwaysDeclineGate(),
        max_steps=4,
    )

    result = runner.run(
        "Publish the final post.",
        tools=registry.schemas,
    )

    assert result.stop_reason == StopReason.ANSWERED
    assert result.text == (
        "Publication was declined."
    )

    published_path = (
        published
        / "demo"
        / f"{final.version:03d}-public.md"
    )

    assert not published_path.exists()

    second_request = model.requests[1]
    tool_result = second_request.input[0]

    assert tool_result.call_id == "publish-final"
    assert tool_result.name == (
        "publish_linkedin_post"
    )
    assert tool_result.result["ok"] is False
    assert (
        tool_result.result["error"]["type"]
        == "declined_by_user"
    )

    event_kinds = [
        event.kind
        for event in result.trace
    ]

    assert "approval_requested" in event_kinds
    assert "approval_declined" in event_kinds
    assert "approval_granted" not in event_kinds


def test_publication_content_equals_saved_final(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    published = tmp_path / "published"

    store = ProjectStore(workspace)

    final = store.save_linkedin_draft(
        project_id="demo",
        content="Exact final content.",
        stage="final",
    )

    outbox = PublicationOutbox(
        root=published,
        store=store,
    )

    published_post = outbox.publish(
        project_id="demo",
        version=final.version,
        visibility="connections",
    )

    assert published_post.content == (
        "Exact final content."
    )
    assert published_post.path.read_text(
        encoding="utf-8"
    ) == "Exact final content."
    assert published_post.path.resolve().is_relative_to(
        published.resolve()
    )
