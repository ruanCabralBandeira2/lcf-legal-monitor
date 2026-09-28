from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from legal_monitor.domain.cnj import CnjNumber
from legal_monitor.domain.models import DocumentRecord, Movement


@dataclass(frozen=True, slots=True)
class MonitoredProcess:
    id: uuid.UUID
    cnj: CnjNumber
    tribunal: str
    source_key: str | None
    sensitivity: str = "CONFIDENTIAL"


class PostgresMonitorRepository:
    def __init__(self, database_url: str) -> None:
        self._url = database_url.replace("postgresql+psycopg://", "postgresql://", 1)

    def _connect(self) -> Any:
        import psycopg
        from psycopg.rows import dict_row

        return psycopg.connect(self._url, row_factory=dict_row)

    def active_processes(self) -> tuple[MonitoredProcess, ...]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT p.id, p.numero_cnj, p.tribunal, h.source_key, p.sensitivity
                  FROM legal_process p
                  LEFT JOIN process_system_history h
                    ON h.process_id = p.id AND h.ended_at IS NULL
                 WHERE p.active AND p.deleted_at IS NULL
                 ORDER BY p.created_at
                """
            ).fetchall()
        return tuple(
            MonitoredProcess(
                row["id"],
                CnjNumber(row["numero_cnj"]),
                row["tribunal"],
                row["source_key"],
                row["sensitivity"],
            )
            for row in rows
        )

    def lookups(self) -> dict[tuple[uuid.UUID, str], tuple[str, datetime]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT process_id, source_key, result, checked_at FROM source_lookup"
            ).fetchall()
        return {
            (row["process_id"], row["source_key"]): (row["result"], row["checked_at"])
            for row in rows
        }

    def record_lookup(
        self,
        process_id: uuid.UUID,
        source_key: str,
        *,
        result: str,
        detail: str | None,
        at: datetime,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO source_lookup (process_id, source_key, result, detail, checked_at)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (process_id, source_key) DO UPDATE
                   SET result = EXCLUDED.result,
                       detail = EXCLUDED.detail,
                       checked_at = EXCLUDED.checked_at
                """,
                (process_id, source_key, result, detail, at),
            )

    def statuses(self) -> dict[uuid.UUID, tuple[str, datetime | None]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT process_id, status, last_success_at FROM monitor_state"
            ).fetchall()
        return {row["process_id"]: (row["status"], row["last_success_at"]) for row in rows}

    def known_fingerprints(self, process_id: uuid.UUID, source: str) -> set[str]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT fingerprint FROM movement WHERE process_id = %s AND source = %s",
                (process_id, source),
            ).fetchall()
        return {row["fingerprint"] for row in rows}

    def record_source(
        self, process_id: uuid.UUID, *, system: str, source_key: str, at: datetime
    ) -> None:
        with self._connect() as connection:
            current = connection.execute(
                "SELECT id, source_key FROM process_system_history "
                "WHERE process_id = %s AND ended_at IS NULL",
                (process_id,),
            ).fetchone()
            if current and current["source_key"] == source_key:
                return
            if current:
                connection.execute(
                    "UPDATE process_system_history SET ended_at = %s WHERE id = %s",
                    (at, current["id"]),
                )
            connection.execute(
                """
                INSERT INTO process_system_history
                    (id, process_id, system, detected_at, evidence_ref, confidence, source_key)
                VALUES (%s, %s, %s, %s, %s, 1, %s)
                """,
                (uuid.uuid4(), process_id, system, at, f"monitor://{source_key}", source_key),
            )

    def insert_movement(
        self, process_id: uuid.UUID, movement: Movement, correlation_id: uuid.UUID
    ) -> uuid.UUID | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                INSERT INTO movement (id, process_id, source, source_event_id, event_at,
                    observed_at, type_raw, type_normalized, description, fingerprint,
                    correlation_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT DO NOTHING
                RETURNING id
                """,
                (
                    uuid.uuid4(),
                    process_id,
                    movement.source.value if hasattr(movement.source, "value") else movement.source,
                    movement.source_event_id,
                    movement.event_at,
                    movement.observed_at,
                    movement.type_raw,
                    movement.type_normalized,
                    movement.description,
                    movement.fingerprint,
                    correlation_id,
                ),
            ).fetchone()
        return row["id"] if row else None

    def insert_document(
        self, movement_id: uuid.UUID, source_ref: str, record: DocumentRecord
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO document (id, movement_id, source_ref, storage_path, mime, bytes,
                    page_count, sha256, collected_at, text_extractable)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT DO NOTHING
                """,
                (
                    uuid.uuid4(),
                    movement_id,
                    source_ref,
                    str(record.storage_path),
                    record.mime,
                    record.bytes,
                    record.page_count,
                    record.sha256,
                    record.collected_at,
                    record.text_extractable,
                ),
            )

    def mark_checked(
        self, process_id: uuid.UUID, *, status: str, at: datetime, success: bool
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE monitor_state
                   SET status = %s,
                       last_attempt_at = %s,
                       last_success_at = CASE WHEN %s THEN %s ELSE last_success_at END,
                       consecutive_failures = CASE WHEN %s THEN 0
                                                   ELSE consecutive_failures + 1 END,
                       updated_at = %s
                 WHERE process_id = %s
                """,
                (status, at, success, at, success, at, process_id),
            )
