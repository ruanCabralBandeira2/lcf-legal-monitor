CREATE TABLE lawyer (
    id uuid PRIMARY KEY,
    display_name text NOT NULL,
    active boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now(),
    deleted_at timestamptz,
    CONSTRAINT lawyer_display_name_not_blank CHECK (btrim(display_name) <> '')
);

CREATE TABLE legal_process (
    id uuid PRIMARY KEY,
    numero_cnj char(20) NOT NULL,
    tribunal text NOT NULL,
    active boolean NOT NULL DEFAULT true,
    lawyer_id uuid NOT NULL REFERENCES lawyer(id),
    sensitivity text NOT NULL DEFAULT 'CONFIDENTIAL',
    created_at timestamptz NOT NULL DEFAULT now(),
    deleted_at timestamptz,
    CONSTRAINT legal_process_numero_cnj_digits CHECK (numero_cnj ~ '^[0-9]{20}$'),
    CONSTRAINT legal_process_sensitivity CHECK (
        sensitivity IN ('INTERNAL', 'CONFIDENTIAL', 'RESTRICTED')
    )
);

CREATE UNIQUE INDEX legal_process_numero_cnj_active_uq
    ON legal_process (numero_cnj)
    WHERE deleted_at IS NULL;

CREATE TABLE process_system_history (
    id uuid PRIMARY KEY,
    process_id uuid NOT NULL REFERENCES legal_process(id),
    system text NOT NULL,
    detected_at timestamptz NOT NULL,
    evidence_ref text,
    confidence numeric(4,3) NOT NULL,
    ended_at timestamptz,
    CONSTRAINT process_system_value CHECK (
        system IN ('LEGACY_DCP', 'PJE', 'EPROC', 'UNKNOWN', 'MIGRATING')
    ),
    CONSTRAINT process_system_confidence CHECK (confidence >= 0 AND confidence <= 1),
    CONSTRAINT process_system_interval CHECK (ended_at IS NULL OR ended_at >= detected_at)
);

CREATE UNIQUE INDEX process_system_one_current_uq
    ON process_system_history (process_id)
    WHERE ended_at IS NULL;

CREATE TABLE monitor_state (
    process_id uuid PRIMARY KEY REFERENCES legal_process(id),
    status text NOT NULL,
    last_attempt_at timestamptz,
    last_success_at timestamptz,
    next_check_at timestamptz,
    consecutive_failures integer NOT NULL DEFAULT 0,
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT monitor_status_value CHECK (status IN (
        'ACTIVE_HEALTHY', 'RETRY_SCHEDULED', 'AUTH_REQUIRED', 'CAPTCHA_REQUIRED',
        'MANUAL_ACTION_OPEN', 'SOURCE_DIVERGENCE', 'MIGRATION_DETECTED',
        'STALE_ALERTING', 'DISABLED'
    )),
    CONSTRAINT monitor_failures_nonnegative CHECK (consecutive_failures >= 0),
    CONSTRAINT monitor_success_after_attempt CHECK (
        last_success_at IS NULL OR last_attempt_at IS NULL OR last_success_at <= last_attempt_at
    )
);

CREATE TABLE source_check (
    id uuid PRIMARY KEY,
    process_id uuid NOT NULL REFERENCES legal_process(id),
    connector text NOT NULL,
    started_at timestamptz NOT NULL,
    ended_at timestamptz,
    result text NOT NULL,
    cursor text,
    correlation_id uuid NOT NULL,
    error_code text,
    raw_snapshot_ref text,
    CONSTRAINT source_check_result CHECK (result IN ('RUNNING', 'SUCCESS', 'FAILED', 'BLOCKED')),
    CONSTRAINT source_check_interval CHECK (ended_at IS NULL OR ended_at >= started_at),
    CONSTRAINT source_check_error_consistency CHECK (
        (result IN ('FAILED', 'BLOCKED') AND error_code IS NOT NULL)
        OR (result IN ('RUNNING', 'SUCCESS') AND error_code IS NULL)
    )
);

CREATE INDEX source_check_process_started_idx ON source_check (process_id, started_at DESC);
CREATE INDEX source_check_correlation_idx ON source_check (correlation_id);

CREATE TABLE movement (
    id uuid PRIMARY KEY,
    process_id uuid NOT NULL REFERENCES legal_process(id),
    source text NOT NULL,
    source_event_id text,
    event_at timestamptz,
    observed_at timestamptz NOT NULL,
    type_raw text NOT NULL,
    type_normalized text NOT NULL,
    description text NOT NULL,
    fingerprint char(64) NOT NULL,
    raw_payload_ref text,
    correlation_id uuid NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT movement_fingerprint_sha256 CHECK (fingerprint ~ '^[0-9a-f]{64}$')
);

CREATE UNIQUE INDEX movement_source_event_uq
    ON movement (process_id, source, source_event_id)
    WHERE source_event_id IS NOT NULL;
CREATE UNIQUE INDEX movement_fingerprint_uq ON movement (process_id, source, fingerprint);
CREATE INDEX movement_observed_idx ON movement (process_id, observed_at DESC);

CREATE TABLE document (
    id uuid PRIMARY KEY,
    movement_id uuid NOT NULL REFERENCES movement(id),
    source_ref text NOT NULL,
    storage_path text NOT NULL UNIQUE,
    mime text NOT NULL,
    bytes bigint NOT NULL,
    page_count integer NOT NULL,
    sha256 char(64) NOT NULL,
    collected_at timestamptz NOT NULL,
    text_extractable boolean NOT NULL DEFAULT false,
    CONSTRAINT document_pdf_mime CHECK (mime = 'application/pdf'),
    CONSTRAINT document_bytes_positive CHECK (bytes > 0),
    CONSTRAINT document_pages_positive CHECK (page_count > 0),
    CONSTRAINT document_sha256 CHECK (sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT document_movement_source_uq UNIQUE (movement_id, source_ref)
);

CREATE INDEX document_sha256_idx ON document (sha256);

CREATE TABLE summary (
    id uuid PRIMARY KEY,
    document_id uuid NOT NULL REFERENCES document(id),
    schema_version text NOT NULL,
    prompt_version text NOT NULL,
    model_ref text NOT NULL,
    output_json jsonb NOT NULL,
    confidence numeric(4,3),
    review_status text NOT NULL DEFAULT 'REVIEW_REQUIRED',
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT summary_confidence CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1)),
    CONSTRAINT summary_review_status CHECK (
        review_status IN ('REVIEW_REQUIRED', 'APPROVED', 'REJECTED', 'UNAVAILABLE')
    ),
    CONSTRAINT summary_document_schema_uq UNIQUE (document_id, schema_version, prompt_version)
);

CREATE TABLE trigger_event (
    id uuid PRIMARY KEY,
    type text NOT NULL,
    external_id text,
    received_at timestamptz NOT NULL,
    payload_hash char(64) NOT NULL,
    payload_ref text NOT NULL,
    process_id uuid REFERENCES legal_process(id),
    status text NOT NULL,
    correlation_id uuid NOT NULL,
    CONSTRAINT trigger_payload_hash CHECK (payload_hash ~ '^[0-9a-f]{64}$'),
    CONSTRAINT trigger_status CHECK (status IN ('RECEIVED', 'MAPPED', 'QUARANTINED', 'PROCESSED'))
);

CREATE UNIQUE INDEX trigger_type_external_uq
    ON trigger_event (type, external_id)
    WHERE external_id IS NOT NULL;
CREATE UNIQUE INDEX trigger_type_payload_uq ON trigger_event (type, payload_hash);

CREATE TABLE job (
    id uuid PRIMARY KEY,
    type text NOT NULL,
    process_id uuid REFERENCES legal_process(id),
    due_at timestamptz NOT NULL,
    lease_until timestamptz,
    attempt integer NOT NULL DEFAULT 0,
    status text NOT NULL,
    correlation_id uuid NOT NULL,
    error_code text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT job_attempt_nonnegative CHECK (attempt >= 0),
    CONSTRAINT job_status CHECK (status IN ('PENDING', 'LEASED', 'RUNNING', 'SUCCEEDED', 'FAILED', 'PAUSED'))
);

CREATE INDEX job_due_idx ON job (due_at) WHERE status = 'PENDING';
CREATE INDEX job_lease_idx ON job (lease_until) WHERE status IN ('LEASED', 'RUNNING');

CREATE TABLE job_attempt (
    id uuid PRIMARY KEY,
    job_id uuid NOT NULL REFERENCES job(id),
    attempt integer NOT NULL,
    started_at timestamptz NOT NULL,
    ended_at timestamptz,
    status text NOT NULL,
    correlation_id uuid NOT NULL,
    error_code text,
    CONSTRAINT job_attempt_number_positive CHECK (attempt > 0),
    CONSTRAINT job_attempt_status CHECK (status IN ('RUNNING', 'SUCCEEDED', 'FAILED', 'BLOCKED')),
    CONSTRAINT job_attempt_interval CHECK (ended_at IS NULL OR ended_at >= started_at),
    CONSTRAINT job_attempt_uq UNIQUE (job_id, attempt)
);

CREATE TABLE manual_action (
    id uuid PRIMARY KEY,
    type text NOT NULL,
    status text NOT NULL,
    process_id uuid REFERENCES legal_process(id),
    connector text,
    opened_at timestamptz NOT NULL,
    assigned_to text,
    resolved_at timestamptz,
    resolution text,
    correlation_id uuid NOT NULL,
    CONSTRAINT manual_action_type CHECK (type IN (
        'AUTH_REQUIRED', 'CAPTCHA_REQUIRED', 'SOURCE_DIVERGENCE', 'MIGRATION_REVIEW',
        'DOCUMENT_INVALID', 'PARSE_REVIEW'
    )),
    CONSTRAINT manual_action_status CHECK (status IN ('OPEN', 'IN_PROGRESS', 'RESOLVED', 'CANCELLED')),
    CONSTRAINT manual_action_resolution CHECK (
        (status IN ('RESOLVED', 'CANCELLED') AND resolved_at IS NOT NULL AND resolution IS NOT NULL)
        OR (status IN ('OPEN', 'IN_PROGRESS') AND resolved_at IS NULL)
    )
);

CREATE INDEX manual_action_open_idx ON manual_action (opened_at) WHERE status IN ('OPEN', 'IN_PROGRESS');

CREATE TABLE notification_outbox (
    id uuid PRIMARY KEY,
    recipient_id uuid NOT NULL REFERENCES lawyer(id),
    document_id uuid REFERENCES document(id),
    channel text NOT NULL,
    idempotency_key char(64) NOT NULL UNIQUE,
    payload_ref text NOT NULL,
    status text NOT NULL,
    next_attempt_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT notification_idempotency_sha256 CHECK (idempotency_key ~ '^[0-9a-f]{64}$'),
    CONSTRAINT notification_channel CHECK (channel IN ('WHATSAPP', 'SECONDARY', 'FAKE')),
    CONSTRAINT notification_status CHECK (status IN ('PENDING', 'SENDING', 'SENT', 'DELIVERED', 'READ', 'FAILED', 'DEAD_LETTER'))
);

CREATE INDEX notification_pending_idx
    ON notification_outbox (next_attempt_at)
    WHERE status IN ('PENDING', 'FAILED');

CREATE TABLE notification_attempt (
    id uuid PRIMARY KEY,
    outbox_id uuid NOT NULL REFERENCES notification_outbox(id),
    attempted_at timestamptz NOT NULL,
    provider_id text,
    result text NOT NULL,
    error_code text,
    CONSTRAINT notification_attempt_result CHECK (result IN ('SENT', 'DELIVERED', 'FAILED'))
);

CREATE TABLE audit_event (
    id uuid PRIMARY KEY,
    actor_type text NOT NULL,
    actor_id text,
    action text NOT NULL,
    entity_type text NOT NULL,
    entity_id uuid NOT NULL,
    at timestamptz NOT NULL,
    correlation_id uuid NOT NULL,
    metadata_json jsonb NOT NULL DEFAULT '{}'::jsonb,
    CONSTRAINT audit_actor_type CHECK (actor_type IN ('SYSTEM', 'ADMIN', 'OPERATOR', 'LAWYER')),
    CONSTRAINT audit_metadata_object CHECK (jsonb_typeof(metadata_json) = 'object')
);

CREATE INDEX audit_entity_idx ON audit_event (entity_type, entity_id, at DESC);
CREATE INDEX audit_correlation_idx ON audit_event (correlation_id, at);
