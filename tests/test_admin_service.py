from __future__ import annotations

import unittest
from datetime import UTC, datetime
from uuid import UUID

from legal_monitor.admin.models import LawyerRecord
from legal_monitor.admin.service import AdminService, AdminValidationError
from legal_monitor.domain.cnj import CnjNumber


class MemoryAdminRepository:
    def __init__(self) -> None:
        self.lawyer_values: dict[str, object] | None = None

    def register_lawyer(self, **values: object) -> LawyerRecord:
        self.lawyer_values = values
        return LawyerRecord(
            id=UUID("00000000-0000-0000-0000-000000000001"),
            reference_code=str(values["reference_code"]),
            display_name=str(values["display_name"]),
            active=True,
            created_at=values["occurred_at"],  # type: ignore[arg-type]
            created=True,
        )


class AdminServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repository = MemoryAdminRepository()
        self.service = AdminService(self.repository)  # type: ignore[arg-type]
        self.now = datetime(2026, 8, 31, 12, 0, tzinfo=UTC)

    def test_normalizes_lawyer_reference_and_display_name(self) -> None:
        record = self.service.register_lawyer(
            reference_code=" ADV-DEMO ",
            display_name="Advogado   Demonstrativo",
            actor_id="local-admin",
            now=self.now,
        )
        self.assertEqual(record.reference_code, "adv-demo")
        self.assertEqual(record.display_name, "Advogado Demonstrativo")

    def test_rejects_invalid_reference_code(self) -> None:
        with self.assertRaisesRegex(AdminValidationError, "Código"):
            self.service.register_lawyer(
                reference_code="A!",
                display_name="Advogado Demonstrativo",
                actor_id="local-admin",
                now=self.now,
            )

    def test_rejects_non_tjrj_process_in_mvp(self) -> None:
        other_court = CnjNumber.from_components(
            sequence=1,
            year=2026,
            justice=8,
            tribunal=1,
            origin=1,
        )
        with self.assertRaisesRegex(AdminValidationError, "Aceitos"):
            self.service.register_process(
                cnj_value=str(other_court),
                lawyer_reference="adv-demo",
                actor_id="local-admin",
                now=self.now,
            )


if __name__ == "__main__":
    unittest.main()
