from __future__ import annotations

import json

import pytest

from editorial_agent.contracts.workflow import OutcomeStatus
from editorial_agent.role_results import (
    ExecutorResult,
    MemoryDecision,
    RoleOutputError,
    parse_critic_outcome,
    parse_executor_outcome,
)


def envelope(status: str, result: dict[str, object]) -> str:
    return json.dumps({"status": status, "result": result})


def executor_result(memory: dict[str, object]) -> dict[str, object]:
    return {
        "draft": "A grounded LinkedIn post.",
        "summary": "Created a concise post.",
        "memory_decision": memory,
    }


def test_valid_executor_complete_and_no_save() -> None:
    outcome = parse_executor_outcome(
        envelope(
            "complete",
            executor_result(
                {
                    "should_save": False,
                    "reason": "This instruction applies only once.",
                }
            ),
        )
    )

    assert outcome.status is OutcomeStatus.COMPLETE
    parsed = ExecutorResult.from_dict(outcome.result or {})
    assert parsed.memory_decision == MemoryDecision(
        False,
        "This instruction applies only once.",
    )


def test_valid_executor_save_decision() -> None:
    outcome = parse_executor_outcome(
        envelope(
            "complete",
            executor_result(
                {
                    "should_save": True,
                    "content": "Use US English for executive posts.",
                    "cue": "executive LinkedIn style",
                    "reason": "The user stated a durable preference.",
                }
            ),
        )
    )

    decision = ExecutorResult.from_dict(outcome.result or {}).memory_decision
    assert decision.should_save is True
    assert decision.cue == "executive LinkedIn style"


@pytest.mark.parametrize(
    "result",
    [
        executor_result(
            {"should_save": True, "reason": "Durable but incomplete."}
        ),
        executor_result(
            {
                "should_save": False,
                "reason": "No save.",
                "content": "Unexpected content.",
            }
        ),
        {
            "draft": " ",
            "summary": "Invalid blank draft.",
            "memory_decision": {
                "should_save": False,
                "reason": "No save.",
            },
        },
    ],
)
def test_invalid_executor_results_are_rejected(
    result: dict[str, object],
) -> None:
    with pytest.raises(RoleOutputError):
        parse_executor_outcome(envelope("complete", result))


def test_model_supplied_identity_is_rejected() -> None:
    result = executor_result(
        {"should_save": False, "reason": "No save."}
    )
    result["user_id"] = "other_user"
    with pytest.raises(RoleOutputError, match="identity"):
        parse_executor_outcome(envelope("complete", result))


def test_valid_critic_acceptance() -> None:
    outcome = parse_critic_outcome(
        envelope(
            "complete",
            {
                "verdict": "accept",
                "issues": [],
                "summary": "The draft satisfies the rubric.",
            },
        )
    )

    assert outcome.status is OutcomeStatus.COMPLETE


def test_valid_critic_revision_builds_structured_feedback() -> None:
    outcome = parse_critic_outcome(
        envelope(
            "revise",
            {
                "verdict": "revise",
                "issues": [
                    {
                        "category": "unsupported_claim",
                        "summary": "Adoption is unsupported.",
                        "evidence": "The source has no adoption data.",
                        "required_change": "Remove the adoption claim.",
                    }
                ],
                "summary": "One factual issue requires revision.",
            },
        )
    )

    assert outcome.status is OutcomeStatus.REVISE
    assert outcome.revision.required_changes == ("Remove the adoption claim.",)


def test_critic_revision_without_issues_is_rejected() -> None:
    with pytest.raises(RoleOutputError):
        parse_critic_outcome(
            envelope(
                "revise",
                {
                    "verdict": "revise",
                    "issues": [],
                    "summary": "Revise.",
                },
            )
        )


@pytest.mark.parametrize("text", ["not json", "[]", '{"status":"unknown"}'])
def test_malformed_or_unknown_role_output_is_rejected(text: str) -> None:
    with pytest.raises(RoleOutputError):
        parse_executor_outcome(text)

