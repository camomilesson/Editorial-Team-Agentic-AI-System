# Stage 2 storage, authorization, and context services

Stage 2 implements the three local storage boundaries defined in Stage 1.
These services are not connected to the existing live CLI or `AgentRunner`.

## SQLite structured domain storage

`SQLiteDatabase` initializes `migrations/001_initial_domain.sql`, records
schema version 1 with `PRAGMA user_version`, enables foreign keys for every
connection, and exposes explicit transactions. Initialization is repeatable.

`SQLiteDomainRepository` persists users, documents, access grants, immutable
document versions, shared comments, workflow runs, events, and handoffs.
Version allocation uses `BEGIN IMMEDIATE`, checks the next per-document
sequence number, and never overwrites earlier content. Event and handoff
payloads use stable sorted JSON.

Authorization is deterministic:

- the document owner receives `owner` access during document creation;
- only the owner can grant collaborator access;
- `read` permits retrieval and shared comments;
- `edit` additionally permits new immutable versions;
- an unrelated user has no document, version, comment, or run access.

Document-ID possession alone never grants access.

## Private JSON facts

`JsonPrivateFactStore` writes one schema-versioned JSON file per validated user
under a trusted configured root. Callers supply a typed user ID, never a
filename. Reads open only that user's derived file, and writes use a temporary
file in the same directory followed by atomic replacement.

Facts are append-only and ordered by creation timestamp and fact ID. Retrieval
tokenizes the query, cue, and content case-insensitively:

1. cue-token overlap is the primary rank;
2. content-token overlap is secondary;
3. facts with no overlap are excluded;
4. creation time and fact ID break ties deterministically;
5. an optional positive limit truncates the ordered result.

There is no cross-user enumeration method.

## Trusted Markdown rules

`MarkdownRulesLoader` accepts a configured trusted directory and a `RuleKind`,
not an arbitrary path. Logical names map internally to `operating_rules.md`,
`critic_brief.md`, and the reserved future `monitor_rubric.md`. Each load reads
the current Markdown and returns its logical kind, source filename, content,
trust label, and SHA-256 content version. Manual edits are visible immediately.

The repository now includes:

- `config/operating_rules.md`;
- `config/critic_brief.md`.

Missing, blank, unsupported, or unreadable rule requests produce sanitized
application errors.

## Push and pull context

`EditorialContextService.build_push_context` first checks document
authorization through the repository and then attaches:

- workflow run, user, session, and document identity;
- the authorized document and latest version;
- current global operating rules;
- the Critic brief when building Critic context;
- permanent trust-boundary instructions.

It does not attach private facts or shared comments.

Separate pull operations retrieve:

- cue-matched private facts using only `WorkflowRequestContext.user_id`;
- shared comments using only the context's authorized document and user.

Comments retain `untrusted_shared_content`; their bodies remain quoted data.
All context objects are provider-neutral and make no model calls.

## Workflow history and Nina's Monitor boundary

Runs, events, and handoffs can be appended and read in deterministic order.
`build_completed_run_bundle` combines an authorized terminal run with its
events, handoffs, version snapshots, and caller-supplied trusted rule snapshots.
It only constructs the Stage 1 input contract; it does not run or judge a
Monitor. Nina can continue developing independently with
`tests/fixtures/completed_run_v1.json`.

## Still deferred

Stage 2 does not implement:

- Executor or Critic model behavior;
- the multi-agent orchestration loop;
- automatic fact-worthiness decisions or model-driven saving;
- Gemini or CLI integration for the new services;
- tool registration for memory or comments;
- event payload redaction beyond sanitized service boundaries;
- Monitor scheduling, verdict generation, or report persistence;
- migration of the existing filesystem LinkedIn drafts.
