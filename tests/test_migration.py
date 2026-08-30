from __future__ import annotations

import re
import unittest
from pathlib import Path


class MigrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.sql = Path("migrations/001_foundation.sql").read_text(encoding="utf-8")

    def test_contains_all_required_entities(self) -> None:
        required = {
            "legal_process",
            "process_system_history",
            "monitor_state",
            "source_check",
            "movement",
            "document",
            "summary",
            "trigger_event",
            "job",
            "job_attempt",
            "manual_action",
            "notification_outbox",
            "notification_attempt",
            "audit_event",
        }
        created = set(re.findall(r"CREATE TABLE\s+(\w+)", self.sql, re.IGNORECASE))
        self.assertTrue(required.issubset(created), required - created)

    def test_contains_idempotency_and_sha_constraints(self) -> None:
        self.assertIn("movement_source_event_uq", self.sql)
        self.assertIn("movement_fingerprint_uq", self.sql)
        self.assertIn("idempotency_key char(64) NOT NULL UNIQUE", self.sql)
        self.assertIn("document_sha256", self.sql)

    def test_uses_timezone_aware_timestamps(self) -> None:
        self.assertNotRegex(self.sql, r"\btimestamp\s+(?!with time zone)")
        self.assertIn("timestamptz", self.sql)


if __name__ == "__main__":
    unittest.main()
