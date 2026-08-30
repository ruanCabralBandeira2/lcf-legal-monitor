from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any
from uuid import UUID


@dataclass(frozen=True, slots=True)
class EnqueuedJob:
    id: UUID
    correlation_id: UUID
    idempotency_key: str
    created: bool


@dataclass(frozen=True, slots=True)
class JobLease:
    id: UUID
    attempt_id: UUID
    job_type: str
    process_id: UUID | None
    due_at: datetime
    lease_until: datetime
    attempt: int
    max_attempts: int
    correlation_id: UUID
    lease_owner: str


@dataclass(frozen=True, slots=True)
class SchedulerHealth:
    checked_at: datetime
    database_accessible: bool
    jobs_due: int
    jobs_running: int
    jobs_failed: int
    oldest_due_age_seconds: float | None
    last_worker_at: datetime | None
    worker_healthy: bool
    worker_stale: bool
    processes_overdue: int
    processes_without_success: int

    @property
    def platform_alive(self) -> bool:
        return self.database_accessible and self.worker_healthy and not self.worker_stale

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["checked_at"] = self.checked_at.isoformat()
        payload["last_worker_at"] = self.last_worker_at.isoformat() if self.last_worker_at else None
        payload["platform_alive"] = self.platform_alive
        return payload


@dataclass(frozen=True, slots=True)
class WorkerRunSummary:
    worker_id: str
    claimed: int
    succeeded: int
    retried: int
    blocked: int
    failed: int

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)
