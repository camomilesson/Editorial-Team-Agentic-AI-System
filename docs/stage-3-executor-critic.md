# Stage 3 Executor–Critic workflow

Stage 3 adds a provider-neutral multi-agent workflow service beside the
original single-agent alpha. The existing CLI still uses the alpha.

## Request flow

`EditorialWorkflowRunner` receives an already validated
`WorkflowRequestContext` and explicit dependencies. It:

1. creates the authorized persistent run and `run_started` event;
2. builds pushed Executor context from the source, trusted operating rules,
   Executor brief, workflow identity, and trust-boundary instructions;
3. requires the Executor to check current-user private memory through the
   scoped retrieval tool before every LinkedIn draft or revision, then lets it
   call other relevant current-user/current-document retrieval tools;
4. strictly parses the Executor's structured draft and memory decision;
5. saves an approved durable fact decision under trusted application identity;
6. stores the draft as a new immutable SQLite document version;
7. appends an Executor-to-Critic handoff referencing that exact version;
8. runs the Critic with source, exact candidate draft, rules, brief, and
   budget; when the Executor consulted shared comments, the Critic must
   retrieve them independently;
9. either accepts, blocks, fails, or sends structured issues back to Executor;
10. repeats bounded revisions and immutable version creation when required;
11. requests explicit human approval immediately after Critic acceptance;
12. records approval and a terminal completed, blocked, or failed run event.

No external publication occurs. A successful result identifies the exact
Critic-accepted and human-approved document version.

## Roles, prompts, and tools

The Executor and Critic are explicit `RoleAgent` instances. They may use the
same provider in composition, but each receives a separate prompt, tool
registry, model request sequence, role label, and strict result parser.

The editable `config/executor_brief.md` requires grounded LinkedIn copy,
relevant-only private facts, untrusted-comment handling, and an explicit
memory decision. `config/critic_brief.md` limits the Critic to review,
structured revision, blocking, or escalation.

Both registries expose only:

- `retrieve_private_facts(cue, limit?)`;
- `retrieve_shared_comments()`.

The registries are bound to the validated workflow context. Neither schema
accepts user ID, document ID, database, memory root, path, access control,
publication, approval, or mutation arguments. The Critic cannot save facts.

## Pushed and pulled context

Pushed context contains workflow identity, the authorized document snapshot,
trusted rules, the role brief, source material, trust-boundary instructions,
and structured revision feedback when applicable. It explicitly does not
contain all private facts or shared comments.

Private facts and comments enter a role request only after a model tool call.
Facts come from the current user's file. Comments come from the current
authorized document and retain `untrusted_shared_content`.

## Structured results and memory

Role responses must be JSON objects. Free-form final prose, unknown statuses,
identity fields, unsupported fields, blank drafts, invalid memory decisions,
and revision verdicts without issues fail safely.

An Executor success contains:

- nonblank draft and summary;
- `MemoryDecision.should_save`;
- a nonblank reason;
- content and cue only for a durable save decision.

The model cannot choose fact ID, user ID, timestamp, source metadata, or path.
The orchestrator supplies those values. Greetings and one-post instructions
are represented by explicit no-save decisions. Events record whether a save
was chosen and the generated fact reference, never the private fact content.

The Critic returns `accept` with no issues or `revise` with concrete category,
summary, issue type, source evidence, required change, and an exact
`draft_excerpt` for present-content allegations. Omission issues need no
draft excerpt, but must provide request evidence, an exact source-evidence
substring, exact source-backed required content, and
`rule_compatibility="supported"`. User requests are subordinate to operating
rules and source factuality; request text alone cannot establish a factual
requirement. Before a revision can consume budget, the orchestrator verifies
present-content excerpts and every source-backed omission field against the
exact request, source, and draft. Missing-content feedback sent to the Executor
is reduced to the validated required content rather than free-form model
instructions. Invalid grounding emits `critic_grounding_rejected`, fails
explicitly, and creates no revision version.

## Revision and approval rules

Round 0 is the initial Executor draft. The first accepted Critic revision
request creates revision 1; the second creates revision 2. A further Critic
revision request blocks the run before another Executor round.

Identical consecutive Critic feedback blocks as `stalled_revision`. An
unchanged Executor draft after revision feedback blocks as `stalled_draft`.
Role step budgets also prevent unbounded tool loops.

Critic acceptance never finalizes a draft itself. The orchestrator records an
approval request for the exact version and calls the configured `ApprovalGate`
immediately before finalization. Approval completes the run. Decline blocks
it. Missing or failing approval cannot produce a successful result.

Every valid Critic verdict emits `critic_review_completed`. Acceptance also
creates a Critic-to-Orchestrator handoff; revision continues to use the
Critic-to-Executor handoff. These records identify the reviewed version,
verdict, issue count/categories, grounded excerpts, and summary.

## Trace and redaction policy

Events record actor, deterministic sequence, model-turn/tool counts,
retrieval counts, version and handoff references, revision rounds, approval
state, and sanitized terminal codes. Handoffs retain result summaries or
structured Critic issues and exact reviewed version references.

The practical Stage 3 redaction policy is:

- document text lives in immutable document versions, not event payloads;
- private fact content lives in the private store and transient tool result,
  not events or handoffs;
- shared-comment bodies live in the comment table and transient tool result,
  not event payloads;
- raw role responses, SQL errors, provider IDs, paths, and secrets are not
  persisted;
- errors persist sanitized codes only.

Migration 002 extends the closed event vocabulary with memory-decision,
fact-saved, and revision-limit events while upgrading existing schema-version-1
databases to version 2.

## Monitor bundle compatibility

Successful terminal runs retain ordered events, handoffs, the original source
snapshot, and every run-created version. The repository combines these with
trusted rule snapshots into the existing `CompletedRunBundle`. The bundle
schema remains version 1 and backward-compatible; consumers such as Nina's
future Monitor should now expect the source as the first document snapshot and
can read explicit Critic verdict records. This stage does not implement or
invoke Monitor judgment.

## Testing and deferred work

Tests use scripted `FakeModelClient` responses, temporary SQLite and memory
roots, copied Markdown rules, deterministic clocks and IDs, and fake approval
gates. They do not call Gemini or the network.

Still deferred:

- polished CLI integration and final evidence/demo scripts;
- Nina's independent Monitor implementation and merge;
- Monitor scheduling and report persistence;
- external scheduling;
- external publication and LinkedIn integration.
