"""Conector eproc (TJRJ 1º/2º grau, JFRJ, TRF2, TRF4), somente leitura (ADR-009).

Todas as instâncias usam o mesmo sistema (eproc 9.x, TRF4), então um único leitor serve
para todas; muda apenas o endereço e o login de cada site.

Regras de segurança:
- navega só pela busca rápida (`txtNumProcessoPesquisaRapida`) e pela página do processo;
- busca documentos por requisição direta, e só de URLs cuja `acao` está na lista permitida;
- nunca abre documentos de eventos de intimação/citação (risco de registrar ciência);
- diálogos JavaScript (confirmações) são recusados automaticamente pelo Playwright.
"""

from __future__ import annotations

import contextlib
import html
import json
import re
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import parse_qs, urljoin, urlparse

from legal_monitor.connectors.errors import AuthenticationRequired, ConnectorError
from legal_monitor.connectors.pje import (
    _STRUCTURE_JS,
    FORBIDDEN_PATTERN,
    TimelineDocument,
    TimelineItem,
    items_from_payload,
)
from legal_monitor.connectors.routing import SourceEndpoint
from legal_monitor.domain.cnj import CnjNumber
from legal_monitor.domain.enums import ErrorCode, SourceSystem

if TYPE_CHECKING:
    from playwright.sync_api import BrowserContext, Page

DOCUMENT_ACTIONS = frozenset(
    {"acessar_documento", "acessar_documento_implementacao", "acessar_documento_publico"}
)
PROCESS_ACTIONS = frozenset({"processo_selecionar"})
_EMBEDDED_DOCUMENT = re.compile(
    r"""(?:src|data|href)\s*=\s*["']([^"']*acao=acessar_documento_implementacao[^"']*)["']""",
    re.IGNORECASE,
)

# Tabela de eventos: localiza pela id conhecida (#tblEventos) ou pelo cabeçalho.
# Cada linha com data vira um item; links de documento recebem data-lcf-doc.
_EVENTS_JS = r"""
(forbiddenSource) => {
  const forbidden = new RegExp(forbiddenSource, 'i');
  let table = document.querySelector('#tblEventos');
  if (!table) {
    table = [...document.querySelectorAll('table')].find((t) => {
      const head = (t.querySelector('tr') || t).innerText || '';
      return /evento/i.test(head) && /data/i.test(head) && /descri/i.test(head);
    }) || null;
  }
  if (!table) return {found: false, items: []};
  const items = [];
  table.querySelectorAll('tr').forEach((tr) => {
    const cells = [...tr.querySelectorAll(':scope > td')];
    if (cells.length < 3) return;
    const texts = cells.map((td) => (td.innerText || '').replace(/\s+/g, ' ').trim());
    const dateIdx = texts.findIndex((t) => /^\d{2}\/\d{2}\/\d{4}/.test(t));
    if (dateIdx < 0) return;
    const event = texts.slice(0, dateIdx).map((t) => t.match(/^\d+/)).find(Boolean);
    const docs = [];
    tr.querySelectorAll('a[href]').forEach((a) => {
      const href = a.getAttribute('href') || '';
      if (!/acao=acessar_documento/i.test(href)) return;
      const label = (a.innerText || a.title || '').replace(/\s+/g, ' ').trim();
      if (forbidden.test(label) || forbidden.test(a.title || '')) return;
      const tag = `${items.length}-${docs.length}`;
      a.setAttribute('data-lcf-doc', tag);
      docs.push({tag, label, hint: href});
    });
    items.push({
      date: texts[dateIdx],
      text: texts[dateIdx + 1] || '',
      docs,
      event: event ? event[0] : null,
    });
  });
  return {found: true, items};
}
"""


def action_of(url: str) -> str:
    return parse_qs(urlparse(url).query).get("acao", [""])[0]


class EprocConnector:
    system = SourceSystem.EPROC

    def __init__(self, endpoint: SourceEndpoint) -> None:
        if endpoint.system is not SourceSystem.EPROC:
            raise ValueError("EprocConnector exige fonte eproc do catálogo")
        self.endpoint = endpoint

    def open_autos(self, context: BrowserContext, cnj: CnjNumber) -> Page:
        page = context.new_page()
        page.goto(self.endpoint.base_url, wait_until="domcontentloaded")
        with contextlib.suppress(Exception):
            page.wait_for_load_state("networkidle", timeout=25_000)
        host = urlparse(page.url).hostname or ""
        if host != self.endpoint.host or page.locator("input[type='password']").count():
            page.close()
            raise AuthenticationRequired()
        box = page.locator("#txtNumProcessoPesquisaRapida").first
        if box.count() == 0:
            raise ConnectorError(ErrorCode.PARSE_ERROR, "Busca rápida do eproc não encontrada")
        box.fill(cnj.digits)
        box.press("Enter")
        with contextlib.suppress(Exception):
            page.wait_for_load_state("networkidle", timeout=30_000)
        if action_of(page.url) in PROCESS_ACTIONS:
            return page
        # Mais de um resultado (ex.: instâncias diferentes): segue o link do número exato.
        link = page.locator("a[href*='acao=processo_selecionar']").filter(has_text=str(cnj)).first
        if link.count():
            target = urljoin(page.url, link.get_attribute("href") or "")
            if action_of(target) in PROCESS_ACTIONS:
                page.goto(target, wait_until="domcontentloaded")
                with contextlib.suppress(Exception):
                    page.wait_for_load_state("networkidle", timeout=30_000)
                return page
        page.close()
        raise ConnectorError(ErrorCode.SOURCE_UNAVAILABLE, "Processo não encontrado nesta fonte")

    def read_timeline(self, autos: Page) -> tuple[TimelineItem, ...]:
        payload = autos.evaluate(_EVENTS_JS, FORBIDDEN_PATTERN)
        items = items_from_payload(payload)
        if not payload.get("found") or not items:
            raise ConnectorError(
                ErrorCode.PARSE_ERROR, "Tabela de eventos do eproc não reconhecida"
            )
        # O eproc lista do evento mais recente para o mais antigo; garante essa ordem.
        if all(item.event_id and item.event_id.isdigit() for item in items):
            items = tuple(sorted(items, key=lambda item: int(item.event_id or 0), reverse=True))
        return items

    def download_document(
        self, context: BrowserContext, autos: Page, document: TimelineDocument, target: Path
    ) -> Path:
        href = autos.locator(f"[data-lcf-doc='{document.tag}']").first.get_attribute("href")
        url = self._allowed_document_url(urljoin(autos.url, href or ""))
        target.parent.mkdir(parents=True, exist_ok=True)
        body = context.request.get(url, timeout=90_000).body()
        if body[:5] == b"%PDF-":
            target.write_bytes(body)
            return target
        # Página intermediária do visualizador: segue o binário embutido.
        embedded = _EMBEDDED_DOCUMENT.search(body.decode("utf-8", errors="ignore"))
        if embedded:
            url = self._allowed_document_url(urljoin(url, html.unescape(embedded.group(1))))
            body = context.request.get(url, timeout=90_000).body()
            if body[:5] == b"%PDF-":
                target.write_bytes(body)
                return target
        # Documento gerado em HTML (despacho/decisão do próprio eproc): imprime em PDF.
        # Page.pdf só funciona com navegador headless, que é o modo do eproc.
        viewer = context.new_page()
        try:
            viewer.goto(url, wait_until="networkidle")
            viewer.pdf(path=str(target), format="A4", print_background=True)
        except Exception as exc:
            raise ConnectorError(
                ErrorCode.INVALID_DOCUMENT, "Documento HTML não convertido em PDF"
            ) from exc
        finally:
            viewer.close()
        if target.read_bytes()[:5] != b"%PDF-":
            raise ConnectorError(ErrorCode.INVALID_DOCUMENT, "Documento não obtido como PDF")
        return target

    def _allowed_document_url(self, url: str) -> str:
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.hostname != self.endpoint.host:
            raise ConnectorError(ErrorCode.PARSE_ERROR, "Documento fora do site oficial recusado")
        if action_of(url) not in DOCUMENT_ACTIONS:
            raise ConnectorError(ErrorCode.PARSE_ERROR, "Ação do eproc fora da lista permitida")
        return url

    @staticmethod
    def dump_structure(page: Page, target: Path) -> Path:
        """Diagnóstico sem conteúdo: só tags, ids e classes (números longos mascarados)."""
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(page.evaluate(_STRUCTURE_JS), ensure_ascii=False), encoding="utf-8"
        )
        return target
