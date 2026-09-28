"""Conector PJe (TJRJ 1º/2º grau), somente leitura.

Regras de segurança (ADR-007/ADR-008):
- só navega para a consulta processual e para a janela de autos aberta pelo próprio site;
- só clica no link de resultado da consulta e em links de documento da linha do tempo;
- nunca abre a aba "Expedientes" (abrir intimação ali pode registrar ciência e iniciar prazo);
- nunca clica em controles cujo texto indique escrita (peticionar, assinar, ciência, excluir...).
"""

from __future__ import annotations

import contextlib
import json
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urljoin

from legal_monitor.connectors.errors import AuthenticationRequired, ConnectorError
from legal_monitor.connectors.routing import SourceEndpoint
from legal_monitor.domain.cnj import CnjNumber
from legal_monitor.domain.enums import ErrorCode

if TYPE_CHECKING:
    from playwright.sync_api import BrowserContext, Page

FORBIDDEN_CONTROL = re.compile(
    r"peticion|assinar|ci[eê]ncia|excluir|remover|juntar|protocol|encerrar|sair|expediente",
    re.IGNORECASE,
)
DOCUMENT_ID = re.compile(r"idProcessoDoc(?:umento)?[=:'\"\s]+(\d+)|idDocumento[=:'\"\s]+(\d+)")
_MONTHS = {
    "jan": 1, "fev": 2, "mar": 3, "abr": 4, "mai": 5, "jun": 6,
    "jul": 7, "ago": 8, "set": 9, "out": 10, "nov": 11, "dez": 12,
}  # fmt: skip

# Extração tolerante da linha do tempo: marca cada link de documento com data-lcf-doc
# para que o Python clique exatamente no elemento lido, sem seletores frágeis.
_TIMELINE_JS = r"""
() => {
  const candidates = ['#divTimeLine', "[id$='divTimeLine']", "[id*='TimeLine']", '.timeline'];
  let root = null;
  for (const sel of candidates) { root = document.querySelector(sel); if (root) break; }
  if (!root) return {found: false, items: []};
  const dateRe = /^\s*(\d{1,2})\s+([a-zç]{3})\.?\s+(\d{4})\s*$/i;
  const numericDateRe = /^\s*(\d{2})\/(\d{2})\/(\d{4})/;
  const items = [];
  let currentDate = null;
  const nodes = root.querySelectorAll('.media, .data, [class*="data"], li');
  const seen = new Set();
  nodes.forEach((node) => {
    if (seen.has(node)) return;
    const text = (node.innerText || '').replace(/\s+/g, ' ').trim();
    if (!text) return;
    if (dateRe.test(text) || (numericDateRe.test(text) && text.length <= 12)) {
      currentDate = text; return;
    }
    if (!node.classList.contains('media') && node.tagName !== 'LI') return;
    node.querySelectorAll('*').forEach((child) => seen.add(child));
    const docs = [];
    node.querySelectorAll('a').forEach((a) => {
      const hint = (a.getAttribute('href') || '') + ' ' + (a.getAttribute('onclick') || '');
      if (!/idProcessoDoc|idDocumento|documento/i.test(hint)) return;
      const tag = `${items.length}-${docs.length}`;
      a.setAttribute('data-lcf-doc', tag);
      docs.push({tag, label: (a.innerText || a.title || '').replace(/\s+/g, ' ').trim(), hint});
    });
    items.push({date: currentDate, text, docs});
  });
  return {found: true, items};
}
"""

_STRUCTURE_JS = r"""
() => {
  const out = [];
  const walk = (el, depth) => {
    if (depth > 14 || out.length > 4000) return;
    const attrs = {};
    for (const name of ['id', 'class', 'name', 'role', 'type']) {
      const v = el.getAttribute && el.getAttribute(name);
      if (v) attrs[name] = v.replace(/\d{3,}/g, 'N').slice(0, 120);
    }
    for (const name of ['href', 'onclick']) {
      const v = el.getAttribute && el.getAttribute(name);
      if (v) attrs[name] = v.replace(/\d{3,}/g, 'N').replace(/'[^']{20,}'/g, "'…'").slice(0, 160);
    }
    out.push({d: depth, t: el.tagName, a: attrs, children: el.children.length});
    for (const c of el.children) walk(c, depth + 1);
  };
  walk(document.body, 0);
  return out;
}
"""


@dataclass(frozen=True, slots=True)
class TimelineDocument:
    tag: str
    label: str
    document_id: str | None


@dataclass(frozen=True, slots=True)
class TimelineItem:
    date_text: str | None
    text: str
    documents: tuple[TimelineDocument, ...] = field(default=())

    @property
    def event_date(self) -> datetime | None:
        return parse_pje_date(self.date_text)


def _strip_accents(value: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", value) if not unicodedata.combining(c))


def parse_pje_date(value: str | None) -> datetime | None:
    if not value:
        return None
    text = _strip_accents(value).strip().lower()
    match = re.match(r"(\d{1,2})\s+([a-z]{3})\.?\s+(\d{4})", text)
    if match and match.group(2) in _MONTHS:
        return datetime(
            int(match.group(3)), _MONTHS[match.group(2)], int(match.group(1)), tzinfo=UTC
        )
    match = re.match(r"(\d{2})/(\d{2})/(\d{4})", text)
    if match:
        return datetime(int(match.group(3)), int(match.group(2)), int(match.group(1)), tzinfo=UTC)
    return None


def items_from_payload(payload: dict[str, Any]) -> tuple[TimelineItem, ...]:
    items = []
    for raw in payload.get("items", []):
        docs = []
        for doc in raw.get("docs", []):
            found = DOCUMENT_ID.search(doc.get("hint", ""))
            doc_id = (found.group(1) or found.group(2)) if found else None
            docs.append(TimelineDocument(doc["tag"], doc.get("label", ""), doc_id))
        items.append(TimelineItem(raw.get("date"), raw.get("text", ""), tuple(docs)))
    return tuple(items)


class PjeConnector:
    def __init__(self, endpoint: SourceEndpoint) -> None:
        if endpoint.system.value != "PJE":
            raise ValueError("PjeConnector exige fonte PJe do catálogo")
        self.endpoint = endpoint
        self._base = endpoint.base_url.rsplit("/", 1)[0] + "/"

    @property
    def consulta_url(self) -> str:
        return urljoin(self._base, "Processo/ConsultaProcesso/listView.seam")

    def open_autos(self, context: BrowserContext, cnj: CnjNumber) -> Page:
        page = context.new_page()
        page.goto(self.consulta_url, wait_until="domcontentloaded")
        with contextlib.suppress(Exception):
            page.wait_for_load_state("networkidle", timeout=25_000)
        if "sso" in (page.url.split("/")[2] if "//" in page.url else ""):
            raise AuthenticationRequired()
        digits = cnj.digits
        parts = {
            "numeroSequencial": digits[0:7],
            "numeroDigitoVerificador": digits[7:9],
            "Ano": digits[9:13],
            "ramoJustica": digits[13],
            "respectivoTribunal": digits[14:16],
            "NumeroOrgaoJustica": digits[16:20],
        }
        try:
            for key, value in parts.items():
                page.fill(f"[id='fPP:numeroProcesso:{key}']", value)
        except Exception as exc:
            raise ConnectorError(ErrorCode.PARSE_ERROR, "Formulário de consulta PJe mudou") from exc
        page.click("[id='fPP:searchProcessos']")
        with contextlib.suppress(Exception):
            page.wait_for_load_state("networkidle", timeout=30_000)
        page.wait_for_timeout(1_500)
        link = page.locator("a[id^='fPP:processosTable:']").filter(has_text=str(cnj)).first
        if link.count() == 0:
            link = page.locator(
                "a[id^='fPP:processosTable:'][onclick*='idProcessoSelecionado']"
            ).first
        if link.count() == 0:
            raise ConnectorError(
                ErrorCode.SOURCE_UNAVAILABLE, "Processo não encontrado nesta fonte"
            )
        with context.expect_page(timeout=45_000) as popup:
            link.click()
        autos = popup.value
        with contextlib.suppress(Exception):
            autos.wait_for_load_state("networkidle", timeout=60_000)
        page.close()
        return autos

    def read_timeline(self, autos: Page) -> tuple[TimelineItem, ...]:
        payload = autos.evaluate(_TIMELINE_JS)
        items = items_from_payload(payload)
        if not payload.get("found") or not items:
            raise ConnectorError(ErrorCode.PARSE_ERROR, "Linha do tempo do PJe não reconhecida")
        return items

    def download_document(
        self, context: BrowserContext, autos: Page, document: TimelineDocument, target: Path
    ) -> Path:
        anchor = autos.locator(f"[data-lcf-doc='{document.tag}']").first
        label = " ".join((anchor.inner_text() or "").split())
        if FORBIDDEN_CONTROL.search(label):
            raise ConnectorError(ErrorCode.PARSE_ERROR, "Controle de escrita recusado")
        target.parent.mkdir(parents=True, exist_ok=True)
        # 1) O clique pode disparar um download direto.
        try:
            with autos.expect_download(timeout=15_000) as download_info:
                anchor.click()
            download_info.value.save_as(target)
            if target.read_bytes()[:5] == b"%PDF-":
                return target
        except Exception:  # noqa: S110 - segue para o visualizador embutido.
            pass
        # 2) Visualizador embutido: busca o binário pela mesma sessão (cookies do contexto).
        autos.wait_for_timeout(2_500)
        for frame in autos.frames:
            source = frame.url or ""
            if not source.startswith("http") or source == autos.url:
                continue
            response = context.request.get(source, timeout=60_000)
            body = response.body()
            if response.ok and body[:5] == b"%PDF-":
                target.write_bytes(body)
                return target
        raise ConnectorError(ErrorCode.INVALID_DOCUMENT, "Documento não obtido como PDF")

    @staticmethod
    def dump_structure(page: Page, target: Path) -> Path:
        """Diagnóstico sem conteúdo: só tags, ids e classes (números longos mascarados)."""
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(page.evaluate(_STRUCTURE_JS), ensure_ascii=False), encoding="utf-8"
        )
        return target
