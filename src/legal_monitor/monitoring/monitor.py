"""Rodada de monitoramento (ADR-009): login por fonte, leitura, dedupe, download e e-mail."""

from __future__ import annotations

import contextlib
import logging
import re
import tempfile
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from legal_monitor.browser.session import BrowserSessionManager
from legal_monitor.connectors.eproc import EprocConnector
from legal_monitor.connectors.errors import AuthenticationRequired, ConnectorError
from legal_monitor.connectors.pje import PjeConnector, TimelineItem
from legal_monitor.connectors.routing import (
    CATALOG,
    SourceEndpoint,
    candidate_keys,
    candidate_sources,
)
from legal_monitor.documents.service import DocumentService, DocumentValidationError
from legal_monitor.domain.enums import ErrorCode, SessionState, SourceSystem
from legal_monitor.domain.models import DocumentRecord, Movement, ProcessRef
from legal_monitor.monitoring.latest import build_movement_message
from legal_monitor.monitoring.monitor_repository import MonitoredProcess, PostgresMonitorRepository
from legal_monitor.notifications.base import NotificationMessage, Notifier

LOGGER = logging.getLogger(__name__)
MAX_DOCUMENTS_PER_MOVEMENT = 5
BASELINE_LINES_PER_EMAIL = 40


def movement_from_item(
    item: TimelineItem, *, observed_at: datetime, system: SourceSystem = SourceSystem.PJE
) -> Movement:
    first_doc = next((doc.document_id for doc in item.documents if doc.document_id), None)
    return Movement(
        source=system,
        source_event_id=item.event_id,
        event_at=item.event_date,
        observed_at=observed_at,
        type_raw=item.text[:500],
        type_normalized=f"{system.value.lower()}-timeline",
        description=item.text,
        document_ref=first_doc,
    )


LOOKUP_RETRY = timedelta(hours=24)
MAX_DISCOVERY_SHORT_SESSION = 8
MAX_INDIVIDUAL_ALERTS = 10
BURST_DOCUMENT_MOVEMENTS = 3
MAX_BURST_LINES = 60
_CNJ_IN_TEXT = re.compile(r"\d{7}-?\d{2}\.?\d{4}\.?\d\.?\d{2}\.?\d{4}|\d{20}")


def safe_detail(exc: BaseException) -> str:
    """Mensagem de erro curta, sem número de processo (vai para log e banco)."""
    text = f"{type(exc).__name__}: {exc}".replace("\n", " ")
    return _CNJ_IN_TEXT.sub("<cnj>", text)[:300]


def recently_not_found(entry: tuple[str, datetime] | None, now: datetime) -> bool:
    return entry is not None and entry[0] == "NOT_FOUND" and now - entry[1] < LOOKUP_RETRY


def next_candidate(
    process: MonitoredProcess,
    lookups: dict[tuple[uuid.UUID, str], tuple[str, datetime]],
    now: datetime,
) -> str | None:
    """Próximo site a procurar: o primeiro provável onde ele ainda não foi dado como ausente."""
    for key in candidate_keys(process.cnj):
        if not recently_not_found(lookups.get((process.id, key)), now):
            return key
    return None


def limit_discovery(group: list[MonitoredProcess], key: str) -> list[MonitoredProcess]:
    """Sessões curtas (PJe, ~15 min): os processos já encontrados neste site sempre entram;
    os ainda sem site entram no máximo MAX_DISCOVERY_SHORT_SESSION por rodada, primeiro os
    que têm este site como mais provável (ex.: numeração PJe)."""
    known = [p for p in group if p.source_key == key]
    unknown = [p for p in group if p.source_key != key]
    unknown.sort(key=lambda p: candidate_keys(p.cnj)[0] != key)
    return known + unknown[:MAX_DISCOVERY_SHORT_SESSION]


def dump_structure(page: Any, target: Path) -> Path:
    return EprocConnector.dump_structure(page, target)


def connector_for(endpoint: SourceEndpoint) -> PjeConnector | EprocConnector | None:
    """Um "robô" por família de sistema; cada site do catálogo usa o seu."""
    if endpoint.system is SourceSystem.PJE:
        return PjeConnector(endpoint)
    if endpoint.system is SourceSystem.EPROC:
        return EprocConnector(endpoint)
    return None


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
    baseline_emails: int = 0

    def as_dict(self) -> dict[str, Any]:
        totals: dict[str, int] = {}
        for item in self.processes:
            totals[item.status] = totals.get(item.status, 0) + 1
        return {
            "started_at": self.started_at.isoformat(),
            "finished_at": datetime.now(UTC).isoformat(),
            "totals": totals,
            "sessions": self.sessions,
            "processes": [item.as_dict() for item in self.processes],
            "new_movements": sum(item.new_movements for item in self.processes),
            "emails": sum(item.emails for item in self.processes) + self.baseline_emails,
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
        notify_initial: bool = False,
        interactive_login: bool = True,
    ) -> None:
        self._interactive_login = interactive_login
        self._repo = repository
        self._sessions = sessions
        self._documents = documents
        self._notifier = lawyer_notifier
        self._on_auth_problem = on_auth_problem
        self._on_waiting = on_waiting_approval
        self._diagnostics = diagnostics_dir
        self._max_attachment = max_attachment_bytes
        # Primeira rodada de cada processo: por padrão registra o histórico em silêncio e
        # envia um único resumo; com notify_initial, um e-mail por processo.
        self._notify_initial = notify_initial
        self._baseline: list[tuple[MonitoredProcess, TimelineItem]] = []

    def run(self, *, site: str | None = None) -> RunSummary:
        """Rodada completa; com `site`, só aquele site (um robô por site, agendas próprias)."""
        summary = RunSummary(started_at=datetime.now(UTC))
        self._baseline = []
        now = summary.started_at
        lookups = self._repo.lookups()

        def should_try(process: MonitoredProcess, key: str) -> bool:
            if site is not None:
                # Robô de um site só procura os processos cujo próximo site provável é ele,
                # para não gastar sessões curtas (PJe) procurando o que está em outro lugar.
                return next_candidate(process, lookups, now) == key
            return key in candidate_keys(process.cnj) and not recently_not_found(
                lookups.get((process.id, key)), now
            )

        pending = {p.id: p for p in self._repo.active_processes()}
        outcomes = {pid: ProcessOutcome(process=p.cnj.masked()) for pid, p in pending.items()}
        touched: set[uuid.UUID] = set()
        # Ordem de fontes: as já conhecidas primeiro; depois descoberta pelo catálogo.
        order: list[str] = []
        for process in pending.values():
            keys = [process.source_key] if process.source_key else []
            keys += [e.key for e in candidate_sources(process.cnj)]
            for key in keys:
                if key and key not in order:
                    order.append(key)
        if site is not None:
            order = [key for key in order if key == site]
        for key in order:
            endpoint = CATALOG[key]
            group = [
                p
                for p in pending.values()
                if key == p.source_key or (p.source_key is None and should_try(p, key))
            ]
            if endpoint.headless_blocked:
                group = limit_discovery(group, key)
            if not group:
                continue
            touched.update(p.id for p in group)
            if connector_for(endpoint) is None:
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
        summary.processes = [outcomes[pid] for pid in outcomes if pid in touched]
        summary.baseline_emails = self._send_baseline_summary()
        return summary

    def _send_baseline_summary(self) -> int:
        """Um e-mail (em partes, se grande) com os processos cujo acompanhamento começou."""
        if self._notifier is None or not self._baseline:
            return 0
        lines = []
        for process, item in self._baseline:
            text = "(restrito)" if process.sensitivity == "RESTRICTED" else item.text[:90]
            lines.append(f"- {process.cnj} | {item.date_text or 's/ data'} | {text}")
        sent = 0
        for start in range(0, len(lines), BASELINE_LINES_PER_EMAIL):
            chunk = lines[start : start + BASELINE_LINES_PER_EMAIL]
            part = start // BASELINE_LINES_PER_EMAIL + 1
            self._notifier.send(
                NotificationMessage(
                    title=f"[LCF Monitor] Acompanhamento iniciado ({len(lines)} processos) - "
                    f"parte {part}",
                    body=(
                        "Histórico registrado; daqui em diante você recebe só as novidades.\n"
                        "Processo | última movimentação | resumo\n\n"
                        + "\n".join(chunk)
                        + "\n\nPrazo não calculado. Confira sempre no sistema do tribunal."
                    ),
                    correlation_id=f"baseline-{datetime.now(UTC):%Y%m%dT%H%M%S}-{part}",
                    demo_only=False,
                    max_length=20_000,
                )
            )
            sent += 1
        return sent

    def _ensure_session(self, endpoint: SourceEndpoint) -> SessionState:
        state = self._sessions.check(endpoint).state
        if state is SessionState.VALID or not self._interactive_login:
            # Sem login interativo (robôs de hora em hora): só avisa; a pessoa roda auth-open.
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
        connector = connector_for(endpoint)
        assert connector is not None  # garantido por run()
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
                    self._lookup(process, endpoint, "AUTH_REQUIRED", outcome.detail)
                    self._on_auth_problem(endpoint, SessionState.AUTH_REQUIRED)
                    break
                except ConnectorError as exc:
                    if exc.code is ErrorCode.SOURCE_UNAVAILABLE:
                        outcome.status = "NOT_FOUND"
                        outcome.detail = f"{endpoint.key}: não encontrado"
                        self._lookup(process, endpoint, "NOT_FOUND", None)
                    else:
                        page = context.pages[-1] if context.pages else None
                        self._fail(process, endpoint, outcome, exc.code.value, str(exc), page)
                    continue
                except Exception as exc:
                    # Erro inesperado (navegador, site lento, mudança de tela): registra e segue.
                    page = context.pages[-1] if context.pages else None
                    self._fail(process, endpoint, outcome, "ERROR", safe_detail(exc), page)
                    continue
                try:
                    self._process_autos(context, connector, autos, endpoint, process, outcome)
                    found.add(process.id)
                    self._lookup(process, endpoint, "FOUND", None)
                except ConnectorError as exc:
                    self._fail(process, endpoint, outcome, exc.code.value, str(exc), autos)
                except Exception as exc:
                    self._fail(process, endpoint, outcome, "ERROR", safe_detail(exc), autos)
                finally:
                    with contextlib.suppress(Exception):
                        autos.close()
        return found

    def _lookup(
        self, process: MonitoredProcess, endpoint: SourceEndpoint, result: str, detail: str | None
    ) -> None:
        try:
            self._repo.record_lookup(
                process.id, endpoint.key, result=result, detail=detail, at=datetime.now(UTC)
            )
        except Exception:
            LOGGER.exception("Falha ao registrar a procura do processo no site")

    def _fail(
        self,
        process: MonitoredProcess,
        endpoint: SourceEndpoint,
        outcome: ProcessOutcome,
        status: str,
        detail: str,
        page: Any,
    ) -> None:
        outcome.status = status
        outcome.detail = f"{endpoint.key}: {detail}"
        if page is not None:
            stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
            path = self._diagnostics / f"estrutura-{endpoint.key}-{stamp}.json"
            with contextlib.suppress(Exception):
                outcome.detail += f" | diagnóstico: {dump_structure(page, path)}"
        self._lookup(process, endpoint, "ERROR", outcome.detail[:500])

    def _process_autos(
        self,
        context: Any,
        connector: PjeConnector | EprocConnector,
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
        system = endpoint.system
        known = self._repo.known_fingerprints(process.id, system.value)
        outcome.first_run = not known
        pairs = [(item, movement_from_item(item, observed_at=now, system=system)) for item in items]
        new = [(item, mv) for item, mv in pairs if mv.fingerprint not in known]
        # Primeira rodada: registra o histórico inteiro; avisa só da mais recente (um e-mail
        # por processo com notify_initial) ou entra no resumo único da rodada.
        if outcome.first_run and not self._notify_initial:
            to_notify: set[int] = set()
            self._baseline.append((process, pairs[0][0]))
            outcome.detail = "histórico registrado (resumo único por e-mail)"
        elif outcome.first_run:
            to_notify = {id(pairs[0][0])}
        else:
            to_notify = {id(item) for item, _ in new}
        # Trava contra enxurrada: muitas "novidades" de uma vez indicam mudança no site ou na
        # leitura. Um único e-mail consolidado; documentos só das mais recentes.
        burst = not outcome.first_run and len(new) > MAX_INDIVIDUAL_ALERTS
        if burst:
            to_notify = {id(item) for item, _ in new[:BURST_DOCUMENT_MOVEMENTS]}
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
            if self._notifier is not None and not burst:
                first = records[0][1] if records else None
                restricted = process.sensitivity == "RESTRICTED"
                message = build_movement_message(
                    process.cnj,
                    endpoint,
                    item,
                    first,
                    attached=(
                        not restricted and first is not None and first.bytes <= self._max_attachment
                    ),
                    initial=outcome.first_run,
                    extra_documents=max(len(records) - 1, 0),
                    restricted=restricted,
                )
                self._notifier.send(message)
                outcome.emails += 1
        if burst and self._notifier is not None:
            self._send_burst_summary(process, endpoint, [item for item, _ in new])
            outcome.emails += 1
            outcome.detail = f"{len(new)} movimentações novas de uma vez: e-mail consolidado"
        self._repo.mark_checked(process.id, status="ACTIVE_HEALTHY", at=now, success=True)
        outcome.status = "OK"

    def _send_burst_summary(
        self, process: MonitoredProcess, endpoint: SourceEndpoint, items: list[TimelineItem]
    ) -> None:
        restricted = process.sensitivity == "RESTRICTED"
        lines = [
            f"- {item.date_text or 's/ data'} | {'(restrito)' if restricted else item.text[:110]}"
            for item in items[:MAX_BURST_LINES]
        ]
        if len(items) > MAX_BURST_LINES:
            lines.append(f"- ... e mais {len(items) - MAX_BURST_LINES}")
        assert self._notifier is not None
        self._notifier.send(
            NotificationMessage(
                title=f"[LCF Monitor] {len(items)} movimentações novas: {process.cnj}",
                body=(
                    f"Processo: {process.cnj}\nFonte: {endpoint.notes.split(';')[0]}\n\n"
                    "O robô encontrou várias movimentações novas de uma vez (pode ser uma "
                    "mudança no site ou na leitura). Confira no sistema do tribunal.\n"
                    f"Documentos das {BURST_DOCUMENT_MOVEMENTS} mais recentes foram guardados "
                    "no computador do escritório.\n\n"
                    + "\n".join(lines)
                    + "\n\nPrazo não calculado."
                ),
                correlation_id=f"burst-{process.id}-{datetime.now(UTC):%Y%m%dT%H%M%S}",
                demo_only=False,
                max_length=20_000,
            )
        )

    def _download_all(
        self,
        context: Any,
        connector: PjeConnector | EprocConnector,
        autos: Any,
        endpoint: SourceEndpoint,
        process: MonitoredProcess,
        item: TimelineItem,
    ) -> list[tuple[str, DocumentRecord]]:
        records: list[tuple[str, DocumentRecord]] = []
        if not item.documents_allowed:
            LOGGER.info("Documentos de intimação/citação não são abertos (risco de ciência)")
            return records
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
