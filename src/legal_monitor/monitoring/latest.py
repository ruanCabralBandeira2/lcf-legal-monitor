from __future__ import annotations

import tempfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from legal_monitor.browser.session import BrowserSessionManager
from legal_monitor.connectors.errors import ConnectorError
from legal_monitor.connectors.pje import PjeConnector, TimelineItem
from legal_monitor.connectors.routing import SourceEndpoint, candidate_sources, get_endpoint
from legal_monitor.documents.service import DocumentService
from legal_monitor.domain.cnj import CnjNumber
from legal_monitor.domain.enums import ErrorCode, SourceSystem
from legal_monitor.domain.models import DocumentRecord, ProcessRef
from legal_monitor.notifications.base import (
    NotificationAttachment,
    NotificationMessage,
    Notifier,
)

MAX_MOVEMENT_TEXT = 900


@dataclass
class LatestResult:
    process: str
    source: str | None = None
    found: bool = False
    movement_date: str | None = None
    movement_text: str | None = None
    document: dict[str, Any] | None = None
    emailed: bool = False
    diagnostics: list[str] = field(default_factory=list)
    tried: list[dict[str, str]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "process": self.process,
            "source": self.source,
            "found": self.found,
            "movement_date": self.movement_date,
            "movement_text": self.movement_text,
            "document": self.document,
            "emailed": self.emailed,
            "diagnostics": self.diagnostics,
            "tried": self.tried,
        }


def build_movement_message(
    cnj: CnjNumber,
    endpoint: SourceEndpoint,
    item: TimelineItem,
    record: DocumentRecord | None,
    *,
    attached: bool,
    initial: bool = False,
    extra_documents: int = 0,
    restricted: bool = False,
    missing_reason: str | None = None,
) -> NotificationMessage:
    text = item.text if len(item.text) <= MAX_MOVEMENT_TEXT else item.text[:MAX_MOVEMENT_TEXT] + "…"
    if restricted:
        # Processo restrito (família, criminal, segredo): o e-mail só avisa; conteúdo e peça
        # ficam no computador do escritório.
        text = "(processo restrito: consulte o texto no sistema ou no computador do escritório)"
        attached = False
    lines = (
        [
            "Acompanhamento iniciado. Esta é a movimentação mais recente; a partir de agora você "
            "recebe apenas as novas.\n"
        ]
        if initial
        else []
    )
    lines += [
        f"Processo: {cnj}",
        f"Fonte: {endpoint.notes.split(';')[0]}",
        f"Data: {item.date_text or 'não identificada'}",
        f"Movimentação: {text}",
    ]
    if record is not None:
        lines += [
            f"Documento: {record.friendly_name} ({record.page_count} pág.)",
            f"SHA-256: {record.sha256}",
            "Anexo: sim" if attached else f"Anexo: não enviado; guardado em {record.storage_path}",
        ]
    else:
        lines.append(
            "Documento: nenhum PDF obtido para esta movimentação"
            + (f" - motivo: {missing_reason}" if missing_reason else "")
        )
    if extra_documents:
        lines.append(
            f"Outros {extra_documents} documento(s) desta movimentação guardados no Mac mini/PC."
        )
    lines.append("\nAtenção: prazo não calculado. Confira sempre no sistema do tribunal.")
    prefix = "Acompanhamento iniciado" if initial else "Movimentação"
    return NotificationMessage(
        title=f"[LCF Monitor] {prefix}: {cnj}",
        body="\n".join(lines),
        correlation_id=f"latest-{cnj.digits}-{record.sha256[:12] if record else 'sem-doc'}",
        demo_only=False,
        attachments=(
            (NotificationAttachment(record.storage_path, record.friendly_name),)
            if record is not None and attached
            else ()
        ),
    )


class LatestMovementService:
    """Busca a última movimentação de um processo, baixa o documento e opcionalmente envia."""

    def __init__(
        self,
        *,
        sessions: BrowserSessionManager,
        documents: DocumentService,
        diagnostics_dir: Path,
        notifier: Notifier | None,
        max_attachment_bytes: int,
        prefer_document: bool = False,
    ) -> None:
        # Teste de peça: em vez da última movimentação, a mais recente que tenha peça
        # (nunca intimação/citação).
        self._prefer_document = prefer_document
        self._sessions = sessions
        self._documents = documents
        self._diagnostics_dir = diagnostics_dir
        self._notifier = notifier
        self._max_attachment = max_attachment_bytes

    def run(self, cnj: CnjNumber, *, source_key: str | None = None) -> LatestResult:
        result = LatestResult(process=str(cnj))
        endpoints = [get_endpoint(source_key)] if source_key else list(candidate_sources(cnj))
        for endpoint in endpoints:
            if endpoint.key == "tjrj-portal":
                outcome = self._try_portal(cnj, endpoint, result)
                result.tried.append({"source": endpoint.key, "result": outcome})
                if result.found:
                    break
                continue
            if endpoint.system is not SourceSystem.PJE:
                result.tried.append({"source": endpoint.key, "result": "conector ainda não feito"})
                continue
            if not self._sessions.has_saved_state(endpoint):
                result.tried.append(
                    {"source": endpoint.key, "result": "sem sessão; rode auth-open"}
                )
                continue
            outcome = self._try_pje(cnj, endpoint, result)
            result.tried.append({"source": endpoint.key, "result": outcome})
            if result.found:
                break
        return result

    def _try_pje(self, cnj: CnjNumber, endpoint: SourceEndpoint, result: LatestResult) -> str:
        connector = PjeConnector(endpoint)
        headless = self._sessions.headless_for(endpoint)
        with self._sessions.context(endpoint, headless=headless) as context:
            autos = None
            try:
                autos = connector.open_autos(context, cnj)
                items = connector.read_timeline(autos)
            except ConnectorError as exc:
                if exc.code is ErrorCode.PARSE_ERROR:
                    page = autos or (context.pages[-1] if context.pages else None)
                    if page is not None:
                        result.diagnostics.append(str(self._dump(connector, page, endpoint)))
                return f"{exc.code.value}: {exc}"
            return self._deliver(context, connector, autos, cnj, endpoint, items, result)

    def _try_portal(self, cnj: CnjNumber, endpoint: SourceEndpoint, result: LatestResult) -> str:
        """Portal do TJRJ: login dentro do mesmo contexto (a sessão vive na aba, ADR-010)."""
        from legal_monitor.connectors.tjrj_portal import TjrjPortalConnector

        connector = TjrjPortalConnector(endpoint)
        with self._sessions.context(endpoint, headless=False) as context:
            if not connector.login(context):
                return "login não concluído"
            try:
                autos = connector.open_autos(context, cnj)
                items = connector.read_timeline(autos)
            except ConnectorError as exc:
                return f"{exc.code.value}: {exc}"
            return self._deliver(context, connector, autos, cnj, endpoint, items, result)

    def _pick(self, items):
        if self._prefer_document:
            for item in items:
                if item.documents and item.documents_allowed:
                    return item
        return items[0]

    def _deliver(self, context, connector, autos, cnj, endpoint, items, result) -> str:
        result.found = True
        result.source = endpoint.key
        latest = self._pick(items)
        result.movement_date = latest.date_text
        result.movement_text = latest.text[:MAX_MOVEMENT_TEXT]
        record = (
            self._download_first(context, connector, autos, cnj, endpoint, latest, result)
            if latest.documents_allowed
            else None
        )
        missing = None
        if record is None:
            if not latest.documents_allowed:
                missing = "intimação/citação: o robô não abre esses documentos; consulte no sistema"
            else:
                errors = [t["result"][5:] for t in result.tried if t["result"].startswith("doc: ")]
                missing = errors[-1].split(" | diagnóstico:")[0][:150] if errors else None
        if self._notifier is not None:
            attached = record is not None and record.bytes <= self._max_attachment
            self._notifier.send(
                build_movement_message(
                    cnj, endpoint, latest, record, attached=attached, missing_reason=missing
                )
            )
            result.emailed = True
        return "OK"

    def _download_first(self, context, connector, autos, cnj, endpoint, item, result):
        for document in item.documents:
            with tempfile.TemporaryDirectory(prefix="lcf-download-") as temporary:
                try:
                    path = connector.download_document(
                        context, autos, document, Path(temporary) / "documento.pdf"
                    )
                except ConnectorError as exc:
                    result.tried.append({"source": endpoint.key, "result": f"doc: {exc}"})
                    continue
                record = self._documents.store_pdf(
                    path,
                    process=ProcessRef(
                        cnj, tribunal=endpoint.tribunal, current_system=endpoint.system
                    ),
                    movement_type=document.label or "documento",
                    observed_at=item.event_date or datetime.now(UTC),
                )
            result.document = {
                "label": document.label,
                "sha256": record.sha256,
                "pages": record.page_count,
                "bytes": record.bytes,
                "stored_at": str(record.storage_path),
            }
            return record
        if not item.documents:
            result.tried.append({"source": endpoint.key, "result": "movimentação sem documento"})
        return None

    def _dump(self, connector: PjeConnector, page, endpoint: SourceEndpoint) -> Path:
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        return connector.dump_structure(
            page, self._diagnostics_dir / f"estrutura-{endpoint.key}-{stamp}.json"
        )
