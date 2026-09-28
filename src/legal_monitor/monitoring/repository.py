from __future__ import annotations

import uuid
from datetime import datetime


class PostgresManualActionStore:
    def __init__(self, database_url: str) -> None:
        self._database_url = database_url.replace("postgresql+psycopg://", "postgresql://", 1)

    def open_source_action(
        self, *, action_type: str, connector: str, opened_at: datetime, correlation_id: uuid.UUID
    ) -> bool:
        import psycopg

        with psycopg.connect(self._database_url) as connection:
            row = connection.execute(
                """
                INSERT INTO manual_action (id, type, status, connector, opened_at, correlation_id)
                VALUES (%s, %s, 'OPEN', %s, %s, %s)
                ON CONFLICT (type, connector)
                    WHERE status IN ('OPEN', 'IN_PROGRESS') AND process_id IS NULL
                    DO NOTHING
                RETURNING id
                """,
                (uuid.uuid4(), action_type, connector, opened_at, correlation_id),
            ).fetchone()
            if row is not None:
                connection.execute(
                    """
                    INSERT INTO audit_event
                        (id, actor_type, actor_id, action, entity_type, entity_id, at,
                         correlation_id, metadata_json)
                    VALUES (%s, 'SYSTEM', 'auth-alert', 'MANUAL_ACTION_OPENED', 'manual_action',
                            %s, %s, %s, jsonb_build_object('type', %s::text, 'connector', %s::text))
                    """,
                    (uuid.uuid4(), row[0], opened_at, correlation_id, action_type, connector),
                )
            return row is not None

    def resolve_source_actions(self, *, connector: str, resolved_at: datetime) -> int:
        import psycopg

        with psycopg.connect(self._database_url) as connection:
            cursor = connection.execute(
                """
                UPDATE manual_action
                   SET status = 'RESOLVED', resolved_at = %s, resolution = 'SESSION_CONFIRMED'
                 WHERE connector = %s AND process_id IS NULL
                   AND type IN ('AUTH_REQUIRED', 'CAPTCHA_REQUIRED')
                   AND status IN ('OPEN', 'IN_PROGRESS')
                """,
                (resolved_at, connector),
            )
            return cursor.rowcount


class MemoryManualActionStore:
    """Somente para testes e para operar sem banco."""

    def __init__(self) -> None:
        self.open: set[tuple[str, str]] = set()

    def open_source_action(
        self, *, action_type: str, connector: str, opened_at: datetime, correlation_id: uuid.UUID
    ) -> bool:
        del opened_at, correlation_id
        key = (action_type, connector)
        if key in self.open:
            return False
        self.open.add(key)
        return True

    def resolve_source_actions(self, *, connector: str, resolved_at: datetime) -> int:
        del resolved_at
        matching = {key for key in self.open if key[1] == connector}
        self.open -= matching
        return len(matching)
