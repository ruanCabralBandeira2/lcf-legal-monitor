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
    _strip_accents,
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
# Paginação padrão das tabelas do eproc (framework "infra" do TRF4).
NEXT_PAGE_SELECTOR = "a[id^='lnkInfraProximaPagina']"
MAX_EVENT_PAGES = 60
# Carregamento sob demanda da tabela de eventos (TRF2, 28/09/2026): rolar até o fim.
MAX_LOAD_ROUNDS = 120
LOAD_STABLE_ROUNDS = 3
_SCROLL_TO_END_JS = r"""
() => {
  const table = document.querySelector('#tblEventos');
  const last = table && table.querySelector('tr:last-child');
  if (last) last.scrollIntoView({block: 'end'});
  const box = document.querySelector('#divTblEventos');
  if (box) box.scrollTop = box.scrollHeight;
  window.scrollTo(0, document.body.scrollHeight);
}
"""
# Mensagem do eproc para busca sem resultado (texto já sem acentos).
NOT_FOUND_TEXT = re.compile(r"nao encontrad|nenhum (?:processo|registro)", re.IGNORECASE)
_EMBEDDED_DOCUMENT = re.compile(
    r"""(?:src|data|href)\s*=\s*["']([^"']*acao=acessar_documento_implementacao[^"']*)["']""",
    re.IGNORECASE,
)

# Tabela de eventos: localiza pela id conhecida (#tblEventos) ou pelo cabeçalho.
# Cada linha com data vira um item; links de documento recebem data-lcf-doc.
_EVENTS_JS = r"""
([forbiddenSource, pageIndex]) => {
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
      const tag = `${pageIndex}-${items.length}-${docs.length}`;
      a.setAttribute('data-lcf-doc', tag);
      docs.push({tag, label, hint: href, href});
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
        # "Não encontrado" só com a mensagem do próprio eproc; qualquer outra tela vira erro
        # com diagnóstico (a página fica aberta para o registro de estrutura).
        body = ""
        with contextlib.suppress(Exception):
            body = _strip_accents(page.locator("body").inner_text(timeout=5_000))
        if NOT_FOUND_TEXT.search(body):
            page.close()
            raise ConnectorError(
                ErrorCode.SOURCE_UNAVAILABLE, "Processo não encontrado nesta fonte"
            )
        raise ConnectorError(ErrorCode.PARSE_ERROR, "Resultado da busca do eproc não reconhecido")

    def read_timeline(self, autos: Page) -> tuple[TimelineItem, ...]:
        """Lê TODAS as páginas da tabela de eventos (1º uso real, 28/09/2026: o eproc do TRF2
        mostrou só os eventos 1-50 na primeira página)."""
        collected: dict[str, TimelineItem] = {}
        table_found = False
        for page_index in range(MAX_EVENT_PAGES):
            self._load_all_events(autos)
            payload = autos.evaluate(_EVENTS_JS, [FORBIDDEN_PATTERN, page_index])
            table_found = table_found or bool(payload.get("found"))
            for item in items_from_payload(payload):
                key = item.event_id or f"{page_index}|{item.date_text}|{item.text}"
                collected.setdefault(key, item)
            next_link = autos.locator(NEXT_PAGE_SELECTOR).first
            if next_link.count() == 0 or not next_link.is_visible():
                break
            # Paginação da tabela (infraAcaoPaginar): somente leitura.
            next_link.click()
            with contextlib.suppress(Exception):
                autos.wait_for_load_state("networkidle", timeout=30_000)
        else:
            raise ConnectorError(
                ErrorCode.PARSE_ERROR, f"Mais de {MAX_EVENT_PAGES} páginas de eventos"
            )
        items = tuple(collected.values())
        if not table_found or not items:
            raise ConnectorError(
                ErrorCode.PARSE_ERROR, "Tabela de eventos do eproc não reconhecida"
            )
        # Do evento mais recente para o mais antigo, independentemente da ordem da tela.
        if all(item.event_id and item.event_id.isdigit() for item in items):
            items = tuple(sorted(items, key=lambda item: int(item.event_id or 0), reverse=True))
        return items

    @staticmethod
    def _load_all_events(autos: Page) -> None:
        """O eproc (ex.: TRF2) desenha 50 eventos e carrega o resto sob demanda ao rolar
        (`#carregarNovosEventos`). Rola até o fim até o número de linhas parar de crescer."""
        previous, stable = -1, 0
        for _ in range(MAX_LOAD_ROUNDS):
            rows = autos.locator("#tblEventos tr").count()
            if rows == previous:
                stable += 1
                if stable >= LOAD_STABLE_ROUNDS:
                    return
            else:
                stable = 0
            previous = rows
            with contextlib.suppress(Exception):
                autos.evaluate(_SCROLL_TO_END_JS)
            with contextlib.suppress(Exception):
                autos.wait_for_load_state("networkidle", timeout=8_000)
            autos.wait_for_timeout(700)

    def download_document(
        self, context: BrowserContext, autos: Page, document: TimelineDocument, target: Path
    ) -> Path:
        # Usa o endereço lido na tabela: com várias páginas, a posição na tela não serve.
        href = document.href or autos.locator(
            f"[data-lcf-doc='{document.tag}']"
        ).first.get_attribute("href")
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
