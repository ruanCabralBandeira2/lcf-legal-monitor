from __future__ import annotations

import hashlib
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from legal_monitor.domain.enums import ErrorCode, JobStatus
from legal_monitor.scheduler.models import EnqueuedJob, JobLease, SchedulerHealth


class LostLeaseError(RuntimeError):
    """O job já não pertence ao worker/attempt que tentou finalizá-lo."""


def _require_aware(value: datetime, field: str) -> None:
    if value.tzinfo is None:
        raise ValueError(f"{field} precisa conter fuso horário")


class PostgresSchedulerRepository:
    def __init__(self, database_url: str) -> None:
        self._database_url = database_url.replace("postgresql+psycopg://", "postgresql://", 1)

    def enqueue(
        self,
        *,
        job_type: str,
        due_at: datetime,
        idempotency_scope: str,
        process_id: UUID | None = None,
        max_attempts: int = 4,
        correlation_id: UUID | None = None,
    ) -> EnqueuedJob:
        _require_aware(due_at, "due_at")
        if not job_type.strip():
            raise ValueError("job_type não pode ser vazio")
        if not idempotency_scope.strip():
            raise ValueError("idempotency_scope não pode ser vazio")
        if max_attempts < 1:
            raise ValueError("max_attempts deve ser positivo")

        idempotency_key = hashlib.sha256(
            "\x1f".join((job_type, str(process_id or ""), idempotency_scope)).encode()
        ).hexdigest()
        job_id = uuid4()
        effective_correlation_id = correlation_id or uuid4()
        with psycopg.connect(self._database_url, row_factory=dict_row) as connection:
            row = connection.execute(
                """
                INSERT INTO job (
                    id, type, process_id, due_at, status, correlation_id,
                    idempotency_key, max_attempts
                )
                VALUES (%s, %s, %s, %s, 'PENDING', %s, %s, %s)
                ON CONFLICT (idempotency_key) WHERE idempotency_key IS NOT NULL
                DO NOTHING
                RETURNING id, correlation_id
                """,
                (
                    job_id,
                    job_type.strip(),
                    process_id,
                    due_at,
                    effective_correlation_id,
                    idempotency_key,
                    max_attempts,
                ),
            ).fetchone()
            if row is not None:
                return EnqueuedJob(row["id"], row["correlation_id"], idempotency_key, True)
            existing = connection.execute(
                "SELECT id, correlation_id FROM job WHERE idempotency_key = %s",
                (idempotency_key,),
            ).fetchone()
            if existing is None:
                raise RuntimeError("Job idempotente não foi criado nem localizado")
            return EnqueuedJob(existing["id"], existing["correlation_id"], idempotency_key, False)

    def claim_due(
        self,
        *,
        worker_id: str,
        now: datetime,
        lease_seconds: int,
        limit: int,
    ) -> tuple[JobLease, ...]:
        _require_aware(now, "now")
        if not worker_id.strip():
            raise ValueError("worker_id não pode ser vazio")
        if lease_seconds < 1 or limit < 1:
            raise ValueError("lease_seconds e limit devem ser positivos")

        lease_until = now + timedelta(seconds=lease_seconds)
        claimed: list[JobLease] = []
        with psycopg.connect(self._database_url, row_factory=dict_row) as connection:
            rows = connection.execute(
                """
                SELECT id, type, process_id, due_at, attempt, max_attempts,
                       correlation_id, status
                FROM job
                WHERE (status = 'PENDING' AND due_at <= %s)
                   OR (status IN ('LEASED', 'RUNNING') AND lease_until <= %s)
                ORDER BY due_at, created_at, id
                FOR UPDATE SKIP LOCKED
                LIMIT %s
                """,
                (now, now, limit),
            ).fetchall()
            for row in rows:
                previous_attempt = row["attempt"]
                if row["status"] in (JobStatus.LEASED.value, JobStatus.RUNNING.value):
                    connection.execute(
                        """
                        UPDATE job_attempt
                        SET ended_at = %s, status = 'FAILED', error_code = %s
                        WHERE job_id = %s AND attempt = %s AND status = 'RUNNING'
                        """,
                        (now, ErrorCode.LEASE_EXPIRED.value, row["id"], previous_attempt),
                    )
                if previous_attempt >= row["max_attempts"]:
                    connection.execute(
                        """
                        UPDATE job
                        SET status = 'FAILED', lease_until = NULL, lease_owner = NULL,
                            error_code = %s, updated_at = %s
                        WHERE id = %s
                        """,
                        (ErrorCode.LEASE_EXPIRED.value, now, row["id"]),
                    )
                    continue

                attempt = previous_attempt + 1
                attempt_id = uuid4()
                connection.execute(
                    """
                    UPDATE job
                    SET status = 'RUNNING', lease_until = %s, lease_owner = %s,
                        attempt = %s, error_code = NULL, updated_at = %s
                    WHERE id = %s
                    """,
                    (lease_until, worker_id, attempt, now, row["id"]),
                )
                connection.execute(
                    """
                    INSERT INTO job_attempt (
                        id, job_id, attempt, started_at, status, correlation_id
                    )
                    VALUES (%s, %s, %s, %s, 'RUNNING', %s)
                    """,
                    (attempt_id, row["id"], attempt, now, row["correlation_id"]),
                )
                claimed.append(
                    JobLease(
                        id=row["id"],
                        attempt_id=attempt_id,
                        job_type=row["type"],
                        process_id=row["process_id"],
                        due_at=row["due_at"],
                        lease_until=lease_until,
                        attempt=attempt,
                        max_attempts=row["max_attempts"],
                        correlation_id=row["correlation_id"],
                        lease_owner=worker_id,
                    )
                )
        return tuple(claimed)

    def complete(self, lease: JobLease, *, completed_at: datetime) -> None:
        _require_aware(completed_at, "completed_at")
        with psycopg.connect(self._database_url) as connection:
            cursor = connection.execute(
                """
                UPDATE job
                SET status = 'SUCCEEDED', lease_until = NULL, lease_owner = NULL,
                    error_code = NULL, updated_at = %s
                WHERE id = %s AND status = 'RUNNING' AND attempt = %s
                  AND lease_owner = %s AND lease_until > %s
                """,
                (completed_at, lease.id, lease.attempt, lease.lease_owner, completed_at),
            )
            if cursor.rowcount != 1:
                raise LostLeaseError(f"Lease perdido para o job {lease.id}")
            connection.execute(
                """
                UPDATE job_attempt
                SET ended_at = %s, status = 'SUCCEEDED', error_code = NULL
                WHERE id = %s AND status = 'RUNNING'
                """,
                (completed_at, lease.attempt_id),
            )

    def fail(
        self,
        lease: JobLease,
        *,
        failed_at: datetime,
        error_code: ErrorCode,
        retry_at: datetime | None,
        blocked: bool,
    ) -> JobStatus:
        _require_aware(failed_at, "failed_at")
        if retry_at is not None:
            _require_aware(retry_at, "retry_at")
        status = (
            JobStatus.PAUSED
            if blocked
            else (JobStatus.PENDING if retry_at is not None else JobStatus.FAILED)
        )
        attempt_status = "BLOCKED" if blocked else "FAILED"
        due_at = retry_at or lease.due_at
        with psycopg.connect(self._database_url) as connection:
            cursor = connection.execute(
                """
                UPDATE job
                SET status = %s, due_at = %s, lease_until = NULL, lease_owner = NULL,
                    error_code = %s, updated_at = %s
                WHERE id = %s AND status = 'RUNNING' AND attempt = %s
                  AND lease_owner = %s AND lease_until > %s
                """,
                (
                    status.value,
                    due_at,
                    error_code.value,
                    failed_at,
                    lease.id,
                    lease.attempt,
                    lease.lease_owner,
                    failed_at,
                ),
            )
            if cursor.rowcount != 1:
                raise LostLeaseError(f"Lease perdido para o job {lease.id}")
            connection.execute(
                """
                UPDATE job_attempt
                SET ended_at = %s, status = %s, error_code = %s
                WHERE id = %s AND status = 'RUNNING'
                """,
                (failed_at, attempt_status, error_code.value, lease.attempt_id),
            )
        return status

    def record_heartbeat(
        self,
        *,
        worker_id: str,
        seen_at: datetime,
        healthy: bool,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        _require_aware(seen_at, "seen_at")
        if not worker_id.strip():
            raise ValueError("worker_id não pode ser vazio")
        with psycopg.connect(self._database_url) as connection:
            connection.execute(
                """
                INSERT INTO scheduler_heartbeat (worker_id, last_seen_at, status, details_json)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (worker_id) DO UPDATE
                SET last_seen_at = EXCLUDED.last_seen_at,
                    status = EXCLUDED.status,
                    details_json = EXCLUDED.details_json
                """,
                (
                    worker_id,
                    seen_at,
                    "HEALTHY" if healthy else "DEGRADED",
                    Jsonb(dict(details or {})),
                ),
            )

    def health(self, *, checked_at: datetime, worker_stale_seconds: int) -> SchedulerHealth:
        _require_aware(checked_at, "checked_at")
        with psycopg.connect(self._database_url, row_factory=dict_row) as connection:
            jobs = connection.execute(
                """
                SELECT
                    count(*) FILTER (WHERE status = 'PENDING' AND due_at <= %s) AS jobs_due,
                    count(*) FILTER (WHERE status IN ('LEASED', 'RUNNING')) AS jobs_running,
                    count(*) FILTER (WHERE status = 'FAILED') AS jobs_failed,
                    min(due_at) FILTER (WHERE status = 'PENDING' AND due_at <= %s) AS oldest_due_at
                FROM job
                """,
                (checked_at, checked_at),
            ).fetchone()
            heartbeat = connection.execute(
                """
                SELECT last_seen_at AS last_worker_at, status
                FROM scheduler_heartbeat
                ORDER BY last_seen_at DESC
                LIMIT 1
                """
            ).fetchone()
            processes = connection.execute(
                """
                SELECT
                    count(*) FILTER (
                        WHERE p.active AND s.next_check_at IS NOT NULL AND s.next_check_at < %s
                    ) AS processes_overdue,
                    count(*) FILTER (
                        WHERE p.active AND (s.process_id IS NULL OR s.last_success_at IS NULL)
                    ) AS processes_without_success
                FROM legal_process p
                LEFT JOIN monitor_state s ON s.process_id = p.id
                """,
                (checked_at,),
            ).fetchone()

        oldest_due_at = jobs["oldest_due_at"]
        oldest_age = (
            max(0.0, (checked_at - oldest_due_at).total_seconds())
            if oldest_due_at is not None
            else None
        )
        last_worker_at = heartbeat["last_worker_at"] if heartbeat is not None else None
        worker_healthy = heartbeat is not None and heartbeat["status"] == "HEALTHY"
        worker_stale = (
            last_worker_at is None
            or (checked_at - last_worker_at).total_seconds() > worker_stale_seconds
        )
        return SchedulerHealth(
            checked_at=checked_at,
            database_accessible=True,
            jobs_due=jobs["jobs_due"],
            jobs_running=jobs["jobs_running"],
            jobs_failed=jobs["jobs_failed"],
            oldest_due_age_seconds=oldest_age,
            last_worker_at=last_worker_at,
            worker_healthy=worker_healthy,
            worker_stale=worker_stale,
            processes_overdue=processes["processes_overdue"],
            processes_without_success=processes["processes_without_success"],
        )


def utc_now() -> datetime:
    return datetime.now(UTC)
