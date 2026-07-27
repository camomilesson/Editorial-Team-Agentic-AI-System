"""Run the independent Monitor against a completed-run JSON bundle."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from editorial_agent.contracts import CompletedRunBundle
from editorial_agent.contracts.storage import RuleKind
from editorial_agent.gemini import DEFAULT_GEMINI_MODEL, GeminiModelClient
from editorial_agent.monitoring import (
    MonitorError,
    MonitorRunner,
    persist_monitor_report,
)
from editorial_agent.rules_loader import MarkdownRulesLoader


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Evaluate a terminal workflow bundle.")
    parser.add_argument("--bundle", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--model", default=DEFAULT_GEMINI_MODEL)
    parser.add_argument("--force", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        payload = json.loads(args.bundle.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError
        bundle = CompletedRunBundle.from_dict(payload)
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
        print("Error: completed-run bundle is invalid or unavailable.", file=sys.stderr)
        return 2

    try:
        rubric = MarkdownRulesLoader(_repository_root() / "config").load(
            kind=RuleKind.MONITOR_RUBRIC
        )
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            print(
                "Error: Gemini configuration is unavailable; export GEMINI_API_KEY.",
                file=sys.stderr,
            )
            return 3
        model = GeminiModelClient(model=args.model, api_key=api_key)
        report = MonitorRunner(model=model, rubric=rubric).evaluate(bundle)
        persist_monitor_report(
            report,
            output_path=args.output,
            input_bundle_path=args.bundle,
            force=args.force,
        )
    except MonitorError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 4
    except (OSError, ValueError):
        print("Error: Monitor configuration is invalid.", file=sys.stderr)
        return 3

    judgments = ", ".join(
        f"{finding.axis.value}={finding.judgment.value}"
        for finding in report.findings
    )
    print(f"Run: {report.run_id}")
    print(f"Judgments: {judgments}")
    print(f"Findings: {len(report.findings)}")
    print(f"Report: {args.output}")
    return 0


def _repository_root() -> Path:
    return Path(__file__).resolve().parents[1]


if __name__ == "__main__":
    raise SystemExit(main())
