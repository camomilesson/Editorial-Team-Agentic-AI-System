"""Separate Monitor report persistence tests."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from editorial_agent.contracts import (
    MonitorAxis,
    MonitorFinding,
    MonitorJudgment,
    MonitorRationale,
    MonitorReport,
)
from editorial_agent.monitoring import MonitorPersistenceError, persist_monitor_report


def sample_report(*, summary: str = "First report.") -> MonitorReport:
    return MonitorReport(
        report_id="report_persistence_001",
        run_id="run_persistence_001",
        created_at=datetime(2026, 7, 27, 12, tzinfo=UTC),
        summary=summary,
        findings=tuple(
            MonitorFinding(
                finding_id=f"finding_persistence_{index}",
                axis=axis,
                judgment=MonitorJudgment.PASS,
                rationale=MonitorRationale(
                    expected="Expected behavior.",
                    observed="Observed behavior.",
                    reason="Evidence supports the result.",
                    impact="The trace remains useful.",
                ),
                evidence_references=("run_persistence_001",),
            )
            for index, axis in enumerate(MonitorAxis, start=1)
        ),
    )


def test_report_is_written_separately_and_round_trips_deterministically(
    tmp_path: Path,
) -> None:
    bundle = tmp_path / "bundle.json"
    original = b'{"original":true}\n'
    bundle.write_bytes(original)
    output = tmp_path / "reports" / "monitor.json"

    persist_monitor_report(
        sample_report(), output_path=output, input_bundle_path=bundle
    )

    assert bundle.read_bytes() == original
    report = MonitorReport.from_dict(json.loads(output.read_text(encoding="utf-8")))
    assert report == sample_report()
    assert output.read_text(encoding="utf-8").endswith("\n")


def test_existing_output_requires_force_and_force_replaces_it(tmp_path: Path) -> None:
    output = tmp_path / "monitor.json"
    persist_monitor_report(sample_report(), output_path=output)

    with pytest.raises(MonitorPersistenceError, match="already exists"):
        persist_monitor_report(sample_report(summary="Replacement."), output_path=output)

    persist_monitor_report(
        sample_report(summary="Replacement."), output_path=output, force=True
    )
    assert json.loads(output.read_text(encoding="utf-8"))["summary"] == "Replacement."


def test_input_and_output_must_differ(tmp_path: Path) -> None:
    path = tmp_path / "bundle.json"
    path.write_text("unchanged", encoding="utf-8")

    with pytest.raises(MonitorPersistenceError, match="must differ"):
        persist_monitor_report(
            sample_report(),
            output_path=path,
            input_bundle_path=path,
            force=True,
        )

    assert path.read_text(encoding="utf-8") == "unchanged"
