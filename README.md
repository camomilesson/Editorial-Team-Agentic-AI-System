# Editorial Agent

An agentic workflow that turns a stored press release into a versioned LinkedIn
post and requires explicit human approval before publication.

## S3 alpha scope

The initial system will:

1. Read a press release from project storage.
2. Generate a LinkedIn post from the supplied facts.
3. Save the post as a versioned draft.
4. Read the saved version back for verification.
5. Require human approval before placing it in the publication outbox.
6. Return tool failures to the agent as explicit error observations.

The alpha uses a local publication outbox. It does not post to LinkedIn directly.

## Architecture

The project will separate:

- the model adapter;
- the handwritten agent loop;
- tool schemas and dispatch;
- editorial storage;
- the approval gate;
- the command-line interface.

## Development setup

Requires Python 3.11.

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
```
