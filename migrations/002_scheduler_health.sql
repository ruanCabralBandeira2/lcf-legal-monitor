ALTER TABLE job
    ADD COLUMN idempotency_key char(64),
    ADD COLUMN max_attempts integer NOT NULL DEFAULT 4,
    ADD COLUMN lease_owner text;

ALTER TABLE job
    ADD CONSTRAINT job_idempotency_sha256 CHECK (
        idempotency_key IS NULL OR idempotency_key ~ '^[0-9a-f]{64}$'
    ),
    ADD CONSTRAINT job_max_attempts_positive CHECK (max_attempts > 0),
    ADD CONSTRAINT job_attempt_within_limit CHECK (attempt <= max_attempts),
    ADD CONSTRAINT job_lease_consistency CHECK (
        (status IN ('LEASED', 'RUNNING') AND lease_until IS NOT NULL AND lease_owner IS NOT NULL)
        OR (status NOT IN ('LEASED', 'RUNNING') AND lease_until IS NULL AND lease_owner IS NULL)
    );

CREATE UNIQUE INDEX job_idempotency_uq
    ON job (idempotency_key)
    WHERE idempotency_key IS NOT NULL;

CREATE INDEX job_claim_idx
    ON job (status, due_at, lease_until);

CREATE TABLE scheduler_heartbeat (
    worker_id text PRIMARY KEY,
    last_seen_at timestamptz NOT NULL,
    status text NOT NULL,
    details_json jsonb NOT NULL DEFAULT '{}'::jsonb,
    CONSTRAINT scheduler_worker_not_blank CHECK (btrim(worker_id) <> ''),
    CONSTRAINT scheduler_heartbeat_status CHECK (status IN ('HEALTHY', 'DEGRADED')),
    CONSTRAINT scheduler_heartbeat_details_object CHECK (
        jsonb_typeof(details_json) = 'object'
    )
);

CREATE INDEX scheduler_heartbeat_seen_idx
    ON scheduler_heartbeat (last_seen_at DESC);
