"""CLI tests for the independent Monitor entry point."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from editorial_agent.contracts import (
    CompletedRunBundle,
    MonitorAxis,
    MonitorFinding,
    MonitorJudgment,
    MonitorRationale,
    MonitorReport,
)
from editorial_agent.models import FakeModelClient, ModelResponse
from scripts import run_monitor

FIXTURES = Path(__file__).parent / "fixtures"


def response_for(bundle_path: Path) -> ModelResponse:
    bundle = CompletedRunBundle.from_dict(
        json.loads(bundle_path.read_text(encoding="utf-8"))
    )
    report = MonitorReport(
        report_id="report_cli_001",
        run_id=bundle.run.run_id,
        created_at=datetime(2026, 7, 27, 12, tzinfo=UTC),
        summary="Concise result.",
        findings=tuple(
            MonitorFinding(
                finding_id=f"finding_cli_{index}",
                axis=axis,
                judgment=MonitorJudgment.PASS,
                rationale=MonitorRationale(
                    expected="Expected behavior.",
                    observed="Observed behavior.",
                    reason="Evidence supports the judgment.",
                    impact="The result is traceable.",
                ),
                evidence_references=(bundle.run.run_id,),
            )
            for index, axis in enumerate(MonitorAxis, start=1)
        ),
    )
    return ModelResponse(
        text=json.dumps(report.to_dict()),
        tool_calls=(),
        continuation_token=None,
    )


def test_cli_parses_bundle_writes_report_and_prints_concise_summary(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    bundle_path = FIXTURES / "completed_run_monitor_v1.json"
    output = tmp_path / "report.json"
    fake = FakeModelClient([response_for(bundle_path)])
    monkeypatch.setenv("GEMINI_API_KEY", "secret-that-must-not-print")
    monkeypatch.setattr(run_monitor, "GeminiModelClient", lambda **kwargs: fake)

    code = run_monitor.main(
        ["--bundle", str(bundle_path), "--output", str(output)]
    )

    captured = capsys.readouterr()
    assert code == 0
    assert "run_monitor_completed_001" in captured.out
    assert "source_fidelity=pass" in captured.out
    assert "Findings: 7" in captured.out
    assert str(output) in captured.out
    assert "secret-that-must-not-print" not in captured.out + captured.err
    assert "Aster Works" not in captured.out + captured.err
    MonitorReport.from_dict(json.loads(output.read_text(encoding="utf-8")))


def test_cli_exits_nonzero_for_invalid_bundle(tmp_path: Path, capsys) -> None:
    invalid = tmp_path / "invalid.json"
    invalid.write_text("not json", encoding="utf-8")

    code = run_monitor.main(
        ["--bundle", str(invalid), "--output", str(tmp_path / "report.json")]
    )

    assert code != 0
    assert "invalid or unavailable" in capsys.readouterr().err


def test_cli_reports_sanitized_missing_configuration(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    bundle_path = FIXTURES / "blocked_run_monitor_v1.json"

    code = run_monitor.main(
        ["--bundle", str(bundle_path), "--output", str(tmp_path / "report.json")]
    )

    captured = capsys.readouterr()
    assert code != 0
    assert "export GEMINI_API_KEY" in captured.err
    assert "Relay" not in captured.err
