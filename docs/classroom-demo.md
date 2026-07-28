# Stage 5 classroom demo

## Purpose

The Stage 5 script presents the complete Editorial Team architecture as one
terminal story. It composes the real Executor–Critic workflow, approval gate,
completed-run evidence builder, and independent Monitor. It does not simulate
stages, bypass validation, or add the Monitor to the production workflow.

## Run it

Export `GEMINI_API_KEY` into the current shell, then run:

```bash
.venv/bin/python scripts/demo_stage5.py
```

The application does not load `.env` automatically. Optional arguments are:

```text
--approval approve|decline|interactive
--model MODEL_NAME
--output-root PATH
--plain
```

Approval defaults to `approve`, and evidence defaults to `demo-evidence/`.
Interactive approval uses the existing gate and accepts only the exact input
`YES`. Use `--plain` when ANSI styling or Unicode terminal rules are unsuitable.
The live command pauses for one second between terminal sections and between
individual Monitor rationale blocks so the story arrives at a
presentation-friendly pace.

## Expected story

The synthetic source says that Aster Works has not published adoption figures.
The user nevertheless requests a claim that Relay is already widely adopted
worldwide. The Executor may omit that unsupported claim immediately, or the
Critic may request a grounded revision that removes it. Both paths are honest
live outcomes.

The terminal presents:

1. the complete trusted source;
2. the complete user request and unsupported phrase;
3. stable workflow identities;
4. Executor context and retrieval events;
5. every persisted Executor draft;
6. every structured Critic review and grounded issue;
7. the actual human approval decision;
8. terminal workflow status and final copy, when finalized;
9. all seven independent Monitor judgments and rationales;
10. paths to the separately persisted workflow bundle and Monitor report.

The Monitor starts only after the workflow is terminal. It receives a fresh
model client, the completed evidence bundle, and its trusted rubric. It cannot
edit, approve, publish, access SQLite, or read private memory.

## Evidence

Every invocation creates a unique directory:

```text
demo-evidence/<UTC timestamp>-<unique suffix>/
    completed_run_bundle.json
    monitor_report.json
    workflow-runtime/
        domain.sqlite3
        private-memory/
```

The bundle and report are separate and existing run directories are never
overwritten. `demo-evidence/` is ignored by Git.

## Live variability and safe failure

Gemini may accept the first draft, request one or two revisions, return a
malformed result, or fail a request. The demo shows the real outcome and never
substitutes fixture output. A declined approval produces a blocked run and is
still monitored when a terminal bundle is available.

Failures are sanitized. The script does not print API keys, prompts, provider
tokens, or private-memory bodies. Invalid Monitor output is not persisted;
safe axis or evidence-reference diagnostics are shown when available.

## Suggested narration

- “The source is trusted evidence; the user request is not automatically true.”
- “The Executor must check scoped memory, but the screen shows only trace
  metadata—not private facts.”
- “Every draft is immutable, so revision creates another version.”
- “The Critic’s judgment is structured and grounded against an exact version.”
- “The human decides immediately before finalization.”
- “The Monitor is a fresh, retrospective reader with no mutation tools.”
- “Executor drafted. Critic verified. Human decided. Monitor audited.”
