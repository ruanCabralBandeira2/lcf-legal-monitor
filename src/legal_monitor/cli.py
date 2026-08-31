from __future__ import annotations

import argparse
import importlib.util
import json
import platform
import sys
import tempfile
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from typing import Any

from legal_monitor import __version__
from legal_monitor.admin.repository import AdminRepositoryError, PostgresAdminRepository
from legal_monitor.admin.service import AdminService, AdminValidationError
from legal_monitor.config import ConfigError, Settings
from legal_monitor.connectors.fake import FakeConnector
from legal_monitor.documents.service import DocumentService
from legal_monitor.domain.cnj import CnjNumber, InvalidCnjNumber
from legal_monitor.domain.enums import Sensitivity, SourceSystem
from legal_monitor.domain.models import Movement, ProcessRef
from legal_monitor.scheduler.policy import RetryPolicy
from legal_monitor.scheduler.repository import PostgresSchedulerRepository
from legal_monitor.scheduler.worker import SchedulerWorker


def _emit(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))


def doctor() -> int:
    checks: dict[str, Any] = {
        "version": __version__,
        "python": platform.python_version(),
        "architecture": platform.machine(),
        "pypdf": importlib.util.find_spec("pypdf") is not None,
        "psycopg": importlib.util.find_spec("psycopg") is not None,
    }
    try:
        settings = Settings.from_env()
        settings.storage_dir.mkdir(parents=True, exist_ok=True)
        settings.temp_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=settings.temp_dir):
            pass
        checks.update(
            {
                "configuration": "valid",
                "environment": settings.app_env.value,
                "storage_writable": True,
                "real_connectors_enabled": settings.real_connectors_enabled,
                "whatsapp_enabled": settings.whatsapp_enabled,
                "m0_approved": settings.m0_approved,
            }
        )
    except (ConfigError, OSError) as exc:
        checks.update({"configuration": "invalid", "error": str(exc)})
        _emit(checks)
        return 1
    _emit(checks)
    return 0


def validate_cnj(value: str) -> int:
    try:
        cnj = CnjNumber.parse(value)
    except InvalidCnjNumber as exc:
        _emit({"valid": False, "error": str(exc)})
        return 1
    _emit({"valid": True, "formatted": str(cnj), "masked": cnj.masked()})
    return 0


def _example_pdf() -> bytes:
    from pypdf import PdfWriter

    writer = PdfWriter()
    writer.add_blank_page(width=595, height=842)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def demo() -> int:
    settings = Settings.from_env(environ={"APP_ENV": "test"}, load_dotenv=False)
    cnj = CnjNumber.from_components(
        sequence=1,
        year=2026,
        justice=8,
        tribunal=19,
        origin=1,
    )
    process = ProcessRef(cnj=cnj, current_system=SourceSystem.FAKE)
    observed_at = datetime(2026, 8, 30, 18, 0, tzinfo=UTC)
    movement = Movement(
        source=SourceSystem.FAKE,
        source_event_id="fixture-mov-001",
        event_at=observed_at,
        observed_at=observed_at,
        type_raw="Decisão proferida",
        type_normalized="decisao",
        description="Movimentação exclusivamente fictícia para teste.",
        document_ref="fixture://documento-001",
        correlation_id="demo-001",
    )
    connector = FakeConnector(
        movements=(movement,),
        documents={"fixture://documento-001": _example_pdf()},
    )
    with tempfile.TemporaryDirectory(prefix="legal-monitor-demo-") as temporary:
        root = Path(temporary)
        download = connector.fetch_document(
            process,
            "fixture://documento-001",
            root / "download.pdf",
        )
        record = DocumentService(root / "documents").store_pdf(
            download.target_path,
            process=process,
            movement_type=movement.type_normalized,
            observed_at=observed_at,
        )
        _emit(
            {
                "safe_demo": True,
                "network_used": False,
                "process": cnj.masked(),
                "movement_fingerprint": movement.fingerprint,
                "document_sha256": record.sha256,
                "page_count": record.page_count,
                "stored": record.storage_path.exists(),
                "production_storage_untouched": (
                    str(settings.storage_dir) not in str(record.storage_path)
                ),
            }
        )
    return 0


def _scheduler_components() -> tuple[Settings, PostgresSchedulerRepository, RetryPolicy]:
    settings = Settings.from_env()
    repository = PostgresSchedulerRepository(settings.database_url)
    policy = RetryPolicy(
        base_seconds=settings.scheduler_base_backoff_seconds,
        maximum_seconds=settings.scheduler_max_backoff_seconds,
    )
    return settings, repository, policy


def scheduler_heartbeat(worker_id: str) -> int:
    _, repository, _ = _scheduler_components()
    observed_at = datetime.now(UTC)
    try:
        repository.record_heartbeat(
            worker_id=worker_id,
            seen_at=observed_at,
            healthy=True,
            details={"source": "cli"},
        )
    except Exception as exc:
        _emit(
            {
                "heartbeat_recorded": False,
                "error_type": type(exc).__name__,
            }
        )
        return 1
    _emit(
        {
            "heartbeat_recorded": True,
            "worker_id": worker_id,
            "observed_at": observed_at.isoformat(),
        }
    )
    return 0


def scheduler_health() -> int:
    settings, repository, _ = _scheduler_components()
    try:
        health = repository.health(
            checked_at=datetime.now(UTC),
            worker_stale_seconds=settings.worker_stale_seconds,
        )
    except Exception as exc:
        _emit(
            {
                "database_accessible": False,
                "platform_alive": False,
                "error_type": type(exc).__name__,
            }
        )
        return 1
    _emit(health.as_dict())
    return 0 if health.platform_alive else 1


def scheduler_enqueue_healthcheck(idempotency_scope: str) -> int:
    settings, repository, _ = _scheduler_components()
    enqueued = repository.enqueue(
        job_type="SYSTEM_HEALTHCHECK",
        due_at=datetime.now(UTC),
        idempotency_scope=idempotency_scope,
        max_attempts=settings.scheduler_max_attempts,
    )
    _emit(
        {
            "job_id": str(enqueued.id),
            "correlation_id": str(enqueued.correlation_id),
            "created": enqueued.created,
        }
    )
    return 0


def scheduler_run_once(worker_id: str) -> int:
    settings, repository, policy = _scheduler_components()
    worker = SchedulerWorker(
        repository=repository,
        worker_id=worker_id,
        handlers={"SYSTEM_HEALTHCHECK": lambda lease: None},
        retry_policy=policy,
        lease_seconds=settings.scheduler_lease_seconds,
        batch_size=settings.scheduler_batch_size,
    )
    _emit(worker.run_once().as_dict())
    return 0


def _admin_service() -> AdminService:
    settings = Settings.from_env()
    return AdminService(
        PostgresAdminRepository(settings.database_url),
        scheduler_max_attempts=settings.scheduler_max_attempts,
    )


def admin_add_lawyer(code: str, name: str, actor: str) -> int:
    record = _admin_service().register_lawyer(
        reference_code=code,
        display_name=name,
        actor_id=actor,
    )
    _emit({"ok": True, "lawyer": record.as_dict()})
    return 0


def admin_add_process(number: str, lawyer: str, sensitivity: str, actor: str) -> int:
    record = _admin_service().register_process(
        cnj_value=number,
        lawyer_reference=lawyer,
        sensitivity=Sensitivity(sensitivity),
        actor_id=actor,
    )
    _emit({"ok": True, "process": record.as_dict()})
    return 0


def admin_list_processes(include_inactive: bool) -> int:
    records = _admin_service().list_processes(include_inactive=include_inactive)
    _emit(
        {
            "ok": True,
            "count": len(records),
            "processes": [record.as_dict() for record in records],
        }
    )
    return 0


def admin_deactivate_process(number: str, actor: str) -> int:
    result = _admin_service().deactivate_process(
        cnj_value=number,
        actor_id=actor,
    )
    _emit({"ok": True, "result": result.as_dict()})
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="legal-monitor")
    subcommands = parser.add_subparsers(dest="command", required=True)
    subcommands.add_parser("doctor", help="verifica configuração e dependências locais")
    cnj_parser = subcommands.add_parser("validate-cnj", help="valida um número CNJ")
    cnj_parser.add_argument("number")
    subcommands.add_parser("demo", help="executa fatia vertical fictícia sem rede")
    heartbeat_parser = subcommands.add_parser(
        "scheduler-heartbeat", help="registra o sinal interno do worker no PostgreSQL"
    )
    heartbeat_parser.add_argument("--worker-id", default="local-worker")
    subcommands.add_parser(
        "scheduler-health", help="mostra saúde da agenda sem confundir heartbeat e processos"
    )
    enqueue_parser = subcommands.add_parser(
        "scheduler-enqueue-healthcheck",
        help="agenda um job fictício e idempotente para teste local",
    )
    enqueue_parser.add_argument("--key", required=True)
    worker_parser = subcommands.add_parser(
        "scheduler-run-once", help="executa um lote vencido e encerra"
    )
    worker_parser.add_argument("--worker-id", default="local-worker")
    lawyer_parser = subcommands.add_parser(
        "admin-add-lawyer", help="cadastra um responsável local com trilha de auditoria"
    )
    lawyer_parser.add_argument("--code", required=True)
    lawyer_parser.add_argument("--name", required=True)
    lawyer_parser.add_argument("--actor", default="local-admin")
    process_parser = subcommands.add_parser(
        "admin-add-process", help="cadastra processo TJRJ e agenda a primeira verificação"
    )
    process_parser.add_argument("number")
    process_parser.add_argument("--lawyer", required=True)
    process_parser.add_argument(
        "--sensitivity",
        choices=[value.value for value in Sensitivity],
        default=Sensitivity.CONFIDENTIAL.value,
    )
    process_parser.add_argument("--actor", default="local-admin")
    list_parser = subcommands.add_parser(
        "admin-list-processes", help="lista processos com número mascarado e estado explícito"
    )
    list_parser.add_argument("--include-inactive", action="store_true")
    deactivate_parser = subcommands.add_parser(
        "admin-deactivate-process", help="desativa processo, agenda e estado sem apagar histórico"
    )
    deactivate_parser.add_argument("number")
    deactivate_parser.add_argument("--actor", default="local-admin")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "doctor":
            return doctor()
        if args.command == "validate-cnj":
            return validate_cnj(args.number)
        if args.command == "demo":
            return demo()
        if args.command == "scheduler-heartbeat":
            return scheduler_heartbeat(args.worker_id)
        if args.command == "scheduler-health":
            return scheduler_health()
        if args.command == "scheduler-enqueue-healthcheck":
            return scheduler_enqueue_healthcheck(args.key)
        if args.command == "scheduler-run-once":
            return scheduler_run_once(args.worker_id)
        if args.command == "admin-add-lawyer":
            return admin_add_lawyer(args.code, args.name, args.actor)
        if args.command == "admin-add-process":
            return admin_add_process(args.number, args.lawyer, args.sensitivity, args.actor)
        if args.command == "admin-list-processes":
            return admin_list_processes(args.include_inactive)
        if args.command == "admin-deactivate-process":
            return admin_deactivate_process(args.number, args.actor)
    except (AdminRepositoryError, AdminValidationError, InvalidCnjNumber) as exc:
        _emit({"ok": False, "error_type": type(exc).__name__, "error": str(exc)})
        return 1
    return 2


if __name__ == "__main__":
    sys.exit(main())
