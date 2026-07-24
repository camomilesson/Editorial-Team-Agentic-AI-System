"""Run the complete live editorial workflow with Gemini."""

from __future__ import annotations

import os
import shutil
from datetime import datetime
from pathlib import Path

from editorial_agent.agent import AgentRunner, StopReason
from editorial_agent.approval import TerminalApprovalGate
from editorial_agent.gemini import create_gemini_client_from_env
from editorial_agent.publication import PublicationOutbox
from editorial_agent.registry import create_editorial_registry
from editorial_agent.storage import ProjectStore

EXAMPLE_SOURCE = Path(
    "examples/demo-project/source/press_release.md"
)


def copy_demo_source(
    *,
    workspace: Path,
    project_id: str,
) -> Path:
    """Copy the tracked synthetic release into the workspace."""

    if not EXAMPLE_SOURCE.exists():
        raise FileNotFoundError(
            f"Demo source not found: {EXAMPLE_SOURCE}"
        )

    destination = (
        workspace
        / project_id
        / "source"
        / "press_release.md"
    )
    destination.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    shutil.copyfile(
        EXAMPLE_SOURCE,
        destination,
    )

    return destination


def find_latest_final_version(
    *,
    workspace: Path,
    project_id: str,
) -> int:
    """Find the newest saved final draft version."""

    linkedin_directory = (
        workspace
        / project_id
        / "linkedin"
    )

    final_paths = sorted(
        linkedin_directory.glob("*-final.md")
    )

    if not final_paths:
        raise RuntimeError(
            "The agent did not save a final draft."
        )

    latest = final_paths[-1]

    try:
        return int(
            latest.name.split("-", maxsplit=1)[0]
        )
    except ValueError as exc:
        raise RuntimeError(
            f"Unexpected draft filename: {latest.name}"
        ) from exc


def print_trace_summary(
    *,
    title: str,
    result,
) -> None:
    """Print trace event names without huge payloads."""

    print("")
    print(title)

    for event in result.trace:
        print(
            f"step={event.step} "
            f"kind={event.kind}"
        )


def main() -> int:
    """Run generation, verification, and publication."""

    timestamp = datetime.now().strftime(
        "%Y%m%d-%H%M%S"
    )
    project_id = f"demo-{timestamp}"

    workspace = Path(
        os.getenv(
            "WORKSPACE_DIR",
            "workspace",
        )
    )
    published_root = Path(
        os.getenv(
            "PUBLICATION_OUTBOX_DIR",
            "published",
        )
    )

    try:
        source_path = copy_demo_source(
            workspace=workspace,
            project_id=project_id,
        )

        store = ProjectStore(workspace)
        outbox = PublicationOutbox(
            root=published_root,
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
            max_steps=10,
        )

        generation_prompt = f"""
Create a LinkedIn post from the stored press release
for project '{project_id}'.

Required workflow:
1. Call read_press_release.
2. Write a concise LinkedIn post in US English.
3. Keep all factual claims grounded in the release.
4. Do not use hashtags.
5. Save the post with save_linkedin_draft using
   stage='first_draft'.
6. Read version 1 back with read_linkedin_draft.
7. Save the verified complete post again using
   stage='final'.
8. Return the final saved version number.

Do not publish it yet.
Do not merely describe the workflow. Use the tools.
""".strip()

        print(f"Project: {project_id}")
        print(f"Source: {source_path}")
        print("")
        print("Generating and verifying the post...")

        generation_result = runner.run(
            generation_prompt,
            tools=registry.schemas,
        )

        print("")
        print("GENERATION RESULT")
        print(generation_result.text)

        print_trace_summary(
            title="GENERATION TRACE",
            result=generation_result,
        )

        if (
            generation_result.stop_reason
            != StopReason.ANSWERED
        ):
            print(
                "Generation did not finish normally."
            )
            return 1

        final_version = find_latest_final_version(
            workspace=workspace,
            project_id=project_id,
        )

        final_path = (
            workspace
            / project_id
            / "linkedin"
            / f"{final_version:03d}-final.md"
        )

        print("")
        print(
            f"Final version: {final_version}"
        )
        print(f"Final file: {final_path}")
        print("")
        print("FINAL POST")
        print(
            final_path.read_text(
                encoding="utf-8"
            )
        )

        publication_prompt = f"""
Publish final LinkedIn post version {final_version}
from project '{project_id}' with public visibility.

Use publish_linkedin_post.
After the tool result, briefly state whether
publication succeeded.
""".strip()

        print("")
        print(
            "Requesting approval-gated publication..."
        )

        publication_result = runner.run(
            publication_prompt,
            tools=registry.schemas,
        )

        print("")
        print("PUBLICATION RESULT")
        print(publication_result.text)

        print_trace_summary(
            title="PUBLICATION TRACE",
            result=publication_result,
        )

        published_path = (
            published_root
            / project_id
            / f"{final_version:03d}-public.md"
        )

        print("")
        print("CREATED PATHS")
        print(f"Source: {source_path}")
        print(f"Final: {final_path}")

        if published_path.exists():
            print(f"Published: {published_path}")
        else:
            print("Published: no file created")

        if (
            publication_result.stop_reason
            != StopReason.ANSWERED
        ):
            return 1

        return 0
    except KeyboardInterrupt:
        print("")
        print("Interrupted.")
        return 130
    except EOFError:
        print(
            "Terminal input ended before approval."
        )
        return 2
    except Exception as exc:
        print(f"Demo failed: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
