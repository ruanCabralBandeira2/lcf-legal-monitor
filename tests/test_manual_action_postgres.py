from __future__ import annotations

import os
import unittest
import uuid
from datetime import UTC, datetime

import psycopg

from legal_monitor.connectors.routing import CATALOG
from legal_monitor.domain.enums import SessionState
from legal_monitor.monitoring.auth_alert import AuthAlertService
from legal_monitor.monitoring.repository import PostgresManualActionStore
from legal_monitor.notifications.base import NotificationMessage, NotificationReceipt

DATABASE_URL = os.environ.get("TEST_DATABASE_URL")


class CountingNotifier:
    def __init__(self) -> None:
        self.sent = 0

    def send(self, message: NotificationMessage) -> NotificationReceipt:
        del message
        self.sent += 1
        return NotificationReceipt(channel="TEST", provider_id=None, accepted=True)


@unittest.skipUnless(DATABASE_URL, "TEST_DATABASE_URL não configurada")
class PostgresManualActionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store = PostgresManualActionStore(DATABASE_URL or "")
        self.connector = f"test-source-{uuid.uuid4().hex[:8]}"
        self.now = datetime.now(UTC)

    def tearDown(self) -> None:
        with psycopg.connect(DATABASE_URL) as connection:
            ids = [
                row[0]
                for row in connection.execute(
                    "SELECT id FROM manual_action WHERE connector = %s", (self.connector,)
                ).fetchall()
            ]
            if ids:
                connection.execute(
                    "DELETE FROM audit_event WHERE entity_type = 'manual_action' "
                    "AND entity_id = ANY(%s)",
                    (ids,),
                )
                connection.execute("DELETE FROM manual_action WHERE id = ANY(%s)", (ids,))

    def _open(self) -> bool:
        return self.store.open_source_action(
            action_type="AUTH_REQUIRED",
            connector=self.connector,
            opened_at=self.now,
            correlation_id=uuid.uuid4(),
        )

    def test_only_one_open_action_per_source(self) -> None:
        self.assertTrue(self._open())
        self.assertFalse(self._open())
        self.assertEqual(
            self.store.resolve_source_actions(connector=self.connector, resolved_at=self.now), 1
        )
        self.assertTrue(self._open())

    def test_service_notifies_once_with_real_store(self) -> None:
        notifier = CountingNotifier()
        service = AuthAlertService(self.store, notifier)
        endpoint = CATALOG["eproc-trf2"]
        # Conector real do catálogo compartilharia estado com a operação; isola pelo nome.
        endpoint = type(endpoint)(
            key=self.connector,
            tribunal=endpoint.tribunal,
            system=endpoint.system,
            base_url=endpoint.base_url,
            auth_realm=endpoint.auth_realm,
            notes=endpoint.notes,
        )
        service.handle(endpoint, SessionState.AUTH_REQUIRED, now=self.now)
        service.handle(endpoint, SessionState.AUTH_REQUIRED, now=self.now)
        self.assertEqual(notifier.sent, 1)
        with psycopg.connect(DATABASE_URL) as connection:
            audits = connection.execute(
                "SELECT count(*) FROM audit_event a JOIN manual_action m ON m.id = a.entity_id "
                "WHERE m.connector = %s AND a.action = 'MANUAL_ACTION_OPENED'",
                (self.connector,),
            ).fetchone()
        self.assertEqual(audits[0], 1)


if __name__ == "__main__":
    unittest.main()
