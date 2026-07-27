# Independent Monitor handoff

## Purpose

The Monitor runs after an editorial workflow reaches a terminal state. It
independently evaluates the supplied evidence; it is not another step in the
Executor–Critic conversation.

## Frozen input

The input boundary is
`editorial_agent.contracts.monitor.CompletedRunBundle`. A Monitor entry point
should accept either a validated bundle object or a JSON file parsed with
`CompletedRunBundle.from_dict`.

A bundle contains:

- one terminal workflow-run record;
- ordered events and agent handoffs;
- ordered document-version snapshots;
- versioned operating rules;
- a versioned Critic rubric.

The `CompletedRunBundle` and Monitor contracts are frozen for the initial
independent Monitor implementation. Core changes should be avoided while the
Monitor branch is in progress unless a blocking contract defect is discovered.

## Frozen output

Monitor output uses the provider-neutral contracts in
`src/editorial_agent/contracts/monitor.py`:

- `MonitorAxis` names source fidelity, instruction adherence, task completion,
  Critic consistency, revision quality, approval/terminal correctness, and
  trace completeness;
- `MonitorJudgment` provides `pass`, `partial`, `fail`, `unknown`, and
  `insufficient_evidence`;
- `MonitorRationale` records expected behavior, observed behavior, reason, and
  impact;
- `MonitorFinding` links one named judgment to stable evidence references;
- `MonitorReport` identifies the evaluated run and serializes an ordered set
  of findings with a summary.

The implementation may choose how to derive judgments, but it should return
and persist a valid `MonitorReport` separately from the workflow records.

## Independence and ownership rules

The Monitor must:

- run as a separate job or CLI invocation;
- receive no Executor or Critic model conversation state;
- evaluate only the supplied bundle and trusted Monitor rubric;
- remain read-only with respect to workflow state;
- not revise documents, approve, publish, or write private memory;
- not access SQLite directly unless a later design explicitly authorizes it;
- persist its own report separately.

Nina may add:

```text
src/editorial_agent/monitoring/
scripts/run_monitor.py
tests/test_monitor_*.py
config/monitor_rubric.md
docs/independent-monitor.md
```

Core workflow, migrations, domain storage, private memory, prompts, and
orchestration should remain unchanged unless the frozen contracts contain a
genuine blocking defect.

## Evidence and evaluation

The Monitor may judge:

- source fidelity;
- valid instruction adherence;
- task completion;
- Critic consistency and grounding;
- revision quality;
- approval and terminal-state correctness;
- trace completeness.

A live-harness pass means its scenario assertions passed. It does not force a
positive Monitor judgment about editorial or reasoning quality.

## Sparse and rich schema-v1 bundles

Both evidence shapes use bundle schema version `1`.

Sparse valid bundles, including
`tests/fixtures/completed_run_v1.json`, may lack source content, explicit
Critic acceptance, grounded issue evidence, or a complete version history.

Rich bundles may include:

- the source version and every run-created draft;
- `critic_review_completed` events;
- Critic-to-Executor revision handoffs;
- Critic-to-Orchestrator acceptance handoffs;
- grounded issue evidence;
- explicit approval and terminal events.

The Monitor must consume the evidence that is available and never infer or
invent missing evidence. When an evaluation axis cannot be supported, use
`partial`, `unknown`, or `insufficient_evidence` and explain exactly which
evidence was unavailable in the rationale.

## Committed fixtures

- `tests/fixtures/completed_run_monitor_v1.json` represents a grounded
  revision, Critic acceptance, human approval, and completed run.
- `tests/fixtures/blocked_run_monitor_v1.json` represents Critic acceptance
  followed by human approval decline and a blocked run.
- `tests/fixtures/completed_run_v1.json` remains the sparse backward-
  compatibility fixture.

All fixtures are synthetic, provider-neutral, and validated through the real
contracts. They contain no API keys, provider state, private-memory bodies,
real user data, or local runtime paths.
