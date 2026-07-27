# Independent Monitor

## Purpose and boundary

The Independent Monitor evaluates a terminal editorial workflow after the main
Executor–Critic workflow has finished. It receives one provider-neutral
`CompletedRunBundle`, makes one fresh model request, validates the resulting
`MonitorReport`, and optionally writes that report to a separate JSON file.

The Monitor is not part of drafting or revision. It receives no tools, no
Executor or Critic continuation token, no SQLite repository, no private-memory
store, and no approval or publication capability. It cannot remediate the run.

## Architecture

`MonitorRunner` is injected with the provider-neutral `ModelClient` and a
trusted `RuleDocument` for `MONITOR_RUBRIC`. The evidence layer derives a
deterministic index containing the run ID, document ID, document-version IDs,
event IDs, handoff IDs, operating-rules version, and Critic-rubric version
present in the bundle. It also records observable facts and missing evidence
classes without making editorial judgments.

The prompt has six explicit sections:

1. trusted Monitor rubric;
2. exact required axes derived from `MonitorAxis`;
3. deterministic evidence summary;
4. exact allowed evidence-reference strings grouped by reference type;
5. untrusted serialized completed-run bundle;
6. existing output contract.

The runner makes exactly one request with no tools and no continuation token.
It parses the response through `MonitorReport.from_dict`, requires every
`MonitorAxis` exactly once, verifies the report run identity, and rejects any
finding that cites a reference absent from the evidence index. Invalid or
malformed output fails with a sanitized error.

Evidence references are literal opaque strings: prefixes, descriptions,
paraphrases, and surrounding whitespace are not equivalent. A finding may use
an empty reference list when the bundle has no stable evidence supporting that
axis. On invalid-reference failure, the CLI prints only the returned, allowed,
and invalid identifier sets; it does not print evidence content or persist a
partial report.

Axis validation likewise remains strict: every required axis must occur exactly
once. A blocked run is evaluated across all axes; respecting a human decline
can support a positive approval-integrity judgment even though task completion
is not a pass. Axis failures print only returned, required, missing, and
duplicate axis names.

## Sparse and rich evidence

Rich bundles can support grounded judgments about source fidelity, Critic
revision and acceptance, revision quality, approval, and terminal state.
Schema-v1 sparse bundles remain valid. Missing source, review, acceptance, or
approval evidence is represented in the deterministic summary; the model must
use `unknown` or `insufficient_evidence` rather than inventing facts.

## Trusted rubric

`config/monitor_rubric.md` is loaded by the existing logical trusted-Markdown
loader. Its SHA-256 content version is included in the trusted prompt section.
Bundle text remains in the untrusted section even if it resembles an
instruction.

## CLI and live Gemini setup

The application does not load `.env` automatically. If a local `.env` exists,
explicitly export it in a compatible shell:

```bash
set -a
source .env
set +a
```

Evaluate a completed fixture:

```bash
.venv/bin/python scripts/run_monitor.py \
  --bundle tests/fixtures/completed_run_monitor_v1.json \
  --output /tmp/completed-monitor-report.json
```

Evaluate an approval-declined fixture:

```bash
.venv/bin/python scripts/run_monitor.py \
  --bundle tests/fixtures/blocked_run_monitor_v1.json \
  --output /tmp/blocked-monitor-report.json
```

`--model` overrides the default Gemini model. Existing output is refused unless
`--force` is supplied. Input and output paths must differ. The CLI prints only
the run ID, axis judgments, finding count, and output path.

## Persistence and failure behavior

Reports use deterministic UTF-8 JSON and an atomic same-directory replacement.
Parent directories are created when possible. The input bundle is never
modified. No workflow event, database, or memory write occurs.

Invalid bundles, missing configuration, model failures, invalid reports, and
persistence failures return nonzero exit codes with sanitized messages. Raw
prompts, bundle contents, secrets, and provider tokens are not printed or
persisted.

## Testing and limitations

Deterministic tests inject `FakeModelClient`; they do not use the network.
Run:

```bash
.venv/bin/python -m pytest tests/test_monitor_*.py -v
.venv/bin/python -m pytest
.venv/bin/ruff check .
```

Live model wording and judgments may vary. The deterministic suite defines the
stable behavior. The Monitor currently performs one evaluation per invocation;
it has no scheduler, retries, remediation loop, database repository, or
provider-specific structured-output extension.
