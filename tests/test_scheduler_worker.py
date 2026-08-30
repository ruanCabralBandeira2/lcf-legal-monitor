from __future__ import annotations

import unittest
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from legal_monitor.domain.enums import ErrorCode, JobStatus
from legal_monitor.scheduler.models import JobLease
from legal_monitor.scheduler.policy import RetryPolicy
from legal_monitor.scheduler.repository import LostLeaseError
from legal_monitor.scheduler.worker import JobExecutionError, SchedulerWorker


class MemoryRepository:
    def __init__(self, leases: tuple[JobLease, ...]) -> None:
        self.leases = leases
        self.completed: list[JobLease] = []
        self.failures: list[tuple[JobLease, ErrorCode, datetime | None, bool]] = []
        self.heartbeats: list[dict[str, object]] = []

    def record_heartbeat(
        self,
        *,
        worker_id: str,
        seen_at: datetime,
        healthy: bool,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        self.heartbeats.append(
            {
                "worker_id": worker_id,
                "seen_at": seen_at,
                "healthy": healthy,
                "details": details,
            }
        )

    def claim_due(
        self,
        *,
        worker_id: str,
        now: datetime,
        lease_seconds: int,
        limit: int,
    ) -> tuple[JobLease, ...]:
        del worker_id, now, lease_seconds, limit
        return self.leases

    def complete(self, lease: JobLease, *, completed_at: datetime) -> None:
        del completed_at
        self.completed.append(lease)

    def fail(
        self,
        lease: JobLease,
        *,
        failed_at: datetime,
        error_code: ErrorCode,
        retry_at: datetime | None,
        blocked: bool,
    ) -> JobStatus:
        del failed_at
        self.failures.append((lease, error_code, retry_at, blocked))
        if blocked:
            return JobStatus.PAUSED
        return JobStatus.PENDING if retry_at else JobStatus.FAILED


class SchedulerWorkerTests(unittest.TestCase):
    def setUp(self) -> None:
        now = datetime.now(UTC)
        self.lease = JobLease(
            id=UUID("00000000-0000-0000-0000-000000000001"),
            attempt_id=UUID("00000000-0000-0000-0000-000000000002"),
            job_type="TEST",
            process_id=None,
            due_at=now,
            lease_until=now + timedelta(minutes=5),
            attempt=1,
            max_attempts=4,
            correlation_id=UUID("00000000-0000-0000-0000-000000000003"),
            lease_owner="test-worker",
        )
        self.policy = RetryPolicy(base_seconds=1, maximum_seconds=60, jitter_ratio=0)

    def _worker(
        self, repository: MemoryRepository, handler: Callable[[JobLease], None]
    ) -> SchedulerWorker:
        return SchedulerWorker(
            repository=repository,
            worker_id="test-worker",
            handlers={"TEST": handler},
            retry_policy=self.policy,
            lease_seconds=300,
            batch_size=10,
        )

    def test_success_completes_job_and_updates_heartbeat(self) -> None:
        repository = MemoryRepository((self.lease,))
        summary = self._worker(repository, lambda lease: None).run_once()
        self.assertEqual(summary.succeeded, 1)
        self.assertEqual(repository.completed, [self.lease])
        self.assertEqual(len(repository.heartbeats), 2)

    def test_retryable_failure_reschedules_job(self) -> None:
        repository = MemoryRepository((self.lease,))

        def fail(lease: JobLease) -> None:
            del lease
            raise JobExecutionError(ErrorCode.TIMEOUT)

        summary = self._worker(repository, fail).run_once()
        self.assertEqual(summary.retried, 1)
        self.assertIsNotNone(repository.failures[0][2])
        self.assertFalse(repository.failures[0][3])

    def test_missing_handler_pauses_job(self) -> None:
        repository = MemoryRepository((self.lease,))
        worker = SchedulerWorker(
            repository=repository,
            worker_id="test-worker",
            handlers={},
            retry_policy=self.policy,
            lease_seconds=300,
            batch_size=10,
        )
        summary = worker.run_once()
        self.assertEqual(summary.blocked, 1)
        self.assertEqual(repository.failures[0][1], ErrorCode.WORKER_MISCONFIGURED)

    def test_lost_lease_is_visible_and_does_not_abort_batch(self) -> None:
        class LostLeaseRepository(MemoryRepository):
            def complete(self, lease: JobLease, *, completed_at: datetime) -> None:
                del lease, completed_at
                raise LostLeaseError("expirado")

        repository = LostLeaseRepository((self.lease,))
        summary = self._worker(repository, lambda lease: None).run_once()
        self.assertEqual(summary.failed, 1)
        self.assertEqual(len(repository.heartbeats), 2)


if __name__ == "__main__":
    unittest.main()
