"""Provider-neutral single-request independent Monitor runner."""

from __future__ import annotations

import json

from editorial_agent.contracts import CompletedRunBundle, MonitorAxis, MonitorReport
from editorial_agent.contracts.monitor import MONITOR_REPORT_SCHEMA_VERSION
from editorial_agent.contracts.storage import RuleDocument, RuleKind
from editorial_agent.models import ModelClient, ModelClientError, ModelRequest
from editorial_agent.monitoring.errors import MonitorModelError, MonitorValidationError
from editorial_agent.monitoring.evidence import build_evidence_index
from editorial_agent.monitoring.prompts import build_monitor_prompt


class MonitorRunner:
    """Evaluate one terminal bundle without tools, continuation state, or mutation."""

    def __init__(self, *, model: ModelClient, rubric: RuleDocument) -> None:
        if rubric.kind is not RuleKind.MONITOR_RUBRIC:
            raise ValueError("MonitorRunner requires the trusted Monitor rubric.")
        self._model = model
        self._rubric = rubric

    def evaluate(self, bundle: CompletedRunBundle) -> MonitorReport:
        """Make one fresh structured request and validate its report."""

        evidence = build_evidence_index(bundle)
        prompt = build_monitor_prompt(
            bundle=bundle,
            rubric=self._rubric,
            evidence=evidence,
        )
        try:
            response = self._model.respond(
                ModelRequest(input=prompt, tools=(), continuation_token=None)
            )
        except (ModelClientError, RuntimeError) as exc:
            raise MonitorModelError("Monitor model evaluation failed.") from exc
        if response.tool_calls:
            raise MonitorModelError("Monitor model returned an unsupported response.")
        try:
            payload = json.loads(response.text)
            if not isinstance(payload, dict):
                raise TypeError
            report = MonitorReport.from_dict(payload)
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise MonitorModelError("Monitor model returned an invalid report.") from exc
        self._validate_report(report, bundle=bundle, references=evidence.references)
        return report

    @staticmethod
    def _validate_report(
        report: MonitorReport,
        *,
        bundle: CompletedRunBundle,
        references: frozenset[str],
    ) -> None:
        if report.run_id != bundle.run.run_id:
            raise MonitorValidationError("Monitor report run identity is invalid.")
        if report.schema_version != MONITOR_REPORT_SCHEMA_VERSION:
            raise MonitorValidationError("Monitor report schema version is invalid.")
        axes = [finding.axis for finding in report.findings]
        required = set(MonitorAxis)
        if len(axes) != len(required) or set(axes) != required:
            raise MonitorValidationError(
                "Monitor report must contain every required axis exactly once."
            )
        if any(not finding.evidence_references for finding in report.findings):
            raise MonitorValidationError(
                "Every Monitor finding must cite supplied evidence."
            )
        invalid = {
            reference
            for finding in report.findings
            for reference in finding.evidence_references
            if reference not in references
        }
        if invalid:
            raise MonitorValidationError(
                "Monitor report contains invalid evidence references."
            )
