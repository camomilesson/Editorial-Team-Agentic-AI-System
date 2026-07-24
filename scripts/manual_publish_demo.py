"""Manual demo of approval-gated publication."""

import os
from pathlib import Path

from editorial_agent.agent import AgentRunner
from editorial_agent.approval import TerminalApprovalGate
from editorial_agent.gemini import create_gemini_client_from_env
from editorial_agent.publication import PublicationOutbox
from editorial_agent.registry import create_editorial_registry
from editorial_agent.storage import ProjectStore

workspace = Path(
    os.getenv("WORKSPACE_DIR", "workspace")
)

store = ProjectStore(workspace)

outbox = PublicationOutbox(
    root=Path("published"),
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
    max_steps=6,
)

result = runner.run(
    (
        "Publish final LinkedIn post version 2 from "
        "project 'demo-project' with public visibility. "
        "Use publish_linkedin_post. After receiving the result, "
        "briefly confirm whether publication succeeded."
    ),
    tools=registry.schemas,
)

print("\nFINAL RESPONSE")
print(result.text)

print("\nSTOP REASON")
print(result.stop_reason)

print("\nTRACE")
for event in result.trace:
    print(event.kind, event.payload)
