"""Regression tests for trusted role-prompt decision rules."""

from __future__ import annotations

import json
from types import SimpleNamespace

from editorial_agent.role_prompts import build_critic_prompt


def test_critic_prompt_treats_omitted_unsupported_request_as_compliance() -> None:
    request = "Announce Relay and say it is already widely adopted worldwide."
    source = "Relay is open source. No adoption figures have been published."
    draft = "Relay is now open source."
    pushed = SimpleNamespace(
        workflow=SimpleNamespace(request=request),
        document_version=SimpleNamespace(content=draft),
        operating_rules=SimpleNamespace(
            content="Never invent unsupported factual claims."
        ),
        role_brief=SimpleNamespace(content="Review the exact supplied draft."),
        trust_boundary_instructions=(),
    )

    prompt = build_critic_prompt(
        pushed=pushed,
        source_content=source,
        candidate_content=draft,
        revision_count=0,
        max_revisions=2,
    )

    instructions, serialized_task = prompt.split("\n", 1)
    task = json.loads(serialized_task)
    assert "its absence from candidate_content is correct compliance" in instructions
    assert "Do not create any issue or request a revision merely" in instructions
    assert "Accept only if the draft also has no separate material defect" in instructions
    assert task["workflow_request"] == request
    assert task["source_content"] == source
    assert task["candidate_content"] == draft
