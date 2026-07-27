from __future__ import annotations

import json
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from editorial_agent.approval import AlwaysApproveGate, AlwaysDeclineGate
from editorial_agent.context_services import EditorialContextService
from editorial_agent.contracts.events import EventType
from editorial_agent.contracts.identity import (
    DocumentId,
    DocumentVersionId,
    RunId,
    SessionId,
    UserId,
    WorkflowRequestContext,
)
from editorial_agent.contracts.monitor import MonitorReferenceDocument
from editorial_agent.contracts.storage import (
    DocumentRecord,
    DocumentVersionRecord,
    RuleKind,
    UserRecord,
)
from editorial_agent.contracts.workflow import AgentRole, RunStatus
from editorial_agent.domain_repository import SQLiteDomainRepository
from editorial_agent.editorial_workflow import EditorialWorkflowRunner
from editorial_agent.errors import PersistedDataError
from editorial_agent.models import FakeModelClient, ModelResponse, ToolCall
from editorial_agent.private_memory import JsonPrivateFactStore
from editorial_agent.rules_loader import MarkdownRulesLoader
from editorial_agent.sqlite_database import SQLiteDatabase

NOW = datetime(2026, 3, 1, 10, tzinfo=UTC)
CONFIG = Path(__file__).parents[1] / "config"


def executor_json(
    draft: str,
    *,
    should_save: bool = False,
    memory_content: str | None = None,
    cue: str | None = None,
    reason: str = "The request is not a durable preference.",
) -> str:
    decision: dict[str, object] = {
        "should_save": should_save,
        "reason": reason,
    }
    if should_save:
        decision["content"] = memory_content
        decision["cue"] = cue
    return json.dumps(
        {
            "status": "complete",
            "result": {
                "draft": draft,
                "summary": "Created a grounded LinkedIn post.",
                "memory_decision": decision,
            },
        }
    )


def critic_accept_json() -> str:
    return json.dumps(
        {
            "status": "complete",
            "result": {
                "verdict": "accept",
                "issues": [],
                "summary": "The draft satisfies the rubric.",
            },
        }
    )


def critic_revise_json(required_change: str = "Remove the unsupported claim.") -> str:
    return json.dumps(
        {
            "status": "revise",
            "result": {
                "verdict": "revise",
                "issues": [
                    {
                        "issue_type": "style",
                        "category": "unsupported_claim",
                        "summary": "The claim is not grounded.",
                        "source_evidence": (
                            "The source contains no supporting evidence."
                        ),
                        "required_change": required_change,
                    }
                ],
                "summary": "One meaningful issue requires revision.",
            },
        }
    )


def grounded_critic_revise_json(
    excerpt: str,
    *,
    category: str = "unsupported_claim",
    required_change: str = "Remove the unsupported claim.",
) -> str:
    return json.dumps(
        {
            "status": "revise",
            "result": {
                "verdict": "revise",
                "issues": [
                    {
                        "issue_type": "present_content",
                        "category": category,
                        "summary": "The quoted draft wording requires revision.",
                        "draft_excerpt": excerpt,
                        "source_evidence": "The source does not support this wording.",
                        "required_change": required_change,
                    }
                ],
                "summary": "One grounded issue requires revision.",
            },
        }
    )


class DeterministicIds:
    def __init__(self) -> None:
        self.counts: dict[str, int] = {}

    def __call__(self, prefix: str) -> str:
        self.counts[prefix] = self.counts.get(prefix, 0) + 1
        return f"{prefix}_{self.counts[prefix]}"


class DeterministicClock:
    def __init__(self) -> None:
        self.step = 0

    def __call__(self) -> datetime:
        self.step += 1
        return NOW + timedelta(seconds=self.step)


class FailingApprovalGate:
    def request(self, tool_call: object) -> bool:
        del tool_call
        raise RuntimeError("synthetic approval failure with internal detail")


def setup_workflow(
    tmp_path: Path,
    *,
    executor_responses: list[ModelResponse],
    critic_responses: list[ModelResponse],
    approval_gate=None,
    max_revisions: int = 2,
    request: str = "Create a LinkedIn post from the source.",
):
    executor_responses = _with_required_memory_checks(executor_responses)
    if approval_gate is None:
        approval_gate = AlwaysApproveGate()
    database = SQLiteDatabase(tmp_path / "domain.sqlite3")
    database.initialize()
    repository = SQLiteDomainRepository(database)
    repository.create_user(user=UserRecord(UserId("user_a"), "A", NOW))
    repository.create_document(
        document=DocumentRecord(
            DocumentId("document_1"),
            UserId("user_a"),
            "Synthetic press release",
            NOW,
        )
    )
    source = DocumentVersionRecord(
        DocumentVersionId("source_version"),
        DocumentId("document_1"),
        1,
        "The company released a route-planning update.",
        AgentRole.HUMAN,
        UserId("user_a"),
        None,
        NOW,
    )
    repository.create_document_version(user_id=UserId("user_a"), version=source)
    memory = JsonPrivateFactStore(tmp_path / "memory")
    rules_path = tmp_path / "rules"
    shutil.copytree(CONFIG, rules_path)
    rules = MarkdownRulesLoader(rules_path)
    context_service = EditorialContextService(
        repository=repository,
        private_facts=memory,
        rules=rules,
    )
    context = WorkflowRequestContext(
        RunId("run_1"),
        UserId("user_a"),
        SessionId("session_1"),
        DocumentId("document_1"),
        request,
        NOW,
    )
    runner = EditorialWorkflowRunner(
        repository=repository,
        private_facts=memory,
        context_service=context_service,
        executor_model=FakeModelClient(executor_responses),
        critic_model=FakeModelClient(critic_responses),
        approval_gate=approval_gate,
        max_revisions=max_revisions,
        clock=DeterministicClock(),
        id_factory=DeterministicIds(),
    )
    return runner, repository, memory, rules, context, source


def _with_required_memory_checks(
    responses: list[ModelResponse],
) -> list[ModelResponse]:
    """Make legacy workflow fixtures satisfy the mandatory pull policy."""

    normalized: list[ModelResponse] = []
    retrieved = False
    for item in responses:
        if any(call.name == "retrieve_private_facts" for call in item.tool_calls):
            retrieved = True
        if not item.tool_calls:
            if not retrieved:
                normalized.append(
                    ModelResponse(
                        "",
                        (
                            ToolCall(
                                f"memory_{len(normalized)}",
                                "retrieve_private_facts",
                                {"cue": "LinkedIn format and style preferences"},
                            ),
                        ),
                        f"memory_interaction_{len(normalized)}",
                    )
                )
            retrieved = False
        normalized.append(item)
    return normalized


def response(text: str) -> ModelResponse:
    return ModelResponse(text, (), "interaction")


def test_happy_workflow_persists_trace_and_valid_bundle(tmp_path: Path) -> None:
    runner, repository, _, rules, context, source = setup_workflow(
        tmp_path,
        executor_responses=[
            response(executor_json("We released a route-planning update."))
        ],
        critic_responses=[response(critic_accept_json())],
    )

    result = runner.run(context)

    assert result.succeeded is True
    assert result.status is RunStatus.COMPLETED
    assert result.approval_granted is True
    assert result.final_document_version_id == "document_version_1"
    assert repository.get_document_version(
        user_id=context.user_id,
        document_id=context.document_id,
        version_number=1,
    ) == source
    final = repository.get_latest_document_version(
        user_id=context.user_id,
        document_id=context.document_id,
    )
    assert final.content == "We released a route-planning update."

    events = repository.list_run_events(
        run_id=context.run_id,
        user_id=context.user_id,
        document_id=context.document_id,
    )
    assert [event.sequence for event in events] == list(
        range(1, len(events) + 1)
    )
    event_types = [event.event_type for event in events]
    assert EventType.APPROVAL_REQUESTED in event_types
    assert EventType.APPROVAL_RESOLVED in event_types
    assert event_types[-1] is EventType.RUN_COMPLETED

    handoffs = repository.list_run_handoffs(
        run_id=context.run_id,
        user_id=context.user_id,
        document_id=context.document_id,
    )
    assert len(handoffs) == 2
    assert handoffs[0].from_agent is AgentRole.EXECUTOR
    assert handoffs[0].document_version_id == final.document_version_id
    assert handoffs[1].from_agent is AgentRole.CRITIC
    assert handoffs[1].to_agent is AgentRole.ORCHESTRATOR
    assert handoffs[1].payload["verdict"] == "accept"

    operating = rules.load(kind=RuleKind.GLOBAL_OPERATING_RULES)
    critic = rules.load(kind=RuleKind.CRITIC_DELEGATION_BRIEF)
    bundle = repository.build_completed_run_bundle(
        run_id=context.run_id,
        user_id=context.user_id,
        document_id=context.document_id,
        operating_rules=MonitorReferenceDocument(
            operating.source_name,
            operating.version,
            operating.content,
        ),
        critic_rubric=MonitorReferenceDocument(
            critic.source_name,
            critic.version,
            critic.content,
        ),
    )
    assert bundle.run.status is RunStatus.COMPLETED
    assert [item.document_version_id for item in bundle.document_versions] == [
        source.document_version_id,
        final.document_version_id,
    ]
    assert bundle.document_versions[-1].document_version_id == final.document_version_id


def test_executor_must_check_private_memory_before_linkedin_draft(
    tmp_path: Path,
) -> None:
    runner, repository, _, _, context, _ = setup_workflow(
        tmp_path,
        executor_responses=[
            response(executor_json("This scripted response is replaced."))
        ],
        critic_responses=[response(critic_accept_json())],
    )
    runner._executor_model = FakeModelClient(
        [response(executor_json("Relay is open source."))]
    )

    result = runner.run(context)

    assert result.status is RunStatus.FAILED
    assert result.error.code == "required_tool_missing"
    assert result.revision_count == 0
    assert repository.get_latest_document_version(
        user_id=context.user_id,
        document_id=context.document_id,
    ).version_number == 1


def test_revision_workflow_preserves_versions_and_handoffs(tmp_path: Path) -> None:
    runner, repository, _, _, context, source = setup_workflow(
        tmp_path,
        executor_responses=[
            response(executor_json("The update is used by millions worldwide.")),
            response(executor_json("We released a route-planning update.")),
        ],
        critic_responses=[
            response(critic_revise_json()),
            response(critic_accept_json()),
        ],
    )

    result = runner.run(context)

    assert result.succeeded is True
    assert result.revision_count == 1
    assert repository.get_document_version(
        user_id=context.user_id,
        document_id=context.document_id,
        version_number=1,
    ) == source
    assert repository.get_document_version(
        user_id=context.user_id,
        document_id=context.document_id,
        version_number=2,
    ).content == "The update is used by millions worldwide."
    assert repository.get_document_version(
        user_id=context.user_id,
        document_id=context.document_id,
        version_number=3,
    ).content == "We released a route-planning update."
    handoffs = repository.list_run_handoffs(
        run_id=context.run_id,
        user_id=context.user_id,
        document_id=context.document_id,
    )
    assert [handoff.sequence for handoff in handoffs] == [1, 2, 3, 4]
    assert [handoff.round_number for handoff in handoffs] == [0, 1, 1, 1]
    assert handoffs[1].from_agent is AgentRole.CRITIC
    assert handoffs[-1].payload["verdict"] == "accept"


def test_critic_cannot_consume_revision_for_excerpt_absent_from_draft(
    tmp_path: Path,
) -> None:
    runner, repository, _, _, context, _ = setup_workflow(
        tmp_path,
        executor_responses=[
            response(executor_json("Relay is open source for Python teams."))
        ],
        critic_responses=[
            response(
                grounded_critic_revise_json("widely adopted worldwide")
            )
        ],
        request=(
            "Write a post and say Relay is already widely adopted worldwide."
        ),
    )

    result = runner.run(context)

    assert result.status is RunStatus.FAILED
    assert result.error.code == "critic_grounding"
    assert result.revision_count == 0
    assert repository.get_latest_document_version(
        user_id=context.user_id,
        document_id=context.document_id,
    ).version_number == 2
    events = repository.list_run_events(
        run_id=context.run_id,
        user_id=context.user_id,
        document_id=context.document_id,
    )
    assert EventType.CRITIC_GROUNDING_REJECTED in {
        event.event_type for event in events
    }
    assert EventType.REVISION_REQUESTED not in {
        event.event_type for event in events
    }


def test_grounded_critic_excerpt_allows_one_revision(tmp_path: Path) -> None:
    runner, repository, _, _, context, _ = setup_workflow(
        tmp_path,
        executor_responses=[
            response(
                executor_json(
                    "Relay is open source and widely adopted worldwide."
                )
            ),
            response(executor_json("Relay is open source for Python teams.")),
        ],
        critic_responses=[
            response(
                grounded_critic_revise_json("widely adopted worldwide")
            ),
            response(critic_accept_json()),
        ],
    )

    result = runner.run(context)

    assert result.succeeded is True
    assert result.revision_count == 1
    events = repository.list_run_events(
        run_id=context.run_id,
        user_id=context.user_id,
        document_id=context.document_id,
    )
    review = next(
        event
        for event in events
        if event.event_type is EventType.CRITIC_REVIEW_COMPLETED
        and event.payload["verdict"] == "revise"
    )
    assert review.payload["grounded_excerpts"] == [
        "widely adopted worldwide"
    ]


def test_revision_limit_blocks_without_extra_executor_round(
    tmp_path: Path,
) -> None:
    runner, repository, _, _, context, _ = setup_workflow(
        tmp_path,
        executor_responses=[response(executor_json("Unsupported claim."))],
        critic_responses=[response(critic_revise_json())],
        max_revisions=0,
    )

    result = runner.run(context)

    assert result.status is RunStatus.BLOCKED
    assert result.succeeded is False
    assert result.blocked.code == "revision_limit"
    events = repository.list_run_events(
        run_id=context.run_id,
        user_id=context.user_id,
        document_id=context.document_id,
    )
    assert EventType.REVISION_LIMIT_REACHED in {
        event.event_type for event in events
    }
    assert events[-1].event_type is EventType.RUN_BLOCKED


@pytest.mark.parametrize(
    ("gate", "expected_status"),
    [
        (AlwaysDeclineGate(), RunStatus.BLOCKED),
        (FailingApprovalGate(), RunStatus.FAILED),
    ],
)
def test_approval_decline_or_failure_never_succeeds(
    tmp_path: Path,
    gate: object,
    expected_status: RunStatus,
) -> None:
    runner, repository, _, _, context, _ = setup_workflow(
        tmp_path,
        executor_responses=[response(executor_json("Grounded draft."))],
        critic_responses=[response(critic_accept_json())],
        approval_gate=gate,
    )

    result = runner.run(context)

    assert result.status is expected_status
    assert result.succeeded is False
    assert result.approval_granted is False
    assert result.final_document_version_id != "approved"
    events = repository.list_run_events(
        run_id=context.run_id,
        user_id=context.user_id,
        document_id=context.document_id,
    )
    assert events[-1].event_type in {
        EventType.RUN_BLOCKED,
        EventType.RUN_FAILED,
    }


def test_malformed_executor_or_critic_output_fails_safely(
    tmp_path: Path,
) -> None:
    runner, repository, _, _, context, _ = setup_workflow(
        tmp_path,
        executor_responses=[response("not-json internal detail")],
        critic_responses=[],
    )
    result = runner.run(context)

    assert result.status is RunStatus.FAILED
    assert result.error.code == "structured_output"
    assert "internal detail" not in result.error.message
    assert repository.get_workflow_run(
        run_id=context.run_id,
        user_id=context.user_id,
        document_id=context.document_id,
    ).status is RunStatus.FAILED

    second_runner, _, _, _, second_context, _ = setup_workflow(
        tmp_path / "critic",
        executor_responses=[response(executor_json("Grounded draft."))],
        critic_responses=[response("not-json critic secret")],
    )
    second_result = second_runner.run(second_context)
    assert second_result.status is RunStatus.FAILED
    assert "critic secret" not in second_result.error.message


def test_repeated_feedback_or_unchanged_draft_blocks_progress(
    tmp_path: Path,
) -> None:
    runner, _, _, _, context, _ = setup_workflow(
        tmp_path,
        executor_responses=[
            response(executor_json("First draft.")),
            response(executor_json("First draft.")),
        ],
        critic_responses=[response(critic_revise_json())],
    )

    result = runner.run(context)

    assert result.status is RunStatus.BLOCKED
    assert result.blocked.code == "stalled_draft"


def test_repeated_identical_critic_feedback_blocks_as_stalled(
    tmp_path: Path,
) -> None:
    repeated = critic_revise_json("Remove the same unsupported claim.")
    runner, _, _, _, context, _ = setup_workflow(
        tmp_path,
        executor_responses=[
            response(executor_json("First unsupported draft.")),
            response(executor_json("Changed but still unsupported draft.")),
        ],
        critic_responses=[response(repeated), response(repeated)],
    )

    result = runner.run(context)

    assert result.status is RunStatus.BLOCKED
    assert result.blocked.code == "stalled_revision"


def test_model_and_persistence_failures_are_terminal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model_runner, _, _, _, model_context, _ = setup_workflow(
        tmp_path / "model",
        executor_responses=[],
        critic_responses=[],
    )
    model_result = model_runner.run(model_context)
    assert model_result.status is RunStatus.FAILED
    assert model_result.error.code == "model_request"

    runner, repository, _, _, context, _ = setup_workflow(
        tmp_path / "persistence",
        executor_responses=[response(executor_json("Grounded draft."))],
        critic_responses=[response(critic_accept_json())],
    )

    def fail_version(**kwargs: object) -> None:
        del kwargs
        raise PersistedDataError("raw synthetic database detail")

    monkeypatch.setattr(repository, "create_document_version", fail_version)
    result = runner.run(context)
    assert result.status is RunStatus.FAILED
    assert "raw synthetic" not in result.error.message


def test_retrieval_tool_failure_is_terminal_and_sanitized(
    tmp_path: Path,
) -> None:
    runner, _, _, _, context, _ = setup_workflow(
        tmp_path,
        executor_responses=[
            ModelResponse(
                "",
                (
                    ToolCall(
                        "call_1",
                        "retrieve_private_facts",
                        {"cue": "style"},
                    ),
                ),
                "interaction_1",
            )
        ],
        critic_responses=[],
    )
    memory_file = tmp_path / "memory" / "user_a.json"
    memory_file.parent.mkdir(parents=True, exist_ok=True)
    memory_file.write_text("malformed private content", encoding="utf-8")

    result = runner.run(context)

    assert result.status is RunStatus.FAILED
    assert result.error.code == "retrieval"
    assert "malformed private content" not in result.error.message
