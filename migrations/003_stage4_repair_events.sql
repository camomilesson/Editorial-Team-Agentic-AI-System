ALTER TABLE run_events RENAME TO run_events_v2;

CREATE TABLE run_events (
    id TEXT PRIMARY KEY CHECK (length(trim(id)) > 0),
    run_id TEXT NOT NULL REFERENCES workflow_runs(id),
    sequence INTEGER NOT NULL CHECK (sequence > 0),
    timestamp TEXT NOT NULL,
    actor TEXT NOT NULL CHECK (
        actor IN ('executor', 'critic', 'monitor', 'orchestrator', 'human', 'tool')
    ),
    event_type TEXT NOT NULL CHECK (
        event_type IN (
            'run_started',
            'context_attached',
            'memory_retrieval_requested',
            'memory_retrieval_completed',
            'memory_save_decided',
            'private_fact_saved',
            'shared_comments_retrieved',
            'model_turn_completed',
            'tool_requested',
            'tool_completed',
            'approval_requested',
            'approval_resolved',
            'document_version_created',
            'handoff_created',
            'revision_requested',
            'revision_limit_reached',
            'critic_review_completed',
            'critic_grounding_rejected',
            'run_completed',
            'run_blocked',
            'run_failed'
        )
    ),
    payload_json TEXT NOT NULL CHECK (json_valid(payload_json)),
    document_version_id TEXT REFERENCES document_versions(id),
    schema_version TEXT NOT NULL CHECK (length(trim(schema_version)) > 0),
    UNIQUE (run_id, sequence)
);

INSERT INTO run_events (
    id, run_id, sequence, timestamp, actor, event_type, payload_json,
    document_version_id, schema_version
)
SELECT
    id, run_id, sequence, timestamp, actor, event_type, payload_json,
    document_version_id, schema_version
FROM run_events_v2;

DROP TABLE run_events_v2;
PRAGMA foreign_keys = ON;
