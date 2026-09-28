"""Rodada de monitoramento (ADR-009): login por fonte, leitura, dedupe, download e e-mail."""

from __future__ import annotations

import contextlib
import logging
import tempfile
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from legal_monitor.browser.session import BrowserSessionManager
from legal_monitor.connectors.errors import AuthenticationRequired, ConnectorError
from legal_monitor.connectors.pje import PjeConnector, TimelineItem
from legal_monitor.connectors.routing import CATALOG, SourceEndpoint, candidate_sources
from legal_monitor.documents.service import DocumentService, DocumentValidationError
from legal_monitor.domain.enums import ErrorCode, SessionState, SourceSystem
from legal_monitor.domain.models import DocumentRecord, Movement, ProcessRef
from legal_monitor.monitoring.latest import build_movement_message
from legal_monitor.monitoring.monitor_repository import MonitoredProcess, PostgresMonitorRepository
from legal_monitor.notifications.base import Notifier

LOGGER = logging.getLogger(__name__)
MAX_DOCUMENTS_PER_MOVEMENT = 5


def movement_from_item(item: TimelineItem, *, observed_at: datetime) -> Movement:
    first_doc = next((doc.document_id for doc in item.documents if doc.document_id), None)
    return Movement(
        source=SourceSystem.PJE,
        source_event_id=None,
        event_at=item.event_date,
        observed_at=observed_at,
        type_raw=item.text[:500],
        type_normalized="pje-timeline",
        description=item.text,
        document_ref=first_doc,
    )


@dataclass
class ProcessOutcome:
    process: str
    source: str | None = None
    status: str = "PENDING"
    new_movements: int = 0
    documents: int = 0
    emails: int = 0
    first_run: bool = False
    detail: str = ""

    def as_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


@dataclass
class RunSummary:
    started_at: datetime
    processes: list[ProcessOutcome] = field(default_factory=list)
    sessions: dict[str, str] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "started_at": self.started_at.isoformat(),
            "sessions": self.sessions,
            "processes": [item.as_dict() for item in self.processes],
            "new_movements": sum(item.new_movements for item in self.processes),
            "emails": sum(item.emails for item in self.processes),
        }


class MonitorService:
    def __init__(
        self,
        *,
        repository: PostgresMonitorRepository,
        sessions: BrowserSessionManager,
        documents: DocumentService,
        lawyer_notifier: Notifier | None,
        on_auth_problem: Callable[[SourceEndpoint, SessionState], None],
        on_waiting_approval: Callable[[SourceEndpoint], None],
        diagnostics_dir: Path,
        max_attachment_bytes: int,
    ) -> None:
        self._repo = repository
        self._sessions = sessions
        self._documents = documents
        self._notifier = lawyer_notifier
        self._on_auth_problem = on_auth_problem
        self._on_waiting = on_waiting_approval
        self._diagnostics = diagnostics_dir
        self._max_attachment = max_attachment_bytes

    def run(self) -> RunSummary:
        summary = RunSummary(started_at=datetime.now(UTC))
        pending = {p.id: p for p in self._repo.active_processes()}
        outcomes = {pid: ProcessOutcome(process=p.cnj.masked()) for pid, p in pending.items()}
        summary.processes = list(outcomes.values())
        # Ordem de fontes: as já conhecidas primeiro; depois descoberta pelo catálogo.
        order: list[str] = []
        for process in pending.values():
            keys = [process.source_key] if process.source_key else []
            keys += [e.key for e in candidate_sources(process.cnj)]
            for key in keys:
                if key and key not in order:
                    order.append(key)
        for key in order:
            endpoint = CATALOG[key]
            group = [
                p
                for p in pending.values()
                if key == p.source_key
                or (p.source_key is None and endpoint in candidate_sources(p.cnj))
            ]
            if not group:
                continue
            if endpoint.system is not SourceSystem.PJE:
                for p in group:
                    outcomes[p.id].detail = f"{key}: conector ainda não implementado"
                continue
            state = self._ensure_session(endpoint)
            summary.sessions[key] = state.value
            if state is not SessionState.VALID:
                self._on_auth_problem(endpoint, state)
                for p in group:
                    outcomes[p.id].status = state.value
                    with contextlib.suppress(Exception):
                        self._repo.mark_checked(
                            p.id, status=state.value, at=datetime.now(UTC), success=False
                        )
                continue
            found = self._run_group(endpoint, group, outcomes)
            for pid in found:
                pending.pop(pid, None)
        return summary

    def _ensure_session(self, endpoint: SourceEndpoint) -> SessionState:
        state = self._sessions.check(endpoint).state
        if state is SessionState.VALID:
            return state
        LOGGER.info("Sessão %s inválida (%s); iniciando login por certificado", endpoint.key, state)
        return self._sessions.login(
            endpoint,
            click_certificate=True,
            on_waiting_approval=lambda: self._on_waiting(endpoint),
        ).state

    def _run_group(
        self,
        endpoint: SourceEndpoint,
        group: list[MonitoredProcess],
        outcomes: dict[uuid.UUID, ProcessOutcome],
    ) -> set[uuid.UUID]:
        connector = PjeConnector(endpoint)
        found: set[uuid.UUID] = set()
        with self._sessions.context(
            endpoint, headless=self._sessions.headless_for(endpoint)
        ) as context:
            for process in group:
                outcome = outcomes[process.id]
                try:
                    autos = connector.open_autos(context, process.cnj)
                except AuthenticationRequired:
                    outcome.status = "AUTH_REQUIRED"
                    outcome.detail = "sessão expirou durante a rodada"
                    self._on_auth_problem(endpoint, SessionState.AUTH_REQUIRED)
                    break
                except ConnectorError as exc:
                    if exc.code is ErrorCode.SOURCE_UNAVAILABLE:
                        outcome.detail = f"{endpoint.key}: não encontrado"
                    else:
                        outcome.status = exc.code.value
                        outcome.detail = f"{endpoint.key}: {exc}"
                    continue
                try:
                    self._process_autos(context, connector, autos, endpoint, process, outcome)
                    found.add(process.id)
                except ConnectorError as exc:
                    outcome.status = exc.code.value
                    outcome.detail = f"{endpoint.key}: {exc}"
                    if exc.code is ErrorCode.PARSE_ERROR:
                        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
                        path = self._diagnostics / f"estrutura-{endpoint.key}-{stamp}.json"
                        with contextlib.suppress(Exception):
                            outcome.detail += (
                                f" | diagnóstico: {connector.dump_structure(autos, path)}"
                            )
                finally:
                    with contextlib.suppress(Exception):
                        autos.close()
        return found

    def _process_autos(
        self,
        context: Any,
        connector: PjeConnector,
        autos: Any,
        endpoint: SourceEndpoint,
        process: MonitoredProcess,
        outcome: ProcessOutcome,
    ) -> None:
        now = datetime.now(UTC)
        items = connector.read_timeline(autos)
        self._repo.record_source(
            process.id, system=endpoint.system.value, source_key=endpoint.key, at=now
        )
        outcome.source = endpoint.key
        known = self._repo.known_fingerprints(process.id, SourceSystem.PJE.value)
        outcome.first_run = not known
        pairs = [(item, movement_from_item(item, observed_at=now)) for item in items]
        new = [(item, mv) for item, mv in pairs if mv.fingerprint not in known]
        # Primeira rodada: registra o histórico inteiro, mas só avisa da movimentação mais recente.
        to_notify = {id(pairs[0][0])} if outcome.first_run else {id(item) for item, _ in new}
        for item, movement in reversed(new):  # do mais antigo para o mais recente
            movement_id = self._repo.insert_movement(process.id, movement, uuid.uuid4())
            if movement_id is None:
                continue
            outcome.new_movements += 0 if outcome.first_run else 1
            if id(item) not in to_notify:
                continue
            records = self._download_all(context, connector, autos, endpoint, process, item)
            for source_ref, record in records:
                self._repo.insert_document(movement_id, source_ref, record)
            outcome.documents += len(records)
            if self._notifier is not None:
                first = records[0][1] if records else None
                message = build_movement_message(
                    process.cnj,
                    endpoint,
                    item,
                    first,
                    attached=first is not None and first.bytes <= self._max_attachment,
                    initial=outcome.first_run,
                    extra_documents=max(len(records) - 1, 0),
                )
                self._notifier.send(message)
                outcome.emails += 1
        self._repo.mark_checked(process.id, status="ACTIVE_HEALTHY", at=now, success=True)
        outcome.status = "OK"

    def _download_all(
        self,
        context: Any,
        connector: PjeConnector,
        autos: Any,
        endpoint: SourceEndpoint,
        process: MonitoredProcess,
        item: TimelineItem,
    ) -> list[tuple[str, DocumentRecord]]:
        records: list[tuple[str, DocumentRecord]] = []
        for document in item.documents[:MAX_DOCUMENTS_PER_MOVEMENT]:
            with tempfile.TemporaryDirectory(prefix="lcf-monitor-") as temporary:
                try:
                    path = connector.download_document(
                        context, autos, document, Path(temporary) / "documento.pdf"
                    )
                    record = self._documents.store_pdf(
                        path,
                        process=ProcessRef(
                            process.cnj, tribunal=endpoint.tribunal, current_system=endpoint.system
                        ),
                        movement_type=document.label or "documento",
                        observed_at=item.event_date or datetime.now(UTC),
                    )
                except (ConnectorError, DocumentValidationError) as exc:
                    LOGGER.warning("Documento não obtido: %s", exc)
                    continue
            records.append((document.document_id or document.tag, record))
        return records
