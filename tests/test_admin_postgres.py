from __future__ import annotations

import os
import unittest
from datetime import UTC, datetime
from uuid import UUID, uuid4

import psycopg

from legal_monitor.admin.repository import PostgresAdminRepository, ProcessConflictError
from legal_monitor.admin.service import AdminService
from legal_monitor.domain.cnj import CnjNumber
from legal_monitor.domain.enums import MonitorStatus

DATABASE_URL = os.environ.get("TEST_DATABASE_URL")


@unittest.skipUnless(DATABASE_URL, "TEST_DATABASE_URL não configurada")
class PostgresAdminIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repository = PostgresAdminRepository(DATABASE_URL or "")
        self.service = AdminService(self.repository)
        suffix = uuid4().hex[:10]
        self.lawyer_code = f"adv-{suffix}"
        self.other_lawyer_code = f"sub-{suffix}"
        sequence = (int(suffix[:6], 16) % 9_999_998) + 1
        self.cnj = CnjNumber.from_components(
            sequence=sequence,
            year=2026,
            justice=8,
            tribunal=19,
            origin=1,
        )
        self.entity_ids: set[UUID] = set()

    def tearDown(self) -> None:
        with psycopg.connect(DATABASE_URL) as connection:
            process_rows = connection.execute(
                "SELECT id FROM legal_process WHERE numero_cnj = %s", (self.cnj.digits,)
            ).fetchall()
            process_ids = [row[0] for row in process_rows]
            lawyer_rows = connection.execute(
                "SELECT id FROM lawyer WHERE reference_code = ANY(%s)",
                ([self.lawyer_code, self.other_lawyer_code],),
            ).fetchall()
            lawyer_ids = [row[0] for row in lawyer_rows]
            entity_ids = process_ids + lawyer_ids
            if entity_ids:
                connection.execute(
                    "DELETE FROM audit_event WHERE entity_id = ANY(%s)", (entity_ids,)
                )
            if process_ids:
                job_rows = connection.execute(
                    "SELECT id FROM job WHERE process_id = ANY(%s)", (process_ids,)
                ).fetchall()
                job_ids = [row[0] for row in job_rows]
                if job_ids:
                    connection.execute("DELETE FROM job_attempt WHERE job_id = ANY(%s)", (job_ids,))
                connection.execute("DELETE FROM job WHERE process_id = ANY(%s)", (process_ids,))
                connection.execute(
                    "DELETE FROM monitor_state WHERE process_id = ANY(%s)", (process_ids,)
                )
                connection.execute(
                    "DELETE FROM process_system_history WHERE process_id = ANY(%s)",
                    (process_ids,),
                )
                connection.execute("DELETE FROM legal_process WHERE id = ANY(%s)", (process_ids,))
            if lawyer_ids:
                connection.execute("DELETE FROM lawyer WHERE id = ANY(%s)", (lawyer_ids,))

    def test_registration_is_idempotent_transactional_and_audited(self) -> None:
        now = datetime.now(UTC)
        lawyer = self.service.register_lawyer(
            reference_code=self.lawyer_code,
            display_name="Advogado Fictício",
            actor_id="integration-admin",
            now=now,
        )
        self.entity_ids.add(lawyer.id)
        repeated_lawyer = self.service.register_lawyer(
            reference_code=self.lawyer_code,
            display_name="Advogado Fictício",
            actor_id="integration-admin",
            now=now,
        )
        self.assertTrue(lawyer.created)
        self.assertFalse(repeated_lawyer.created)
        self.assertEqual(lawyer.id, repeated_lawyer.id)

        process = self.service.register_process(
            cnj_value=str(self.cnj),
            lawyer_reference=self.lawyer_code,
            actor_id="integration-admin",
            now=now,
        )
        self.entity_ids.add(process.id)
        repeated_process = self.service.register_process(
            cnj_value=str(self.cnj),
            lawyer_reference=self.lawyer_code,
            actor_id="integration-admin",
            now=now,
        )
        self.assertTrue(process.created)
        self.assertFalse(repeated_process.created)
        self.assertEqual(process.monitor_status, MonitorStatus.PENDING_INITIAL_CHECK)
        self.assertEqual(process.id, repeated_process.id)
        self.assertNotIn(self.cnj.digits[:7], process.as_dict()["process"])

        with psycopg.connect(DATABASE_URL) as connection:
            state = connection.execute(
                "SELECT status FROM monitor_state WHERE process_id = %s", (process.id,)
            ).fetchone()
            jobs = connection.execute(
                "SELECT count(*) FROM job WHERE process_id = %s AND type = 'MONITOR_PROCESS'",
                (process.id,),
            ).fetchone()
            audits = connection.execute(
                "SELECT action FROM audit_event WHERE entity_id = %s ORDER BY at", (process.id,)
            ).fetchall()
        self.assertEqual(state[0], MonitorStatus.PENDING_INITIAL_CHECK.value)
        self.assertEqual(jobs[0], 1)
        self.assertEqual(audits, [("PROCESS_REGISTERED",)])

        listed = self.service.list_processes()
        self.assertIn(process.id, {item.id for item in listed})

    def test_reassignment_requires_explicit_operation_and_deactivation_preserves_history(
        self,
    ) -> None:
        now = datetime.now(UTC)
        first = self.service.register_lawyer(
            reference_code=self.lawyer_code,
            display_name="Responsável Fictício",
            actor_id="integration-admin",
            now=now,
        )
        second = self.service.register_lawyer(
            reference_code=self.other_lawyer_code,
            display_name="Substituto Fictício",
            actor_id="integration-admin",
            now=now,
        )
        self.entity_ids.update((first.id, second.id))
        process = self.service.register_process(
            cnj_value=str(self.cnj),
            lawyer_reference=self.lawyer_code,
            actor_id="integration-admin",
            now=now,
        )
        self.entity_ids.add(process.id)

        with self.assertRaisesRegex(ProcessConflictError, "reatribuição"):
            self.service.register_process(
                cnj_value=str(self.cnj),
                lawyer_reference=self.other_lawyer_code,
                actor_id="integration-admin",
                now=now,
            )

        deactivated = self.service.deactivate_process(
            cnj_value=str(self.cnj), actor_id="integration-admin", now=now
        )
        repeated = self.service.deactivate_process(
            cnj_value=str(self.cnj), actor_id="integration-admin", now=now
        )
        self.assertTrue(deactivated.changed)
        self.assertFalse(repeated.changed)

        inactive = self.service.list_processes(include_inactive=True)
        record = next(item for item in inactive if item.id == process.id)
        self.assertFalse(record.active)
        self.assertEqual(record.monitor_status, MonitorStatus.DISABLED)
        with psycopg.connect(DATABASE_URL) as connection:
            job_status = connection.execute(
                "SELECT status FROM job WHERE process_id = %s", (process.id,)
            ).fetchone()
            action = connection.execute(
                """
                SELECT action FROM audit_event
                WHERE entity_id = %s AND action = 'PROCESS_DEACTIVATED'
                """,
                (process.id,),
            ).fetchone()
        self.assertEqual(job_status[0], "PAUSED")
        self.assertEqual(action[0], "PROCESS_DEACTIVATED")


if __name__ == "__main__":
    unittest.main()
