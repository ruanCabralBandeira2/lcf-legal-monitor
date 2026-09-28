-- ADR-007: PDPJ como fonte, e-mail como canal e um aviso de login aberto por fonte.

ALTER TABLE process_system_history DROP CONSTRAINT process_system_value;
ALTER TABLE process_system_history ADD CONSTRAINT process_system_value CHECK (
    system IN ('LEGACY_DCP', 'PJE', 'EPROC', 'PDPJ', 'UNKNOWN', 'MIGRATING')
);

ALTER TABLE notification_outbox DROP CONSTRAINT notification_channel;
ALTER TABLE notification_outbox ADD CONSTRAINT notification_channel CHECK (
    channel IN ('EMAIL', 'WHATSAPP', 'SECONDARY', 'FAKE')
);

-- Sessão expirada é da fonte, não do processo: no máximo uma ação aberta por fonte/tipo.
CREATE UNIQUE INDEX manual_action_open_source_uq
    ON manual_action (type, connector)
    WHERE status IN ('OPEN', 'IN_PROGRESS') AND process_id IS NULL;
