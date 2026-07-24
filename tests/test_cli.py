from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from editorial_agent.agent import (
    AgentResult,
    StopReason,
    TraceEvent,
)
from editorial_agent.cli import (
    AgentRuntime,
    CliConfig,
    main,
    positive_integer,
)
from editorial_agent.models import ToolSchema

TEST_SCHEMA: ToolSchema = {
    "type": "function",
    "name": "test_tool",
    "description": "A deterministic test tool.",
    "parameters": {
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    },
}


@dataclass
class RecordingRunner:
    """Record CLI-to-runner calls and return a fixed result."""

    result: AgentResult
    calls: list[
        tuple[str, tuple[ToolSchema, ...]]
    ] = field(default_factory=list)

    def run(
        self,
        user_input: str,
        tools: tuple[ToolSchema, ...] = (),
    ) -> AgentResult:
        self.calls.append(
            (
                user_input,
                tools,
            )
        )
        return self.result


def answered_result(
    text: str = "Done.",
) -> AgentResult:
    return AgentResult(
        text=text,
        stop_reason=StopReason.ANSWERED,
        steps=1,
        trace=(
            TraceEvent(
                step=1,
                kind="model_response",
                payload={
                    "text": text,
                    "tool_call_count": 0,
                },
            ),
            TraceEvent(
                step=1,
                kind="run_stopped",
                payload={
                    "reason": StopReason.ANSWERED,
                },
            ),
        ),
    )


def make_runtime_factory(
    runner: RecordingRunner,
    captured_configs: list[CliConfig] | None = None,
):
    def factory(config: CliConfig) -> AgentRuntime:
        if captured_configs is not None:
            captured_configs.append(config)

        return AgentRuntime(
            runner=runner,
            tools=(TEST_SCHEMA,),
        )

    return factory


def test_request_argument_reaches_runner() -> None:
    runner = RecordingRunner(
        result=answered_result("Saved version 1.")
    )
    outputs: list[str] = []
    errors: list[str] = []

    exit_code = main(
        [
            "run",
            "--request",
            "Create a LinkedIn post.",
        ],
        output_func=outputs.append,
        error_func=errors.append,
        runtime_factory=make_runtime_factory(
            runner
        ),
    )

    assert exit_code == 0
    assert errors == []
    assert outputs == ["Saved version 1."]
    assert runner.calls == [
        (
            "Create a LinkedIn post.",
            (TEST_SCHEMA,),
        )
    ]


def test_request_is_read_interactively_when_missing() -> None:
    runner = RecordingRunner(
        result=answered_result()
    )

    exit_code = main(
        ["run"],
        input_func=lambda prompt: (
            "Read the press release."
        ),
        output_func=lambda output: None,
        error_func=lambda output: None,
        runtime_factory=make_runtime_factory(
            runner
        ),
    )

    assert exit_code == 0
    assert runner.calls[0][0] == (
        "Read the press release."
    )


def test_cli_passes_paths_and_max_steps_to_factory(
    tmp_path: Path,
) -> None:
    runner = RecordingRunner(
        result=answered_result()
    )
    configs: list[CliConfig] = []

    workspace = tmp_path / "custom-workspace"
    outbox = tmp_path / "custom-outbox"

    exit_code = main(
        [
            "run",
            "--request",
            "Do the work.",
            "--workspace",
            str(workspace),
            "--outbox",
            str(outbox),
            "--max-steps",
            "12",
        ],
        output_func=lambda output: None,
        error_func=lambda output: None,
        runtime_factory=make_runtime_factory(
            runner,
            configs,
        ),
    )

    assert exit_code == 0
    assert configs == [
        CliConfig(
            workspace=workspace,
            outbox=outbox,
            max_steps=12,
        )
    ]


def test_trace_flag_prints_trace() -> None:
    runner = RecordingRunner(
        result=answered_result("Finished.")
    )
    outputs: list[str] = []

    exit_code = main(
        [
            "run",
            "--request",
            "Do it.",
            "--trace",
        ],
        output_func=outputs.append,
        error_func=lambda output: None,
        runtime_factory=make_runtime_factory(
            runner
        ),
    )

    assert exit_code == 0
    assert "Finished." in outputs
    assert "TRACE" in outputs
    assert any(
        "kind=model_response" in output
        for output in outputs
    )
    assert any(
        "kind=run_stopped" in output
        for output in outputs
    )


def test_blank_interactive_request_is_rejected() -> None:
    runner = RecordingRunner(
        result=answered_result()
    )
    errors: list[str] = []

    exit_code = main(
        ["run"],
        input_func=lambda prompt: "   ",
        output_func=lambda output: None,
        error_func=errors.append,
        runtime_factory=make_runtime_factory(
            runner
        ),
    )

    assert exit_code == 2
    assert runner.calls == []
    assert errors == [
        "Error: request must not be blank."
    ]


def test_interactive_eof_is_reported() -> None:
    runner = RecordingRunner(
        result=answered_result()
    )
    errors: list[str] = []

    def raise_eof(prompt: str) -> str:
        raise EOFError

    exit_code = main(
        ["run"],
        input_func=raise_eof,
        output_func=lambda output: None,
        error_func=errors.append,
        runtime_factory=make_runtime_factory(
            runner
        ),
    )

    assert exit_code == 2
    assert runner.calls == []
    assert errors == [
        (
            "Error: no request was provided on "
            "standard input."
        )
    ]


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("1", 1),
        ("8", 8),
        ("25", 25),
    ],
)
def test_positive_integer_accepts_positive_values(
    value: str,
    expected: int,
) -> None:
    assert positive_integer(value) == expected


@pytest.mark.parametrize(
    "value",
    [
        "0",
        "-1",
        "not-a-number",
    ],
)
def test_positive_integer_rejects_invalid_values(
    value: str,
) -> None:
    with pytest.raises(
        argparse.ArgumentTypeError,
    ):
        positive_integer(value)


def test_model_error_returns_nonzero_exit() -> None:
    runner = RecordingRunner(
        result=AgentResult(
            text="",
            stop_reason=StopReason.MODEL_ERROR,
            steps=1,
            trace=(),
        )
    )
    errors: list[str] = []

    exit_code = main(
        [
            "run",
            "--request",
            "Create a post.",
        ],
        output_func=lambda output: None,
        error_func=errors.append,
        runtime_factory=make_runtime_factory(
            runner
        ),
    )

    assert exit_code == 1
    assert errors == [
        (
            "Agent stopped without an answer: "
            "model_error"
        )
    ]


def test_max_steps_returns_nonzero_exit() -> None:
    runner = RecordingRunner(
        result=AgentResult(
            text="",
            stop_reason=StopReason.MAX_STEPS,
            steps=4,
            trace=(),
        )
    )
    errors: list[str] = []

    exit_code = main(
        [
            "run",
            "--request",
            "Create a post.",
        ],
        output_func=lambda output: None,
        error_func=errors.append,
        runtime_factory=make_runtime_factory(
            runner
        ),
    )

    assert exit_code == 1
    assert errors == [
        (
            "Agent stopped without an answer: "
            "max_steps"
        )
    ]


def test_answer_explaining_decline_is_successful() -> None:
    runner = RecordingRunner(
        result=answered_result(
            "Publication was declined."
        )
    )
    outputs: list[str] = []

    exit_code = main(
        [
            "run",
            "--request",
            "Publish it.",
        ],
        output_func=outputs.append,
        error_func=lambda output: None,
        runtime_factory=make_runtime_factory(
            runner
        ),
    )

    assert exit_code == 0
    assert outputs == [
        "Publication was declined."
    ]


def test_runtime_configuration_error_is_readable() -> None:
    errors: list[str] = []

    def broken_factory(
        config: CliConfig,
    ) -> AgentRuntime:
        del config
        raise RuntimeError(
            "GEMINI_API_KEY is not configured"
        )

    exit_code = main(
        [
            "run",
            "--request",
            "Create a post.",
        ],
        output_func=lambda output: None,
        error_func=errors.append,
        runtime_factory=broken_factory,
    )

    assert exit_code == 2
    assert errors == [
        (
            "Configuration error: "
            "GEMINI_API_KEY is not configured"
        )
    ]


def test_runner_exception_is_reported() -> None:
    class BrokenRunner:
        def run(
            self,
            user_input: str,
            tools: tuple[ToolSchema, ...] = (),
        ) -> Any:
            del user_input, tools
            raise RuntimeError("unexpected failure")

    errors: list[str] = []

    exit_code = main(
        [
            "run",
            "--request",
            "Create a post.",
        ],
        output_func=lambda output: None,
        error_func=errors.append,
        runtime_factory=lambda config: AgentRuntime(
            runner=BrokenRunner(),
            tools=(),
        ),
    )

    assert exit_code == 1
    assert errors == [
        "Agent execution failed: unexpected failure"
    ]