from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

from legal_monitor.domain.enums import ErrorCode, JobStatus
from legal_monitor.scheduler.models import JobLease, WorkerRunSummary
from legal_monitor.scheduler.policy import RetryPolicy
from legal_monitor.scheduler.repository import LostLeaseError

LOGGER = logging.getLogger(__name__)
JobHandler = Callable[[JobLease], None]


class SchedulerRepository(Protocol):
    def record_heartbeat(
        self,
        *,
        worker_id: str,
        seen_at: datetime,
        healthy: bool,
        details: Mapping[str, Any] | None = None,
    ) -> None: ...

    def claim_due(
        self,
        *,
        worker_id: str,
        now: datetime,
        lease_seconds: int,
        limit: int,
        job_types: tuple[str, ...],
    ) -> tuple[JobLease, ...]: ...

    def complete(self, lease: JobLease, *, completed_at: datetime) -> None: ...

    def fail(
        self,
        lease: JobLease,
        *,
        failed_at: datetime,
        error_code: ErrorCode,
        retry_at: datetime | None,
        blocked: bool,
    ) -> JobStatus: ...


@dataclass(frozen=True, slots=True)
class JobExecutionError(RuntimeError):
    error_code: ErrorCode
    retry_after_seconds: int | None = None

    def __str__(self) -> str:
        return self.error_code.value


class SchedulerWorker:
    def __init__(
        self,
        *,
        repository: SchedulerRepository,
        worker_id: str,
        handlers: Mapping[str, JobHandler],
        retry_policy: RetryPolicy,
        lease_seconds: int,
        batch_size: int,
    ) -> None:
        self._repository = repository
        self._worker_id = worker_id
        self._handlers = dict(handlers)
        self._retry_policy = retry_policy
        self._lease_seconds = lease_seconds
        self._batch_size = batch_size

    def run_once(self, *, now: datetime | None = None) -> WorkerRunSummary:
        started_at = now or datetime.now(UTC)
        self._repository.record_heartbeat(
            worker_id=self._worker_id,
            seen_at=started_at,
            healthy=True,
            details={"phase": "claiming"},
        )
        leases = self._repository.claim_due(
            worker_id=self._worker_id,
            now=started_at,
            lease_seconds=self._lease_seconds,
            limit=self._batch_size,
            job_types=tuple(self._handlers),
        )
        succeeded = retried = blocked = failed = 0
        for lease in leases:
            handler = self._handlers.get(lease.job_type)
            try:
                if handler is None:
                    raise JobExecutionError(ErrorCode.WORKER_MISCONFIGURED)
                handler(lease)
                self._repository.complete(lease, completed_at=datetime.now(UTC))
                succeeded += 1
            except LostLeaseError:
                LOGGER.warning(
                    "Lease expirou antes da conclusão",
                    extra={
                        "event": "scheduler_lease_lost",
                        "entity_type": "job",
                        "entity_id": str(lease.id),
                        "correlation_id": str(lease.correlation_id),
                        "error_code": ErrorCode.LEASE_EXPIRED.value,
                    },
                )
                failed += 1
            except JobExecutionError as exc:
                outcome = self._handle_failure(lease, exc, datetime.now(UTC))
                if outcome is JobStatus.PENDING:
                    retried += 1
                elif outcome is JobStatus.PAUSED:
                    blocked += 1
                else:
                    failed += 1
            except Exception:
                LOGGER.exception(
                    "Falha inesperada no job",
                    extra={
                        "event": "scheduler_job_failed",
                        "entity_type": "job",
                        "entity_id": str(lease.id),
                        "correlation_id": str(lease.correlation_id),
                        "error_code": ErrorCode.UNEXPECTED_ERROR.value,
                    },
                )
                outcome = self._handle_failure(
                    lease,
                    JobExecutionError(ErrorCode.UNEXPECTED_ERROR),
                    datetime.now(UTC),
                )
                if outcome is JobStatus.PENDING:
                    retried += 1
                else:
                    failed += 1
        finished_at = datetime.now(UTC)
        self._repository.record_heartbeat(
            worker_id=self._worker_id,
            seen_at=finished_at,
            healthy=True,
            details={"phase": "idle", "claimed": len(leases)},
        )
        return WorkerRunSummary(
            worker_id=self._worker_id,
            claimed=len(leases),
            succeeded=succeeded,
            retried=retried,
            blocked=blocked,
            failed=failed,
        )

    def _handle_failure(
        self,
        lease: JobLease,
        failure: JobExecutionError,
        failed_at: datetime,
    ) -> JobStatus:
        blocked = self._retry_policy.is_blocking(failure.error_code)
        retry_at = self._retry_policy.next_retry_at(
            job_id=lease.id,
            attempt=lease.attempt,
            max_attempts=lease.max_attempts,
            error_code=failure.error_code,
            now=failed_at,
            retry_after_seconds=failure.retry_after_seconds,
        )
        try:
            return self._repository.fail(
                lease,
                failed_at=failed_at,
                error_code=failure.error_code,
                retry_at=retry_at,
                blocked=blocked,
            )
        except LostLeaseError:
            LOGGER.warning(
                "Lease expirou antes do registro da falha",
                extra={
                    "event": "scheduler_lease_lost",
                    "entity_type": "job",
                    "entity_id": str(lease.id),
                    "correlation_id": str(lease.correlation_id),
                    "error_code": ErrorCode.LEASE_EXPIRED.value,
                },
            )
            return JobStatus.FAILED
