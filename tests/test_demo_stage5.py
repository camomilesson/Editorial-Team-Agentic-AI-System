"""Deterministic tests for the one-command Stage 5 classroom demo."""

from __future__ import annotations

import json
import re
from collections import deque
from io import StringIO
from pathlib import Path

import pytest

from editorial_agent.contracts import MonitorAxis, MonitorReport
from editorial_agent.live_integration import ApprovalMode
from editorial_agent.models import (
    FakeModelClient,
    ModelRequest,
    ModelResponse,
    ToolCall,
)
from scripts import demo_stage5


def response(payload: dict[str, object]) -> ModelResponse:
    return ModelResponse(json.dumps(payload), (), "provider-token-must-not-print")


def memory_check() -> ModelResponse:
    return ModelResponse(
        "",
        (
            ToolCall(
                "call_memory",
                "retrieve_private_facts",
                {"cue": "LinkedIn format and writing preferences"},
            ),
        ),
        "provider-token-must-not-print",
    )


def executor(draft: str) -> ModelResponse:
    return response(
        {
            "status": "complete",
            "result": {
                "draft": draft,
                "summary": "Prepared a source-grounded LinkedIn post.",
                "memory_decision": {
                    "should_save": False,
                    "reason": "No durable user preference was provided.",
                },
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
                        "summary": "The adoption claim is unsupported.",
                        "draft_excerpt": demo_stage5.UNSUPPORTED_PHRASE,
                        "source_evidence": "No adoption figures are published.",
                        "required_change": "Remove the unsupported adoption claim.",
                    }
                ],
                "summary": "Remove one unsupported factual claim.",
            },
        }
    )


class MonitorModel:
    def __init__(self, *, valid: bool = True) -> None:
        self.valid = valid
        self.requests: list[ModelRequest] = []

    def respond(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request)
        assert isinstance(request.input, str)
        run_id = re.search(r'"run_id":\s*"(run_demo_[^"]+)"', request.input).group(1)
        axes = list(MonitorAxis)
        if not self.valid:
            axes.pop()
        findings = [
            {
                "finding_id": f"finding_demo_{index}",
                "axis": axis.value,
                "judgment": "pass",
                "rationale": {
                    "expected": "The workflow should preserve the trusted boundary.",
                    "observed": "The persisted trace records the bounded behavior.",
                    "reason": "The cited run evidence supports this judgment.",
                    "impact": "The result remains auditable.",
                },
                "evidence_references": [run_id],
            }
            for index, axis in enumerate(axes, 1)
        ]
        return response(
            {
                "schema_version": "1",
                "report_id": "report_demo_001",
                "run_id": run_id,
                "created_at": "2026-07-27T12:00:00Z",
                "summary": "Independent evaluation completed.",
                "findings": findings,
            }
        )


class ModelQueue:
    def __init__(self, groups: list[list[ModelResponse]]) -> None:
        self.clients = deque(FakeModelClient(group) for group in groups)

    def __call__(self) -> FakeModelClient:
        return self.clients.popleft()


def run(
    tmp_path: Path,
    *,
    revision: bool = False,
    approval: ApprovalMode = ApprovalMode.APPROVE,
    valid_monitor: bool = True,
) -> tuple[demo_stage5.DemoArtifacts, str]:
    unsafe = (
        "Relay is already widely adopted worldwide."
        if revision
        else "Relay is open source for Python workflow teams."
    )
    safe = "Relay is open source for Python workflow teams."
    executor_responses = [memory_check(), executor(unsafe)]
    critic_responses = [critic_revise(), critic_accept()] if revision else [critic_accept()]
    if revision:
        executor_responses.extend((memory_check(), executor(safe)))
    stream = StringIO()
    artifacts = demo_stage5.run_demo(
        approval_mode=approval,
        model_name="fake-classroom-model",
        output_root=tmp_path / "demo-evidence",
        plain=True,
        workflow_model_factory=ModelQueue(
            [executor_responses, critic_responses]
        ),
        monitor_model_factory=lambda: MonitorModel(valid=valid_monitor),
        stream=stream,
        section_delay_seconds=0,
    )
    return artifacts, stream.getvalue()


@pytest.mark.parametrize("revision", [False, True])
def test_demo_completes_and_persists_real_bundle_and_monitor(
    tmp_path: Path, revision: bool
) -> None:
    artifacts, output = run(tmp_path, revision=revision)

    assert artifacts.workflow_result.succeeded
    assert artifacts.workflow_result.revision_count == int(revision)
    assert artifacts.bundle_path is not None and artifacts.bundle_path.exists()
    assert artifacts.monitor_path is not None and artifacts.monitor_path.exists()
    assert artifacts.bundle_path != artifacts.monitor_path
    MonitorReport.from_dict(json.loads(artifacts.monitor_path.read_text()))
    assert "PRELIMINARY DRAFT" in output
    assert "CRITIC REVIEW — round 1" in output
    assert "Decision: approved" in output
    assert ("EXECUTOR REVISION" in output) is revision
    assert "Expected:" in output
    assert "Observed:" in output
    assert "Reason:" in output
    assert "Impact:" in output
    for axis in MonitorAxis:
        assert output.count(f"{axis.value:<34} PASS") == 1
    assert "\033[" not in output
    assert "provider-token-must-not-print" not in output


def test_declined_workflow_is_blocked_but_still_monitored(tmp_path: Path) -> None:
    artifacts, output = run(tmp_path, approval=ApprovalMode.DECLINE)

    assert artifacts.workflow_result.status.value == "blocked"
    assert artifacts.monitor_report is not None
    assert artifacts.monitor_path is not None and artifacts.monitor_path.exists()
    assert "Decision: declined" in output
    assert "No version was finalized." in output


def test_invalid_monitor_report_is_not_persisted(tmp_path: Path) -> None:
    artifacts, output = run(tmp_path, valid_monitor=False)

    assert artifacts.bundle_path is not None and artifacts.bundle_path.exists()
    assert artifacts.monitor_path is None
    assert not (artifacts.output_directory / "monitor_report.json").exists()
    assert "Missing axes:" in output
    assert "No Monitor report was persisted." in output


def test_each_run_uses_a_unique_non_overwriting_directory(tmp_path: Path) -> None:
    first, _ = run(tmp_path)
    second, _ = run(tmp_path)

    assert first.output_directory != second.output_directory
    assert first.bundle_path is not None and first.bundle_path.exists()
    assert second.bundle_path is not None and second.bundle_path.exists()


def test_missing_key_exits_safely(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    code = demo_stage5.main(["--plain"])

    captured = capsys.readouterr()
    assert code != 0
    assert captured.err.strip() == "Demo cannot start: export GEMINI_API_KEY first."


def test_model_failure_is_sanitized_and_bundle_remains_monitorable(
    tmp_path: Path,
) -> None:
    stream = StringIO()
    artifacts = demo_stage5.run_demo(
        approval_mode=ApprovalMode.APPROVE,
        model_name="fake-classroom-model",
        output_root=tmp_path / "demo-evidence",
        plain=True,
        workflow_model_factory=ModelQueue([[], [critic_accept()]]),
        monitor_model_factory=MonitorModel,
        stream=stream,
        section_delay_seconds=0,
    )
    output = stream.getvalue()

    assert artifacts.workflow_result.status.value == "failed"
    assert artifacts.bundle_path is not None and artifacts.bundle_path.exists()
    assert "Executor failed safely" in output
    assert "provider-token" not in output
