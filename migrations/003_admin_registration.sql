ALTER TABLE lawyer
    ADD COLUMN reference_code text,
    ADD COLUMN updated_at timestamptz NOT NULL DEFAULT now();

UPDATE lawyer
SET reference_code = 'legacy-' || id::text
WHERE reference_code IS NULL;

ALTER TABLE lawyer
    ALTER COLUMN reference_code SET NOT NULL,
    ADD CONSTRAINT lawyer_reference_code_format CHECK (
        reference_code ~ '^[a-z0-9][a-z0-9_-]{2,63}$'
    );

CREATE UNIQUE INDEX lawyer_reference_code_uq ON lawyer (reference_code);

ALTER TABLE monitor_state DROP CONSTRAINT monitor_status_value;

ALTER TABLE monitor_state
    ADD CONSTRAINT monitor_status_value CHECK (status IN (
        'PENDING_INITIAL_CHECK', 'ACTIVE_HEALTHY', 'RETRY_SCHEDULED',
        'AUTH_REQUIRED', 'CAPTCHA_REQUIRED', 'MANUAL_ACTION_OPEN',
        'SOURCE_DIVERGENCE', 'MIGRATION_DETECTED', 'STALE_ALERTING', 'DISABLED'
    ));

CREATE INDEX legal_process_lawyer_active_idx
    ON legal_process (lawyer_id, created_at DESC)
    WHERE active AND deleted_at IS NULL;
