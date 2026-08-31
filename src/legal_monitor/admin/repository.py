from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from legal_monitor.admin.models import DeactivationResult, LawyerRecord, ProcessRecord
from legal_monitor.domain.cnj import CnjNumber
from legal_monitor.domain.enums import (
    ActorType,
    ErrorCode,
    MonitorStatus,
    Sensitivity,
    SourceSystem,
)
from legal_monitor.scheduler.repository import enqueue_job


class AdminRepositoryError(RuntimeError):
    """Erro de consistência no cadastro administrativo."""


class LawyerNotFoundError(AdminRepositoryError):
    pass


class LawyerConflictError(AdminRepositoryError):
    pass


class ProcessNotFoundError(AdminRepositoryError):
    pass


class ProcessConflictError(AdminRepositoryError):
    pass


def _audit(
    connection: psycopg.Connection[Any],
    *,
    actor_type: ActorType,
    actor_id: str,
    action: str,
    entity_type: str,
    entity_id: UUID,
    occurred_at: datetime,
    correlation_id: UUID,
    metadata: dict[str, Any],
) -> None:
    connection.execute(
        """
        INSERT INTO audit_event (
            id, actor_type, actor_id, action, entity_type, entity_id,
            at, correlation_id, metadata_json
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            uuid4(),
            actor_type.value,
            actor_id,
            action,
            entity_type,
            entity_id,
            occurred_at,
            correlation_id,
            Jsonb(metadata),
        ),
    )


class PostgresAdminRepository:
    def __init__(self, database_url: str) -> None:
        self._database_url = database_url.replace("postgresql+psycopg://", "postgresql://", 1)

    def register_lawyer(
        self,
        *,
        reference_code: str,
        display_name: str,
        actor_id: str,
        occurred_at: datetime,
    ) -> LawyerRecord:
        with psycopg.connect(self._database_url, row_factory=dict_row) as connection:
            existing = connection.execute(
                "SELECT * FROM lawyer WHERE reference_code = %s FOR UPDATE",
                (reference_code,),
            ).fetchone()
            if existing is not None:
                if existing["display_name"] != display_name:
                    raise LawyerConflictError(
                        "Código do responsável já existe com outro nome; use alteração explícita"
                    )
                return self._lawyer_from_row(existing, created=False)

            lawyer_id = uuid4()
            correlation_id = uuid4()
            row = connection.execute(
                """
                INSERT INTO lawyer (
                    id, reference_code, display_name, active, created_at, updated_at
                )
                VALUES (%s, %s, %s, true, %s, %s)
                RETURNING *
                """,
                (lawyer_id, reference_code, display_name, occurred_at, occurred_at),
            ).fetchone()
            _audit(
                connection,
                actor_type=ActorType.ADMIN,
                actor_id=actor_id,
                action="LAWYER_REGISTERED",
                entity_type="lawyer",
                entity_id=lawyer_id,
                occurred_at=occurred_at,
                correlation_id=correlation_id,
                metadata={"reference_code": reference_code},
            )
            return self._lawyer_from_row(row, created=True)

    def register_process(
        self,
        *,
        cnj: CnjNumber,
        lawyer_reference: str,
        sensitivity: Sensitivity,
        actor_id: str,
        occurred_at: datetime,
        first_check_at: datetime,
        max_attempts: int,
    ) -> ProcessRecord:
        with psycopg.connect(self._database_url, row_factory=dict_row) as connection:
            lawyer = connection.execute(
                """
                SELECT id, reference_code
                FROM lawyer
                WHERE reference_code = %s AND active AND deleted_at IS NULL
                FOR UPDATE
                """,
                (lawyer_reference,),
            ).fetchone()
            if lawyer is None:
                raise LawyerNotFoundError("Responsável ativo não encontrado")

            existing = connection.execute(
                """
                SELECT p.*, s.status AS monitor_status, s.last_success_at, s.next_check_at,
                       h.system AS current_system, l.reference_code AS lawyer_reference
                FROM legal_process p
                JOIN lawyer l ON l.id = p.lawyer_id
                LEFT JOIN monitor_state s ON s.process_id = p.id
                LEFT JOIN process_system_history h
                    ON h.process_id = p.id AND h.ended_at IS NULL
                WHERE p.numero_cnj = %s
                ORDER BY p.created_at DESC
                LIMIT 1
                FOR UPDATE OF p
                """,
                (cnj.digits,),
            ).fetchone()
            if existing is not None:
                if existing["deleted_at"] is not None or not existing["active"]:
                    raise ProcessConflictError(
                        "Processo está desativado; reativação explícita é necessária para "
                        "preservar o histórico"
                    )
                if existing["lawyer_id"] != lawyer["id"]:
                    raise ProcessConflictError(
                        "Processo já pertence a outro responsável; reatribuição deve ser explícita"
                    )
                return self._process_from_row(existing, created=False)

            process_id = uuid4()
            correlation_id = uuid4()
            connection.execute(
                """
                INSERT INTO legal_process (
                    id, numero_cnj, tribunal, active, lawyer_id, sensitivity, created_at
                )
                VALUES (%s, %s, 'TJRJ', true, %s, %s, %s)
                """,
                (process_id, cnj.digits, lawyer["id"], sensitivity.value, occurred_at),
            )
            connection.execute(
                """
                INSERT INTO process_system_history (
                    id, process_id, system, detected_at, evidence_ref, confidence
                )
                VALUES (%s, %s, 'UNKNOWN', %s, %s, 0)
                """,
                (uuid4(), process_id, occurred_at, "registration://pending-discovery"),
            )
            connection.execute(
                """
                INSERT INTO monitor_state (
                    process_id, status, next_check_at, consecutive_failures, updated_at
                )
                VALUES (%s, %s, %s, 0, %s)
                """,
                (
                    process_id,
                    MonitorStatus.PENDING_INITIAL_CHECK.value,
                    first_check_at,
                    occurred_at,
                ),
            )
            job = enqueue_job(
                connection,
                job_type="MONITOR_PROCESS",
                due_at=first_check_at,
                idempotency_scope=f"initial:{process_id}",
                process_id=process_id,
                max_attempts=max_attempts,
                correlation_id=correlation_id,
            )
            _audit(
                connection,
                actor_type=ActorType.ADMIN,
                actor_id=actor_id,
                action="PROCESS_REGISTERED",
                entity_type="legal_process",
                entity_id=process_id,
                occurred_at=occurred_at,
                correlation_id=correlation_id,
                metadata={
                    "tribunal": "TJRJ",
                    "system": SourceSystem.UNKNOWN.value,
                    "sensitivity": sensitivity.value,
                    "initial_job_id": str(job.id),
                },
            )
            return ProcessRecord(
                id=process_id,
                cnj=cnj,
                tribunal="TJRJ",
                lawyer_reference=lawyer_reference,
                current_system=SourceSystem.UNKNOWN,
                sensitivity=sensitivity,
                monitor_status=MonitorStatus.PENDING_INITIAL_CHECK,
                last_success_at=None,
                next_check_at=first_check_at,
                active=True,
                created_at=occurred_at,
                initial_job_id=job.id,
                created=True,
            )

    def list_processes(self, *, include_inactive: bool = False) -> tuple[ProcessRecord, ...]:
        with psycopg.connect(self._database_url, row_factory=dict_row) as connection:
            rows = connection.execute(
                """
                SELECT p.*, s.status AS monitor_status, s.last_success_at, s.next_check_at,
                       h.system AS current_system, l.reference_code AS lawyer_reference
                FROM legal_process p
                JOIN lawyer l ON l.id = p.lawyer_id
                LEFT JOIN monitor_state s ON s.process_id = p.id
                LEFT JOIN process_system_history h
                    ON h.process_id = p.id AND h.ended_at IS NULL
                WHERE %s OR (p.active AND p.deleted_at IS NULL)
                ORDER BY p.created_at, p.id
                """,
                (include_inactive,),
            ).fetchall()
        return tuple(self._process_from_row(row, created=False) for row in rows)

    def deactivate_process(
        self,
        *,
        cnj: CnjNumber,
        actor_id: str,
        occurred_at: datetime,
    ) -> DeactivationResult:
        with psycopg.connect(self._database_url, row_factory=dict_row) as connection:
            process = connection.execute(
                """
                SELECT id, active, deleted_at
                FROM legal_process
                WHERE numero_cnj = %s
                ORDER BY created_at DESC
                LIMIT 1
                FOR UPDATE
                """,
                (cnj.digits,),
            ).fetchone()
            if process is None:
                raise ProcessNotFoundError("Processo não encontrado")
            if not process["active"] or process["deleted_at"] is not None:
                return DeactivationResult(process["id"], cnj, False)

            correlation_id = uuid4()
            connection.execute(
                """
                UPDATE job_attempt a
                SET ended_at = %s, status = 'BLOCKED', error_code = %s
                FROM job j
                WHERE a.job_id = j.id AND j.process_id = %s
                  AND a.status = 'RUNNING'
                """,
                (occurred_at, ErrorCode.PROCESS_DISABLED.value, process["id"]),
            )
            connection.execute(
                """
                UPDATE job
                SET status = 'PAUSED', lease_until = NULL, lease_owner = NULL,
                    error_code = %s, updated_at = %s
                WHERE process_id = %s AND status IN ('PENDING', 'LEASED', 'RUNNING')
                """,
                (ErrorCode.PROCESS_DISABLED.value, occurred_at, process["id"]),
            )
            connection.execute(
                """
                UPDATE monitor_state
                SET status = 'DISABLED', next_check_at = NULL, updated_at = %s
                WHERE process_id = %s
                """,
                (occurred_at, process["id"]),
            )
            connection.execute(
                """
                UPDATE process_system_history
                SET ended_at = %s
                WHERE process_id = %s AND ended_at IS NULL
                """,
                (occurred_at, process["id"]),
            )
            connection.execute(
                """
                UPDATE legal_process
                SET active = false, deleted_at = %s
                WHERE id = %s
                """,
                (occurred_at, process["id"]),
            )
            _audit(
                connection,
                actor_type=ActorType.ADMIN,
                actor_id=actor_id,
                action="PROCESS_DEACTIVATED",
                entity_type="legal_process",
                entity_id=process["id"],
                occurred_at=occurred_at,
                correlation_id=correlation_id,
                metadata={"reason": "explicit_admin_action"},
            )
            return DeactivationResult(process["id"], cnj, True)

    @staticmethod
    def _lawyer_from_row(row: dict[str, Any], *, created: bool) -> LawyerRecord:
        return LawyerRecord(
            id=row["id"],
            reference_code=row["reference_code"],
            display_name=row["display_name"],
            active=row["active"],
            created_at=row["created_at"],
            created=created,
        )

    @staticmethod
    def _process_from_row(row: dict[str, Any], *, created: bool) -> ProcessRecord:
        monitor_status = row["monitor_status"] or MonitorStatus.PENDING_INITIAL_CHECK.value
        current_system = row["current_system"] or SourceSystem.UNKNOWN.value
        return ProcessRecord(
            id=row["id"],
            cnj=CnjNumber(row["numero_cnj"]),
            tribunal=row["tribunal"],
            lawyer_reference=row["lawyer_reference"],
            current_system=SourceSystem(current_system),
            sensitivity=Sensitivity(row["sensitivity"]),
            monitor_status=MonitorStatus(monitor_status),
            last_success_at=row["last_success_at"],
            next_check_at=row["next_check_at"],
            active=row["active"],
            created_at=row["created_at"],
            created=created,
        )
