-- Resultado da procura de cada processo em cada site (ADR-009): evita procurar de novo onde
-- ele não está e mostra no sites-report por que um processo ainda não foi encontrado.
CREATE TABLE source_lookup (
    process_id uuid NOT NULL REFERENCES legal_process(id),
    source_key text NOT NULL,
    result text NOT NULL,
    detail text,
    checked_at timestamptz NOT NULL,
    PRIMARY KEY (process_id, source_key),
    CONSTRAINT source_lookup_result CHECK (
        result IN ('FOUND', 'NOT_FOUND', 'ERROR', 'AUTH_REQUIRED')
    )
);
