from __future__ import annotations

import contextlib
import tempfile
import types
import unittest
import uuid
import zlib
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest import mock

from legal_monitor.connectors.errors import ConnectorError
from legal_monitor.connectors.pje import TimelineItem, items_from_payload
from legal_monitor.connectors.routing import CATALOG
from legal_monitor.documents.service import DocumentService
from legal_monitor.domain.cnj import CnjNumber
from legal_monitor.domain.enums import ErrorCode
from legal_monitor.monitoring.monitor import (
    MAX_DISCOVERY_SHORT_SESSION,
    MonitorService,
    ProcessOutcome,
    limit_discovery,
    movement_from_item,
    next_candidate,
)
from legal_monitor.monitoring.monitor_repository import MonitoredProcess
from legal_monitor.notifications.base import NotificationMessage, NotificationReceipt
from tests.helpers import blank_pdf_bytes

CNJ = CnjNumber.from_components(sequence=1, year=2025, justice=8, tribunal=19, origin=209)


class FakeRepo:
    def __init__(self) -> None:
        self.movements: dict[str, uuid.UUID] = {}
        self.documents: list[str] = []
        self.sources: list[str] = []
        self.checked: list[str] = []
        self.lookups_recorded: list[tuple[str, str]] = []

    def known_fingerprints(self, process_id: uuid.UUID, source: str) -> set[str]:
        return set(self.movements)

    def record_source(self, process_id, *, system, source_key, at) -> None:
        self.sources.append(source_key)

    def insert_movement(self, process_id, movement, correlation_id):
        if movement.fingerprint in self.movements:
            return None
        self.movements[movement.fingerprint] = uuid.uuid4()
        return self.movements[movement.fingerprint]

    def insert_document(self, movement_id, source_ref, record) -> None:
        self.documents.append(source_ref)

    def mark_checked(self, process_id, *, status, at, success) -> None:
        self.checked.append(status)

    def record_lookup(self, process_id, source_key, *, result, detail, at) -> None:
        self.lookups_recorded.append((source_key, result))

    def lookups(self) -> dict:
        return {}


class FakeConnector:
    def __init__(self, items: tuple[TimelineItem, ...]) -> None:
        self.items = items
        self.downloads: list[str] = []

    def read_timeline(self, autos):
        return self.items

    def download_document(self, context, autos, document, target: Path) -> Path:
        self.downloads.append(document.tag)
        target.write_bytes(blank_pdf_bytes())
        return target


class RecordingNotifier:
    def __init__(self) -> None:
        self.sent: list[NotificationMessage] = []

    def send(self, message: NotificationMessage) -> NotificationReceipt:
        self.sent.append(message)
        return NotificationReceipt("TEST", None, True)


def timeline(*texts: str) -> tuple[TimelineItem, ...]:
    """Como no PJe real, data e ID do documento pertencem à movimentação (estáveis entre
    rodadas); só a posição na tela (tag) muda quando algo novo entra no topo."""
    items = []
    for i, text in enumerate(texts):
        stable = zlib.crc32(text.encode("utf-8"))
        items.append(
            {
                "date": f"{1 + stable % 28} set. 2026",
                "text": text,
                "docs": [
                    {"tag": f"{i}-0", "label": "Doc", "hint": f"idProcessoDocumento={stable}"}
                ],
            }
        )
    return items_from_payload({"items": items})


class MonitorServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        self.repo = FakeRepo()
        self.notifier = RecordingNotifier()
        self.service = MonitorService(
            repository=self.repo,  # type: ignore[arg-type]
            sessions=None,  # type: ignore[arg-type]
            documents=DocumentService(root / "docs"),
            lawyer_notifier=self.notifier,
            on_auth_problem=lambda endpoint, state: None,
            on_waiting_approval=lambda endpoint: None,
            diagnostics_dir=root / "diag",
            max_attachment_bytes=20_000_000,
            notify_initial=True,
        )
        self.process = MonitoredProcess(uuid.uuid4(), CNJ, "TJRJ", None)
        self.endpoint = CATALOG["pje-tjrj-1g"]

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _run(self, items: tuple[TimelineItem, ...]) -> tuple[ProcessOutcome, FakeConnector]:
        connector = FakeConnector(items)
        outcome = ProcessOutcome(process=CNJ.masked())
        self.service._process_autos(None, connector, None, self.endpoint, self.process, outcome)  # type: ignore[arg-type]
        return outcome, connector

    def test_first_run_records_history_but_notifies_only_latest(self) -> None:
        outcome, connector = self._run(timeline("Decisão C", "Despacho B", "Petição A"))
        self.assertTrue(outcome.first_run)
        self.assertEqual(len(self.repo.movements), 3)
        self.assertEqual(connector.downloads, ["0-0"])
        self.assertEqual(len(self.notifier.sent), 1)
        self.assertIn("Acompanhamento iniciado", self.notifier.sent[0].title)
        self.assertEqual(self.repo.checked, ["ACTIVE_HEALTHY"])

    def test_default_first_run_is_silent_and_summarized_once(self) -> None:
        self.service._notify_initial = False
        self.service._baseline = []
        for text in ("Decisão A", "Despacho B"):
            self.process = MonitoredProcess(uuid.uuid4(), CNJ, "TJRJ", None)
            self.repo.movements.clear()
            _, connector = self._run(timeline(text))
            self.assertEqual(connector.downloads, [])
        self.assertEqual(self.notifier.sent, [])
        self.assertEqual(self.service._send_baseline_summary(), 1)
        summary = self.notifier.sent[0]
        self.assertIn("Acompanhamento iniciado (2 processos)", summary.title)
        self.assertIn("Decisão A", summary.body)
        self.assertEqual(summary.attachments, ())

    def test_second_run_without_changes_sends_nothing(self) -> None:
        items = timeline("Decisão C", "Despacho B")
        self._run(items)
        outcome, connector = self._run(items)
        self.assertEqual(outcome.new_movements, 0)
        self.assertEqual(connector.downloads, [])
        self.assertEqual(len(self.notifier.sent), 1)

    def test_new_movement_is_downloaded_and_emailed(self) -> None:
        self._run(timeline("Decisão C", "Despacho B"))
        outcome, connector = self._run(timeline("Sentença D", "Decisão C", "Despacho B"))
        self.assertFalse(outcome.first_run)
        self.assertEqual(outcome.new_movements, 1)
        self.assertEqual(connector.downloads, ["0-0"])
        self.assertIn("Movimentação", self.notifier.sent[-1].title)
        self.assertEqual(len(self.notifier.sent[-1].attachments), 1)

    def test_restricted_process_email_has_no_text_or_attachment(self) -> None:
        self.process = MonitoredProcess(uuid.uuid4(), CNJ, "TJRJ", None, "RESTRICTED")
        self._run(timeline("Decisão sigilosa X"))
        message = self.notifier.sent[0]
        self.assertEqual(message.attachments, ())
        self.assertNotIn("sigilosa", message.body)
        self.assertIn("processo restrito", message.body)

    def test_intimation_documents_are_never_downloaded(self) -> None:
        _, connector = self._run(timeline("Intimação Eletrônica - Expedida"))
        self.assertEqual(connector.downloads, [])
        self.assertEqual(len(self.notifier.sent), 1)  # o aviso sai mesmo assim

    def test_unexpected_error_in_one_process_does_not_stop_the_others(self) -> None:
        processes = [MonitoredProcess(uuid.uuid4(), CNJ, "TJRJ", None) for _ in range(3)]
        outcomes = {p.id: ProcessOutcome(process=CNJ.masked()) for p in processes}
        errors = [
            ConnectorError(ErrorCode.SOURCE_UNAVAILABLE, "não encontrado"),
            TimeoutError("Timeout 30000ms exceeded while filling 1234567-89.2025.8.19.0209"),
            ConnectorError(ErrorCode.SOURCE_UNAVAILABLE, "não encontrado"),
        ]

        class RaisingConnector:
            def open_autos(self, context, cnj):
                raise errors.pop(0)

        class FakeSessions:
            def headless_for(self, endpoint) -> bool:
                return True

            @contextlib.contextmanager
            def context(self, endpoint, headless=None):
                yield types.SimpleNamespace(pages=[])

        self.service._sessions = FakeSessions()
        with mock.patch(
            "legal_monitor.monitoring.monitor.connector_for", return_value=RaisingConnector()
        ):
            found = self.service._run_group(self.endpoint, processes, outcomes)
        self.assertEqual(found, set())
        self.assertEqual(
            [outcomes[p.id].status for p in processes], ["NOT_FOUND", "ERROR", "NOT_FOUND"]
        )
        # Número do processo nunca vai para o detalhe gravado em log/banco.
        self.assertNotIn("1234567", outcomes[processes[1].id].detail)
        self.assertEqual(
            self.repo.lookups_recorded,
            [
                ("pje-tjrj-1g", "NOT_FOUND"),
                ("pje-tjrj-1g", "ERROR"),
                ("pje-tjrj-1g", "NOT_FOUND"),
            ],
        )

    def test_discovery_moves_to_next_site_after_not_found(self) -> None:
        now = datetime(2026, 9, 28, 20, tzinfo=UTC)
        legacy = MonitoredProcess(uuid.uuid4(), CNJ, "TJRJ", None)
        self.assertEqual(next_candidate(legacy, {}, now), "eproc-tjrj-1g")
        lookups = {(legacy.id, "eproc-tjrj-1g"): ("NOT_FOUND", now - timedelta(hours=1))}
        self.assertEqual(next_candidate(legacy, lookups, now), "pje-tjrj-1g")
        # Depois de 24 h volta a procurar no primeiro site (processos migram de sistema).
        stale = {(legacy.id, "eproc-tjrj-1g"): ("NOT_FOUND", now - timedelta(hours=25))}
        self.assertEqual(next_candidate(legacy, stale, now), "eproc-tjrj-1g")

    def test_short_session_site_limits_discovery_but_keeps_known_processes(self) -> None:
        pje_numbered = CnjNumber.from_components(
            sequence=876_543, year=2025, justice=8, tribunal=19, origin=209
        )
        known = MonitoredProcess(uuid.uuid4(), pje_numbered, "TJRJ", "pje-tjrj-1g")
        legacy = [MonitoredProcess(uuid.uuid4(), CNJ, "TJRJ", None) for _ in range(20)]
        new_pje = MonitoredProcess(uuid.uuid4(), pje_numbered, "TJRJ", None)
        group = limit_discovery([known, *legacy, new_pje], "pje-tjrj-1g")
        self.assertEqual(group[0], known)  # já encontrado: sempre verificado
        self.assertEqual(group[1], new_pje)  # numeração PJe tem prioridade na descoberta
        self.assertEqual(len(group), 1 + MAX_DISCOVERY_SHORT_SESSION)

    def test_fingerprint_is_stable_across_runs(self) -> None:
        item = timeline("Decisão C")[0]
        first = movement_from_item(item, observed_at=datetime(2026, 9, 28, tzinfo=UTC))
        second = movement_from_item(item, observed_at=datetime(2026, 9, 29, tzinfo=UTC))
        self.assertEqual(first.fingerprint, second.fingerprint)


if __name__ == "__main__":
    unittest.main()
