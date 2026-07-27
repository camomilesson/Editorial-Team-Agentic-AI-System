"""Trusted Markdown rule loading by application-owned logical identity."""

from __future__ import annotations

import hashlib
from pathlib import Path

from editorial_agent.contracts.storage import RuleDocument, RuleKind
from editorial_agent.errors import TrustedRuleError

_RULE_FILES = {
    RuleKind.GLOBAL_OPERATING_RULES: "operating_rules.md",
    RuleKind.CRITIC_DELEGATION_BRIEF: "critic_brief.md",
    RuleKind.MONITOR_RUBRIC: "monitor_rubric.md",
}


class MarkdownRulesLoader:
    """Load editable trusted Markdown without accepting caller paths."""

    def __init__(self, rules_directory: Path) -> None:
        self._rules_directory = rules_directory.resolve(strict=False)

    def load(self, *, kind: RuleKind) -> RuleDocument:
        """Load one logical rule document and compute its content version."""

        try:
            filename = _RULE_FILES[kind]
        except (KeyError, TypeError) as exc:
            raise TrustedRuleError("Trusted rule kind is unsupported.") from exc
        path = (self._rules_directory / filename).resolve(strict=False)
        if not path.is_relative_to(self._rules_directory):
            raise TrustedRuleError("Trusted rule configuration is invalid.")
        try:
            content = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise TrustedRuleError(
                f"Trusted rule '{kind.value}' is unavailable."
            ) from exc
        if not content.strip():
            raise TrustedRuleError(f"Trusted rule '{kind.value}' is blank.")
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        return RuleDocument(
            kind=kind,
            source_name=filename,
            version=f"sha256:{digest}",
            content=content,
        )
