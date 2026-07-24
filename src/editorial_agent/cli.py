"""Command-line interface for the editorial agent."""

from __future__ import annotations

import argparse
import json
import os
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from editorial_agent.agent import AgentResult, AgentRunner, StopReason
from editorial_agent.approval import TerminalApprovalGate
from editorial_agent.gemini import create_gemini_client_from_env
from editorial_agent.models import ToolSchema
from editorial_agent.publication import PublicationOutbox
from editorial_agent.registry import create_editorial_registry
from editorial_agent.storage import ProjectStore

InputFunction = Callable[[str], str]
OutputFunction = Callable[[str], None]


class RunnableAgent(Protocol):
    """The small portion of AgentRunner needed by the CLI."""

    def run(
        self,
        user_input: str,
        tools: tuple[ToolSchema, ...] = (),
    ) -> AgentResult:
        """Run one agent request."""
        ...


@dataclass(frozen=True)
class CliConfig:
    """Filesystem and loop configuration selected by the user."""

    workspace: Path
    outbox: Path
    max_steps: int


@dataclass(frozen=True)
class AgentRuntime:
    """A constructed agent and the schemas exposed to its model."""

    runner: RunnableAgent
    tools: tuple[ToolSchema, ...]


RuntimeFactory = Callable[[CliConfig], AgentRuntime]


def positive_integer(value: str) -> int:
    """Parse a positive integer for argparse."""

    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"{value!r} is not an integer"
        ) from exc

    if parsed < 1:
        raise argparse.ArgumentTypeError(
            "value must be at least 1"
        )

    return parsed


def build_parser() -> argparse.ArgumentParser:
    """Create the command-line argument parser."""

    parser = argparse.ArgumentParser(
        prog="editorial-agent",
        description=(
            "Run the approval-gated editorial workflow."
        ),
    )

    subparsers = parser.add_subparsers(
        dest="command",
        required=True,
    )

    run_parser = subparsers.add_parser(
        "run",
        help="Run one natural-language editorial request.",
    )

    run_parser.add_argument(
        "--request",
        help=(
            "Natural-language request. When omitted, the CLI "
            "asks for it interactively."
        ),
    )
    run_parser.add_argument(
        "--workspace",
        type=Path,
        default=Path(
            os.getenv("WORKSPACE_DIR", "workspace")
        ),
        help=(
            "Project workspace root. Defaults to WORKSPACE_DIR "
            "or ./workspace."
        ),
    )
    run_parser.add_argument(
        "--outbox",
        type=Path,
        default=Path(
            os.getenv(
                "PUBLICATION_OUTBOX_DIR",
                "published",
            )
        ),
        help=(
            "Local publication outbox. Defaults to "
            "PUBLICATION_OUTBOX_DIR or ./published."
        ),
    )
    run_parser.add_argument(
        "--max-steps",
        type=positive_integer,
        default=8,
        help="Maximum model turns. Defaults to 8.",
    )
    run_parser.add_argument(
        "--trace",
        action="store_true",
        help="Print the observable execution trace.",
    )

    return parser


def create_runtime(config: CliConfig) -> AgentRuntime:
    """Construct the production agent from existing components."""

    store = ProjectStore(config.workspace)

    outbox = PublicationOutbox(
        root=config.outbox,
        store=store,
    )

    registry = create_editorial_registry(
        store,
        outbox,
    )

    runner = AgentRunner(
        model=create_gemini_client_from_env(),
        executor=registry,
        approval_gate=TerminalApprovalGate(),
        max_steps=config.max_steps,
    )

    return AgentRuntime(
        runner=runner,
        tools=registry.schemas,
    )


def render_trace(
    result: AgentResult,
    *,
    output_func: OutputFunction,
) -> None:
    """Print a stable, readable representation of the trace."""

    output_func("")
    output_func("TRACE")

    for event in result.trace:
        payload = json.dumps(
            event.payload,
            ensure_ascii=False,
            sort_keys=True,
            default=str,
        )

        output_func(
            f"step={event.step} "
            f"kind={event.kind} "
            f"payload={payload}"
        )


def run_command(
    args: argparse.Namespace,
    *,
    input_func: InputFunction,
    output_func: OutputFunction,
    error_func: OutputFunction,
    runtime_factory: RuntimeFactory,
) -> int:
    """Execute the run subcommand."""

    request = args.request

    if request is None:
        try:
            request = input_func("Request: ")
        except EOFError:
            error_func(
                "Error: no request was provided on standard input."
            )
            return 2
        except KeyboardInterrupt:
            output_func("")
            error_func("Interrupted.")
            return 130

    if not request.strip():
        error_func("Error: request must not be blank.")
        return 2

    config = CliConfig(
        workspace=args.workspace,
        outbox=args.outbox,
        max_steps=args.max_steps,
    )

    try:
        runtime = runtime_factory(config)
    except Exception as exc:
        error_func(
            f"Configuration error: {exc}"
        )
        return 2

    try:
        result = runtime.runner.run(
            request,
            tools=runtime.tools,
        )
    except KeyboardInterrupt:
        output_func("")
        error_func("Interrupted.")
        return 130
    except EOFError:
        error_func(
            "Error: terminal input ended before the "
            "approval decision was received."
        )
        return 2
    except Exception as exc:
        error_func(
            f"Agent execution failed: {exc}"
        )
        return 1

    if result.text:
        output_func(result.text)

    if args.trace:
        render_trace(
            result,
            output_func=output_func,
        )

    if result.stop_reason == StopReason.ANSWERED:
        return 0

    error_func(
        f"Agent stopped without an answer: "
        f"{result.stop_reason}"
    )
    return 1


def main(
    argv: Sequence[str] | None = None,
    *,
    input_func: InputFunction = input,
    output_func: OutputFunction = print,
    error_func: OutputFunction = print,
    runtime_factory: RuntimeFactory = create_runtime,
) -> int:
    """Parse CLI arguments and execute the selected command."""

    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "run":
        return run_command(
            args,
            input_func=input_func,
            output_func=output_func,
            error_func=error_func,
            runtime_factory=runtime_factory,
        )

    parser.error(
        f"Unsupported command: {args.command}"
    )
    return 2