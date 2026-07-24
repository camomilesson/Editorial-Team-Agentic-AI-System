# S3 Submission — Andrei Romashkov

We built a small alpha of an agentic editorial system.

Current workflow:

```text
stored press release
→ LinkedIn post
→ versioned draft storage
→ verification
→ human approval
→ local publication outbox
```

The scope is intentionally narrow. The point was not to build the whole “AI editorial team” yet, but to make one workflow actually work end to end.

Gemini handles reasoning and text generation, but the control flow is ours. `AgentRunner` runs a simple observe → reason → act → verify loop: it sends the request and available tools to the model, executes tool calls, returns results back to the model, and keeps going until the model answers or hits a stop condition.

The explicit stop reasons are:

* `answered`
* `max_steps`
* `model_error`

The agent has four custom tools:

* `read_press_release`
* `save_linkedin_draft`
* `read_linkedin_draft`
* `publish_linkedin_post`

Tool arguments are checked against JSON Schemas before execution. Unknown tools, invalid arguments, storage errors, and publication errors go back to the model as structured observations. Unexpected handler crashes go through a separate `tool_error` branch.

The first three tools are reversible or at least non-destructive, so they do not need approval. Publication does.

Before `publish_linkedin_post` runs, the user sees the action and its arguments. It proceeds only after the exact input `YES`. Anything else counts as a decline, and the publication handler is not called.

“Publication” here means writing the final post into a local append-only outbox, not posting to the actual LinkedIn API. Only drafts marked as `final` can be published, and the same version cannot be published twice.

## Division of work

I implemented the model contracts, Gemini adapter, core agent loop, stopping logic, traces, registry integration, schema validation, approval gate, publication outbox, CLI, and end-to-end integration.

I delegated the storage layer and the three reversible editorial tools to Nina Perišić.

Her part added:

* filesystem project storage;
* versioned LinkedIn drafts;
* reading a stored press release;
* saving a draft;
* reading a saved draft back for verification.

She worked on a separate branch, and I merged it without squashing so her commit stays visible. After that, I connected her tools to the registry and the agent loop.

## Class ideas used

The main course ideas we used:

* tools as actual constrained actions, not vague abilities;
* clear tool names and descriptions of when to use them;
* observe → reason → act → verify;
* explicit stopping;
* tool errors returned as observations;
* a separate branch for unexpected tool failures;
* different guarantees for reversible and irreversible actions;
* human approval immediately before the irreversible step;
* fake-model testing instead of relying on live LLM behavior.

The approval flow is basically the guarantee ladder from class: reads and versioned saves stay easy, publication gets the stronger check.

## Testing

Most tests use `FakeModelClient`, so they are deterministic and do not depend on Gemini behaving nicely that day.

The suite covers:

* normal model answers;
* tool calls and continuation turns;
* multiple tool calls;
* max-step and model-error stopping;
* schema validation;
* unknown tools;
* malformed tool output;
* handler exceptions;
* versioned storage;
* publication rules;
* approval;
* decline;
* missing approval gate;
* path containment.

The end-to-end tests use the real loop, registry, tools, storage, and publication outbox with temporary directories.

One test approves publication and checks that the published file exactly matches the saved final draft. Another declines and checks that no publication file is created.

Network access is blocked in tests. We also ran the workflow live with Gemini to check the real tool loop and terminal approval.
