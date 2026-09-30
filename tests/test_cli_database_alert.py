from __future__ import annotations

import os
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

from legal_monitor.cli import alert_database_down
from legal_monitor.notifications.base import NotificationMessage, NotificationReceipt


class RecordingNotifier:
    def __init__(self) -> None:
        self.sent: list[NotificationMessage] = []

    def send(self, message: NotificationMessage) -> NotificationReceipt:
        self.sent.append(message)
        return NotificationReceipt("TEST", None, True)


class DatabaseDownAlertTests(unittest.TestCase):
    def test_alerts_once_every_six_hours(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            marker = Path(temporary) / "alerta-banco-fora.txt"
            notifier = RecordingNotifier()
            now = datetime(2026, 9, 30, 18, tzinfo=UTC)
            self.assertTrue(alert_database_down(marker, notifier, now))
            self.assertFalse(alert_database_down(marker, notifier, now + timedelta(hours=1)))
            self.assertEqual(len(notifier.sent), 1)
            self.assertIn("Docker Desktop", notifier.sent[0].body)
            # Marcador antigo (mais de 6 h): avisa de novo.
            old = (now - timedelta(hours=7)).timestamp()
            os.utime(marker, (old, old))
            self.assertTrue(alert_database_down(marker, notifier, now))
            self.assertEqual(len(notifier.sent), 2)


if __name__ == "__main__":
    unittest.main()
