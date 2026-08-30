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
from legal_monitor.config import ConfigError, Settings
from legal_monitor.connectors.fake import FakeConnector
from legal_monitor.documents.service import DocumentService
from legal_monitor.domain.cnj import CnjNumber, InvalidCnjNumber
from legal_monitor.domain.enums import SourceSystem
from legal_monitor.domain.models import Movement, ProcessRef


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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="legal-monitor")
    subcommands = parser.add_subparsers(dest="command", required=True)
    subcommands.add_parser("doctor", help="verifica configuração e dependências locais")
    cnj_parser = subcommands.add_parser("validate-cnj", help="valida um número CNJ")
    cnj_parser.add_argument("number")
    subcommands.add_parser("demo", help="executa fatia vertical fictícia sem rede")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "doctor":
        return doctor()
    if args.command == "validate-cnj":
        return validate_cnj(args.number)
    if args.command == "demo":
        return demo()
    return 2


if __name__ == "__main__":
    sys.exit(main())
