PRAGMA foreign_keys = ON;

CREATE TABLE users (
    id TEXT PRIMARY KEY
        CHECK (length(trim(id)) > 0),
    display_name TEXT NOT NULL
        CHECK (length(trim(display_name)) > 0),
    created_at TEXT NOT NULL
);

CREATE TABLE documents (
    id TEXT PRIMARY KEY
        CHECK (length(trim(id)) > 0),
    owner_user_id TEXT NOT NULL REFERENCES users(id),
    title TEXT NOT NULL
        CHECK (length(trim(title)) > 0),
    created_at TEXT NOT NULL
);

CREATE TABLE document_access (
    document_id TEXT NOT NULL REFERENCES documents(id),
    user_id TEXT NOT NULL REFERENCES users(id),
    access_level TEXT NOT NULL
        CHECK (access_level IN ('read', 'edit', 'owner')),
    created_at TEXT NOT NULL,
    PRIMARY KEY (document_id, user_id)
);

CREATE TABLE workflow_runs (
    id TEXT PRIMARY KEY
        CHECK (length(trim(id)) > 0),
    user_id TEXT NOT NULL REFERENCES users(id),
    session_id TEXT NOT NULL
        CHECK (length(trim(session_id)) > 0),
    document_id TEXT NOT NULL REFERENCES documents(id),
    request TEXT NOT NULL
        CHECK (length(trim(request)) > 0),
    status TEXT NOT NULL
        CHECK (
            status IN (
                'pending',
                'running',
                'awaiting_approval',
                'completed',
                'blocked',
                'failed'
            )
        ),
    started_at TEXT NOT NULL,
    completed_at TEXT,
    schema_version TEXT NOT NULL
        CHECK (length(trim(schema_version)) > 0),
    CHECK (
        (status IN ('completed', 'blocked', 'failed') AND completed_at IS NOT NULL)
        OR
        (status NOT IN ('completed', 'blocked', 'failed') AND completed_at IS NULL)
    )
);

CREATE TABLE document_versions (
    id TEXT PRIMARY KEY
        CHECK (length(trim(id)) > 0),
    document_id TEXT NOT NULL REFERENCES documents(id),
    version_number INTEGER NOT NULL
        CHECK (version_number > 0),
    content TEXT NOT NULL
        CHECK (length(trim(content)) > 0),
    created_by_actor TEXT NOT NULL
        CHECK (
            created_by_actor IN (
                'executor',
                'critic',
                'monitor',
                'orchestrator',
                'human',
                'tool'
            )
        ),
    created_by_user_id TEXT REFERENCES users(id),
    run_id TEXT REFERENCES workflow_runs(id),
    created_at TEXT NOT NULL,
    UNIQUE (document_id, version_number)
);

CREATE TABLE shared_comments (
    id TEXT PRIMARY KEY
        CHECK (length(trim(id)) > 0),
    document_id TEXT NOT NULL REFERENCES documents(id),
    author_user_id TEXT NOT NULL REFERENCES users(id),
    body TEXT NOT NULL
        CHECK (length(trim(body)) > 0),
    trust TEXT NOT NULL DEFAULT 'untrusted_shared_content'
        CHECK (trust = 'untrusted_shared_content'),
    created_at TEXT NOT NULL
);

CREATE TABLE run_events (
    id TEXT PRIMARY KEY
        CHECK (length(trim(id)) > 0),
    run_id TEXT NOT NULL REFERENCES workflow_runs(id),
    sequence INTEGER NOT NULL
        CHECK (sequence > 0),
    timestamp TEXT NOT NULL,
    actor TEXT NOT NULL
        CHECK (
            actor IN (
                'executor',
                'critic',
                'monitor',
                'orchestrator',
                'human',
                'tool'
            )
        ),
    event_type TEXT NOT NULL
        CHECK (
            event_type IN (
                'run_started',
                'context_attached',
                'memory_retrieval_requested',
                'memory_retrieval_completed',
                'shared_comments_retrieved',
                'model_turn_completed',
                'tool_requested',
                'tool_completed',
                'approval_requested',
                'approval_resolved',
                'document_version_created',
                'handoff_created',
                'revision_requested',
                'run_completed',
                'run_blocked',
                'run_failed'
            )
        ),
    payload_json TEXT NOT NULL
        CHECK (json_valid(payload_json)),
    document_version_id TEXT REFERENCES document_versions(id),
    schema_version TEXT NOT NULL
        CHECK (length(trim(schema_version)) > 0),
    UNIQUE (run_id, sequence)
);

CREATE TABLE agent_handoffs (
    id TEXT PRIMARY KEY
        CHECK (length(trim(id)) > 0),
    run_id TEXT NOT NULL REFERENCES workflow_runs(id),
    sequence INTEGER NOT NULL
        CHECK (sequence > 0),
    round_number INTEGER NOT NULL
        CHECK (round_number >= 0),
    from_agent TEXT NOT NULL
        CHECK (from_agent IN ('executor', 'critic', 'orchestrator', 'human', 'tool')),
    to_agent TEXT NOT NULL
        CHECK (to_agent IN ('executor', 'critic', 'orchestrator', 'human', 'tool')),
    status TEXT NOT NULL
        CHECK (status IN ('complete', 'revise', 'blocked', 'error')),
    payload_json TEXT NOT NULL
        CHECK (json_valid(payload_json)),
    document_version_id TEXT REFERENCES document_versions(id),
    created_at TEXT NOT NULL,
    schema_version TEXT NOT NULL
        CHECK (length(trim(schema_version)) > 0),
    CHECK (from_agent <> to_agent),
    UNIQUE (run_id, sequence)
);

CREATE INDEX document_access_user_idx
    ON document_access (user_id, document_id);

CREATE INDEX workflow_runs_scope_idx
    ON workflow_runs (user_id, document_id, status);

CREATE INDEX shared_comments_document_idx
    ON shared_comments (document_id, created_at);
