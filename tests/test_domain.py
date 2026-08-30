from __future__ import annotations

import unittest
from datetime import UTC, datetime

from legal_monitor.domain.enums import SourceSystem
from legal_monitor.domain.models import Movement


class MovementTests(unittest.TestCase):
    def test_fingerprint_is_stable_under_whitespace_and_case(self) -> None:
        observed = datetime(2026, 8, 30, tzinfo=UTC)
        first = Movement(
            source=SourceSystem.FAKE,
            source_event_id=None,
            event_at=None,
            observed_at=observed,
            type_raw="Decisão",
            type_normalized="DECISAO",
            description="Texto   fictício",
        )
        second = Movement(
            source=SourceSystem.FAKE,
            source_event_id=None,
            event_at=None,
            observed_at=observed,
            type_raw="decisão",
            type_normalized="decisao",
            description="texto fictício",
        )
        self.assertEqual(first.fingerprint, second.fingerprint)

    def test_requires_timezone_aware_observation(self) -> None:
        with self.assertRaisesRegex(ValueError, "fuso horário"):
            Movement(
                source=SourceSystem.FAKE,
                source_event_id="1",
                event_at=None,
                observed_at=datetime(2026, 8, 30),
                type_raw="Teste",
                type_normalized="teste",
                description="Fixture",
            )


if __name__ == "__main__":
    unittest.main()
