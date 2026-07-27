from __future__ import annotations

import json
from collections import deque
from pathlib import Path

import pytest

from editorial_agent.approval import (
    AlwaysApproveGate,
    AlwaysDeclineGate,
    TerminalApprovalGate,
)
from editorial_agent.contracts.identity import UserId
from editorial_agent.live_integration import (
    LEGITIMATE_COMMENT,
    MEMORY_SENTENCE,
    SHARED_COMMENTS_SOURCE,
    SHARED_PREFERRED_TERM,
    SHARED_REPLACED_TERM,
    ApprovalMode,
    LiveEditorialHarness,
    ScenarioAssertion,
    ScenarioResult,
    ScenarioStatus,
    _print_result,
    approval_gate_for,
    compose_runtime,
    main,
    sanitize_evidence,
)
from editorial_agent.models import (
    FakeModelClient,
    ModelResponse,
    ToolCall,
)


def executor_response(
    draft: str,
    *,
    save: bool = False,
    memory: str | None = None,
) -> ModelResponse:
    decision: dict[str, object] = {
        "should_save": save,
        "reason": (
            "The user stated a durable preference."
            if save
            else "No new durable preference was stated."
        ),
    }
    if save:
        decision.update(
            {
                "content": memory,
                "cue": "executive LinkedIn post ending preference",
            }
        )
    return response(
        {
            "status": "complete",
            "result": {
                "draft": draft,
                "summary": "Created a grounded LinkedIn post.",
                "memory_decision": decision,
            },
        }
    )


def critic_accept() -> ModelResponse:
    return response(
        {
            "status": "complete",
            "result": {
                "verdict": "accept",
                "issues": [],
                "summary": "The post is grounded and ready for approval.",
            },
        }
    )


def critic_revise() -> ModelResponse:
    return response(
        {
            "status": "revise",
            "result": {
                "verdict": "revise",
                "issues": [
                    {
                        "issue_type": "present_content",
                        "category": "unsupported_claim",
                        "summary": "Adoption is unsupported.",
                        "draft_excerpt": "widely adopted worldwide",
                        "source_evidence": "The source gives no adoption evidence.",
                        "required_change": "Remove the worldwide adoption claim.",
                    }
                ],
                "summary": "One unsupported claim must be removed.",
            },
        }
    )


def tool_call(name: str, arguments: dict[str, object]) -> ModelResponse:
    return ModelResponse(
        text="",
        tool_calls=(ToolCall(f"call_{name}", name, arguments),),
        continuation_token=f"interaction_{name}",
    )


def memory_check() -> ModelResponse:
    return tool_call(
        "retrieve_private_facts",
        {"cue": "LinkedIn format style structure and closing preferences"},
    )


def response(payload: dict[str, object]) -> ModelResponse:
    return ModelResponse(
        text=json.dumps(payload),
        tool_calls=(),
        continuation_token="interaction_final",
    )


class ClientQueue:
    def __init__(self, response_groups: list[list[ModelResponse]]) -> None:
        self.clients = deque(FakeModelClient(group) for group in response_groups)

    def __call__(self) -> FakeModelClient:
        return self.clients.popleft()


def harness(
    tmp_path: Path,
    clients: ClientQueue,
    *,
    approval: ApprovalMode = ApprovalMode.APPROVE,
) -> LiveEditorialHarness:
    return LiveEditorialHarness(
        workspace_root=tmp_path / "runtime",
        evidence_root=tmp_path / "evidence",
        model_factory=clients,
        model_name="fake-live-model",
        approval_mode=approval,
    )


def test_runtime_composition_uses_explicit_temporary_paths(tmp_path: Path) -> None:
    runtime = compose_runtime(tmp_path / "trusted-runtime")

    assert runtime.root == (tmp_path / "trusted-runtime").resolve()
    assert (runtime.root / "domain.sqlite3").exists()
    assert runtime.private_facts.get_all_facts(user_id=UserId("new_user")) == ()


def test_result_serialization_and_sanitization_omit_sensitive_fields(
    tmp_path: Path,
) -> None:
    result = ScenarioResult(
        scenario="basic",
        status=ScenarioStatus.PASSED,
        assertions=[ScenarioAssertion("ok", True, ("event_1",))],
    )
    unsafe = {
        "result": result.to_dict(),
        "api_key": "secret",
        "continuation_token": "provider-token",
        "path": str(tmp_path / "private" / "memory.json"),
    }

    sanitized = sanitize_evidence(unsafe, roots=(tmp_path,))
    encoded = json.dumps(sanitized)

    assert sanitized["result"]["status"] == "passed"
    assert "api_key" not in sanitized
    assert "continuation_token" not in sanitized
    assert "secret" not in encoded
    assert str(tmp_path) not in encoded


@pytest.mark.parametrize(
    ("mode", "expected_type"),
    [
        (ApprovalMode.INTERACTIVE, TerminalApprovalGate),
        (ApprovalMode.APPROVE, AlwaysApproveGate),
        (ApprovalMode.DECLINE, AlwaysDeclineGate),
    ],
)
def test_approval_mode_selection(mode: ApprovalMode, expected_type: type) -> None:
    assert isinstance(approval_gate_for(mode).delegate, expected_type)


def test_fake_basic_scenario_writes_evidence(tmp_path: Path) -> None:
    runner = harness(
        tmp_path,
        ClientQueue(
            [
                [
                    memory_check(),
                    executor_response(
                        "Relay is now open source for multi-team Python applications."
                    ),
                ],
                [critic_accept()],
            ]
        ),
    )

    result = runner.run_scenario("basic")

    assert result.status is ScenarioStatus.PASSED
    summary_paths = list((tmp_path / "evidence").glob("basic/*/summary.json"))
    assert len(summary_paths) == 1
    assert json.loads(summary_paths[0].read_text())["status"] == "passed"


def test_fake_memory_scenario_saves_retrieves_and_isolates(tmp_path: Path) -> None:
    clients = ClientQueue(
        [
            [
                memory_check(),
                executor_response(
                    f"Wayfinder is open source. {MEMORY_SENTENCE}",
                    save=True,
                    memory=(
                        "For all my executive LinkedIn posts, end with the "
                        f"sentence {MEMORY_SENTENCE}"
                    ),
                )
            ],
            [critic_accept()],
            [
                memory_check(),
                executor_response(f"Wayfinder has a new update. {MEMORY_SENTENCE}"),
            ],
            [critic_accept()],
            [
                memory_check(),
                executor_response("Wayfinder has a new update for Flutter teams."),
            ],
            [critic_accept()],
        ]
    )

    result = harness(tmp_path, clients).run_scenario("memory")

    assert result.status is ScenarioStatus.PASSED
    assert all(assertion.passed for assertion in result.assertions)


def test_fake_shared_comment_scenario_checks_security(tmp_path: Path) -> None:
    clients = ClientQueue(
        [
            [
                memory_check(),
                tool_call("retrieve_shared_comments", {}),
                executor_response(
                    "Relay connects workflow modules through a shared execution layer."
                ),
            ],
            [tool_call("retrieve_shared_comments", {}), critic_accept()],
        ]
    )

    result = harness(tmp_path, clients).run_scenario("shared-comments")

    assert result.status is ScenarioStatus.PASSED
    assert {item.name for item in result.assertions} >= {
        "comments_remained_untrusted",
        "private_canary_absent",
    }
    assert SHARED_REPLACED_TERM in SHARED_COMMENTS_SOURCE
    assert SHARED_REPLACED_TERM in LEGITIMATE_COMMENT
    assert SHARED_PREFERRED_TERM in LEGITIMATE_COMMENT


def test_fake_unsupported_claim_scenario_preserves_revisions(
    tmp_path: Path,
) -> None:
    clients = ClientQueue(
        [
            [
                memory_check(),
                executor_response("Wayfinder is widely adopted worldwide."),
                memory_check(),
                executor_response(
                    "Wayfinder is open source for multi-team Flutter applications."
                ),
            ],
            [critic_revise(), critic_accept()],
        ]
    )

    result = harness(tmp_path, clients).run_scenario("unsupported-claim")

    assert result.status is ScenarioStatus.PASSED
    assert next(iter(result.revision_counts.values())) == 1
    assert "unsupported_claim" in " ".join(result.notes)


def test_fake_approval_decline_scenario_is_blocked(tmp_path: Path) -> None:
    clients = ClientQueue(
        [
            [
                memory_check(),
                executor_response("Relay is open source for Python teams."),
            ],
            [critic_accept()],
        ]
    )

    result = harness(tmp_path, clients).run_scenario("approval-decline")

    assert result.status is ScenarioStatus.PASSED
    assert set(result.terminal_statuses.values()) == {"blocked"}
    assert set(result.approval_outcomes.values()) == {False}


def test_live_client_construction_failure_has_distinct_exit_code(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "present-but-not-printed")
    monkeypatch.setenv("MODEL_PROVIDER", "gemini")

    def fail() -> None:
        raise ValueError("synthetic secret-bearing failure")

    monkeypatch.setattr(
        "editorial_agent.live_integration.create_gemini_client_from_env",
        fail,
    )

    exit_code = main(["basic", "--approval", "approve"])
    captured = capsys.readouterr()

    assert exit_code == 3
    assert "construction failed safely" in captured.err
    assert "present-but-not-printed" not in captured.err
    assert "synthetic secret-bearing failure" not in captured.err


def test_command_exit_codes_for_failed_and_inconclusive(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    class Client:
        model = "fake"

    monkeypatch.setenv("GEMINI_API_KEY", "configured")
    monkeypatch.setattr(
        "editorial_agent.live_integration.create_gemini_client_from_env",
        lambda: Client(),
    )
    statuses = deque([ScenarioStatus.FAILED, ScenarioStatus.INCONCLUSIVE])

    def fake_run(self: object, scenario: str) -> ScenarioResult:
        del self
        return ScenarioResult(scenario=scenario, status=statuses.popleft())

    monkeypatch.setattr(
        "editorial_agent.live_integration.LiveEditorialHarness.run_scenario",
        fake_run,
    )

    failed = main(
        [
            "basic",
            "--approval",
            "approve",
            "--runtime-root",
            str(tmp_path / "runtime"),
            "--evidence-root",
            str(tmp_path / "evidence"),
        ]
    )
    inconclusive = main(
        [
            "basic",
            "--approval",
            "approve",
            "--runtime-root",
            str(tmp_path / "runtime2"),
            "--evidence-root",
            str(tmp_path / "evidence2"),
        ]
    )

    assert failed == 1
    assert inconclusive == 2


@pytest.mark.parametrize(
    ("scenario", "failed_assertion", "category"),
    [
        ("memory", "user_a_fact_retrieved", "retrieval"),
        ("memory", "user_a_preference_applied", "memory_decision"),
        ("shared-comments", "fixture_relevant", "fixture_invalid"),
        (
            "shared-comments",
            "legitimate_terminology_applied",
            "comment_application",
        ),
        ("shared-comments", "private_canary_absent", "security_assertion"),
        ("unsupported-claim", "workflow_completed", "critic_quality"),
    ],
)
def test_failure_categories_match_failed_property(
    scenario: str,
    failed_assertion: str,
    category: str,
) -> None:
    result = ScenarioResult(
        scenario=scenario,
        status=ScenarioStatus.PASSED,
        assertions=[ScenarioAssertion(failed_assertion, False)],
    )

    LiveEditorialHarness._finalize_status(result)

    assert result.status is ScenarioStatus.FAILED
    assert result.failure_category == category


def test_memory_terminal_output_compares_a2_and_b1_without_memory_dump(
    capsys: pytest.CaptureFixture[str],
) -> None:
    result = ScenarioResult(
        scenario="memory",
        status=ScenarioStatus.PASSED,
        run_ids=["a1", "a2", "b1"],
        final_posts={
            "a1": "First post.",
            "a2": f"Second post. {MEMORY_SENTENCE}",
            "b1": "Comparison post.",
        },
        assertions=[
            ScenarioAssertion("user_a_fact_saved", True, ("fact_1",)),
            ScenarioAssertion("user_a_fact_retrieved", True, ("fact_1",)),
            ScenarioAssertion("user_a_preference_applied", True),
            ScenarioAssertion("user_b_isolated", True),
        ],
    )

    _print_result(result, "fake")
    output = capsys.readouterr().out

    assert "User A second-run final post:" in output
    assert "User B comparison final post:" in output
    assert "A2 retrieval evidence: ['fact_1']" in output
    assert "private-memory" not in output


def test_unsupported_terminal_output_includes_grounding_data(
    capsys: pytest.CaptureFixture[str],
) -> None:
    result = ScenarioResult(
        scenario="unsupported-claim",
        status=ScenarioStatus.PASSED,
        notes=[
            "Reviewed version IDs: ['version_1'].",
            "Critic issue categories: ['unsupported_claim'].",
            "Grounded draft excerpts: ['widely adopted worldwide'].",
            "Terminal reason: completed.",
        ],
        assertions=[
            ScenarioAssertion("unsupported_claim_absent", True),
        ],
    )

    _print_result(result, "fake")
    output = capsys.readouterr().out

    assert "Reviewed version IDs" in output
    assert "Grounded draft excerpts" in output
    assert "Unsupported phrase absent: yes" in output
