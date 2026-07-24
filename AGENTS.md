# Editorial Agent — Coding Rules

## Project purpose

Build an agentic workflow that converts a press release into a versioned
LinkedIn post and requires explicit human approval before publication.

## Architecture rules

- Keep the model adapter separate from the core agent loop.
- Keep terminal input and output outside the core agent loop.
- The agent loop must not contain editorial file-handling logic.
- Tools must be registered through the tool registry.
- Tools must return structured success or error results.
- Do not swallow exceptions or represent failures as successful output.
- Never bypass a tool's approval requirement.
- Reversible and read-only tools should remain ungated.
- Do not allow model-generated arbitrary filesystem paths.
- Preserve earlier draft versions rather than overwriting them.
- Keep provider-specific response formats inside the model adapter.

## Scope rules

- Do not add multiple agents yet.
- Do not add a web UI, database, RAG system, or external publishing integration.
- Do not introduce an agent framework unless explicitly requested.
- Prefer simple standard Python over unnecessary abstractions.

## Testing rules

- Use deterministic fake model responses for agent-loop tests.
- Use temporary directories for storage tests.
- Test success, failure, declined approval, max-step, and stalled-loop paths.
- Run `pytest` and `ruff check .` after implementation changes.

## Working rules

- Inspect existing code before editing.
- Make small, reviewable changes.
- Explain architectural changes before making broad refactors.
- Do not commit secrets, `.env`, generated drafts, or publication output.