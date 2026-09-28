-- Monitor periódico (ADR-009): lembra em qual fonte do catálogo o processo foi encontrado.
ALTER TABLE process_system_history ADD COLUMN source_key text;

-- Uma única linha de documento por (movimento, referência na fonte) já é garantida;
-- este índice acelera a checagem de movimentos conhecidos por processo e fonte.
CREATE INDEX IF NOT EXISTS movement_process_source_idx ON movement (process_id, source);
