import pytest

from editorial_agent.approval import (
    AlwaysApproveGate,
    AlwaysDeclineGate,
    TerminalApprovalGate,
)
from editorial_agent.models import ToolCall


def make_publish_call() -> ToolCall:
    return ToolCall(
        call_id="call-1",
        name="publish_linkedin_post",
        arguments={
            "project_id": "demo",
            "version": 2,
            "visibility": "public",
        },
    )


def test_terminal_gate_accepts_exact_yes() -> None:
    outputs: list[str] = []

    gate = TerminalApprovalGate(
        input_func=lambda prompt: "YES",
        output_func=outputs.append,
    )

    assert gate.request(make_publish_call()) is True
    assert any(
        "publish_linkedin_post" in output
        for output in outputs
    )


def test_terminal_gate_rejects_lowercase_yes() -> None:
    gate = TerminalApprovalGate(
        input_func=lambda prompt: "yes",
        output_func=lambda output: None,
    )

    assert gate.request(make_publish_call()) is False


def test_terminal_gate_rejects_blank_input() -> None:
    gate = TerminalApprovalGate(
        input_func=lambda prompt: "",
        output_func=lambda output: None,
    )

    assert gate.request(make_publish_call()) is False


@pytest.mark.parametrize(
    "response",
    (
        " YES",
        "YES ",
        "YES\n",
        "Yes",
    ),
)
def test_terminal_gate_rejects_anything_except_exact_yes(
    response: str,
) -> None:
    gate = TerminalApprovalGate(
        input_func=lambda prompt: response,
        output_func=lambda output: None,
    )

    assert gate.request(make_publish_call()) is False


def test_always_approve_gate() -> None:
    assert AlwaysApproveGate().request(
        make_publish_call()
    ) is True


def test_always_decline_gate() -> None:
    assert AlwaysDeclineGate().request(
        make_publish_call()
    ) is False
