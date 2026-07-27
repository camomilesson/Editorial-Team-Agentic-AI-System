# Stage 1 architecture contracts

Stage 1 defines provider-neutral boundaries for the next course-project stages.
It does not replace or connect to the working single-agent LinkedIn alpha yet.

## Identity and authorization boundary

Every future workflow request carries explicit run, user, session, and document
identity plus a timezone-aware UTC timestamp. Opaque identifiers reject path
syntax and traversal fragments. Possession of a document ID never represents
authorization: `DomainRepository.user_can_access_document` is the explicit
future access boundary, and the SQLite schema includes `document_access`.

Authorization behavior is not implemented in Stage 1.

## Three storage boundaries

The contracts deliberately keep three kinds of data separate:

1. `DomainRepository` represents structured SQLite data: users, documents,
   access, versions, shared comments, runs, events, and handoffs.
2. `PrivateFactStore` represents free-form, user-scoped memory. Both saving and
   retrieval require a `user_id`; each fact includes a retrieval cue.
3. `RulesLoader` represents trusted Markdown operating rules, delegation
   briefs, and Monitor rubrics with stable source and version metadata.

`migrations/001_initial_domain.sql` is the initial structured-domain schema.
It is only a schema contract; there is no SQLite repository implementation.
The existing filesystem draft storage remains unchanged.

## Structured outcomes and roles

Executor and Critic will exchange `AgentOutcome`, whose control fields are
typed and validated:

- `complete` requires a usable result;
- `revise` requires structured revision feedback;
- `blocked` requires a structured reason;
- `error` requires a sanitized error;
- `needs_approval` exactly matches a pending-approval description.

The authorized actors are orchestrator, Executor, Critic, Monitor, human, and
tool. The pure `validate_transition` function describes the future live
Executor–Critic transition rules. Critic-requested revisions default to a
maximum of two. Monitor is an event actor but cannot participate in live
handoffs.

There is no functioning Executor–Critic loop in Stage 1.

## Shared-content trust

`SharedComment` always assigns `untrusted_shared_content` in application code.
Its constructor does not accept a trust value, and deserialization rejects any
attempt to claim trusted operating-rule status. Comment bodies are data to
inspect, not executable instructions. The SQLite column applies the same fixed
classification with a check constraint.

Comment persistence, retrieval, authorization, and context presentation remain
unimplemented.

## Persistent trace contracts

`RunEvent` is an immutable, versioned event envelope with run and event IDs,
positive deterministic sequence, UTC timestamp, actor, closed event type,
JSON-compatible payload, and an optional document-version reference.

`AgentHandoff` is an immutable, versioned record with deterministic ordering,
revision round, distinct sender and receiver, explicit outcome status, and a
JSON-compatible payload. Prose may be carried in payloads but never controls
workflow transitions.

Payload redaction and content policy will be implemented before events are
persisted. Contracts do not require secrets, provider continuation tokens, raw
authorization material, or private facts.

## Independent Monitor input

`CompletedRunBundle` is the read-only boundary for Nina's independent Monitor.
It contains one terminal run, ordered events and handoffs, ordered document
versions, and versioned snapshots of operating rules and the Critic rubric.
It validates ordering, run ownership, terminal state, and terminal event
consistency without accessing live repositories, model providers, API keys, or
private-memory storage.

`tests/fixtures/completed_run_v1.json` remains the sparse sanitized
provider-neutral schema-v1 fixture. Rich schema-v1 examples with source
content, explicit Critic outcomes, approval, and terminal evidence are
available in `completed_run_monitor_v1.json` and
`blocked_run_monitor_v1.json`. See
[`monitor-handoff.md`](monitor-handoff.md) for compatibility and the frozen
Monitor boundary.

Provider-neutral output contracts now name Monitor axes, judgments,
expected/observed/reason/impact rationale, evidence-linked findings, and the
run-level report. Monitor execution, scheduling, LLM judgment, and report
persistence remain unimplemented.

## Stage 1 deferred implementation

Stage 2 has since implemented the local repositories, authorization, private
fact persistence, trusted rule loading, and context assembly described in
[`stage-2-storage-and-context.md`](stage-2-storage-and-context.md). The
remaining later-stage work includes:

- the Executor–Critic orchestration loop;
- integration of persistent events and handoffs with that loop;
- the final event-payload redaction policy;
- independent Monitor invocation, verdicts, and report storage.
