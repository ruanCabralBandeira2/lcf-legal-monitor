from __future__ import annotations

import os
import unittest
from datetime import UTC, datetime, timedelta
from uuid import UUID

import psycopg

from legal_monitor.domain.enums import ErrorCode, JobStatus
from legal_monitor.scheduler.repository import LostLeaseError, PostgresSchedulerRepository

DATABASE_URL = os.environ.get("TEST_DATABASE_URL")


@unittest.skipUnless(DATABASE_URL, "TEST_DATABASE_URL não configurada")
class PostgresSchedulerIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repository = PostgresSchedulerRepository(DATABASE_URL or "")
        self.job_ids: set[UUID] = set()
        self.worker_ids: set[str] = set()
        self.now = datetime.now(UTC)

    def tearDown(self) -> None:
        with psycopg.connect(DATABASE_URL) as connection:
            if self.job_ids:
                connection.execute(
                    "DELETE FROM job_attempt WHERE job_id = ANY(%s)",
                    (list(self.job_ids),),
                )
                connection.execute("DELETE FROM job WHERE id = ANY(%s)", (list(self.job_ids),))
            if self.worker_ids:
                connection.execute(
                    "DELETE FROM scheduler_heartbeat WHERE worker_id = ANY(%s)",
                    (list(self.worker_ids),),
                )

    def _enqueue(self, scope: str, *, max_attempts: int = 4):
        job = self.repository.enqueue(
            job_type="SYSTEM_HEALTHCHECK",
            due_at=self.now,
            idempotency_scope=scope,
            max_attempts=max_attempts,
        )
        self.job_ids.add(job.id)
        return job

    def test_enqueue_is_idempotent_and_claim_is_exclusive(self) -> None:
        first = self._enqueue(f"integration-idempotency-{self.now.isoformat()}")
        repeated = self.repository.enqueue(
            job_type="SYSTEM_HEALTHCHECK",
            due_at=self.now,
            idempotency_scope=f"integration-idempotency-{self.now.isoformat()}",
        )
        self.assertTrue(first.created)
        self.assertFalse(repeated.created)
        self.assertEqual(first.id, repeated.id)

        leases = self.repository.claim_due(
            worker_id="integration-a", now=self.now, lease_seconds=60, limit=10
        )
        self.assertEqual(len(leases), 1)
        competing = self.repository.claim_due(
            worker_id="integration-b", now=self.now, lease_seconds=60, limit=10
        )
        self.assertEqual(competing, ())
        self.repository.complete(leases[0], completed_at=self.now + timedelta(seconds=1))

    def test_expired_lease_is_reclaimed_and_old_owner_cannot_complete(self) -> None:
        self._enqueue(f"integration-expired-{self.now.isoformat()}")
        first = self.repository.claim_due(
            worker_id="integration-old", now=self.now, lease_seconds=1, limit=1
        )[0]
        second = self.repository.claim_due(
            worker_id="integration-new",
            now=self.now + timedelta(seconds=2),
            lease_seconds=60,
            limit=1,
        )[0]
        self.assertEqual(second.attempt, 2)
        with self.assertRaises(LostLeaseError):
            self.repository.complete(first, completed_at=self.now + timedelta(seconds=3))
        self.repository.complete(second, completed_at=self.now + timedelta(seconds=3))

    def test_failure_is_rescheduled_and_health_separates_worker_from_processes(self) -> None:
        self._enqueue(f"integration-retry-{self.now.isoformat()}")
        lease = self.repository.claim_due(
            worker_id="integration-retry", now=self.now, lease_seconds=60, limit=1
        )[0]
        status = self.repository.fail(
            lease,
            failed_at=self.now + timedelta(seconds=1),
            error_code=ErrorCode.TIMEOUT,
            retry_at=self.now + timedelta(minutes=1),
            blocked=False,
        )
        self.assertEqual(status, JobStatus.PENDING)

        worker_id = f"integration-health-{self.now.timestamp()}"
        self.worker_ids.add(worker_id)
        self.repository.record_heartbeat(
            worker_id=worker_id,
            seen_at=self.now,
            healthy=True,
            details={"test": True},
        )
        health = self.repository.health(checked_at=self.now, worker_stale_seconds=60)
        self.assertTrue(health.platform_alive)
        self.assertTrue(health.worker_healthy)
        self.assertFalse(health.worker_stale)

        self.repository.record_heartbeat(
            worker_id=worker_id,
            seen_at=self.now + timedelta(seconds=1),
            healthy=False,
            details={"test": True, "reason": "degraded-fixture"},
        )
        degraded = self.repository.health(
            checked_at=self.now + timedelta(seconds=1), worker_stale_seconds=60
        )
        self.assertFalse(degraded.platform_alive)
        self.assertFalse(degraded.worker_healthy)


if __name__ == "__main__":
    unittest.main()
