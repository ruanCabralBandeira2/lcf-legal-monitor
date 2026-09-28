from __future__ import annotations

import unittest

from legal_monitor.connectors.eproc import (
    _EVENTS_JS,
    NOT_FOUND_TEXT,
    EprocConnector,
    action_of,
)
from legal_monitor.connectors.errors import ConnectorError
from legal_monitor.connectors.pje import FORBIDDEN_PATTERN, items_from_payload
from legal_monitor.connectors.routing import CATALOG

# Página sintética no formato da tabela de eventos do eproc (dados fictícios).
EPROC_FIXTURE = """
<html><body>
<table id="tblEventos">
  <tr><th>Evento</th><th>Data/Hora</th><th>Descrição</th><th>Usuário</th><th>Documentos</th></tr>
  <tr>
    <td>12</td><td>28/09/2026 14:32:10</td>
    <td>Intimação Eletrônica - Expedida/Certificada</td><td>X</td>
    <td><a href="controlador.php?acao=acessar_documento&doc=900&evento=12">INTIM1</a></td>
  </tr>
  <tr>
    <td>11</td><td>27/09/2026 10:00:00</td><td>Despacho/Decisão - Deferido</td><td>Y</td>
    <td>
      <a href="controlador.php?acao=acessar_documento&doc=777&evento=11">DESPADEC1</a>
      <a href="controlador.php?acao=processo_movimentar&evento=11">Peticionar</a>
    </td>
  </tr>
  <tr>
    <td>10</td><td>20/09/2026 09:00:00</td><td>Juntada de Petição</td><td>Z</td>
    <td><a href="controlador.php?acao=acessar_documento&doc=555&evento=10">PET1</a></td>
  </tr>
</table>
</body></html>
"""


def _payload_from_edge() -> dict | None:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return None
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel="msedge", headless=True)
            page = browser.new_page()
            page.set_content(EPROC_FIXTURE)
            payload = page.evaluate(_EVENTS_JS, FORBIDDEN_PATTERN)
            browser.close()
            return payload
    except Exception:
        return None


class EprocConnectorTests(unittest.TestCase):
    def test_only_document_actions_on_official_host_are_allowed(self) -> None:
        connector = EprocConnector(CATALOG["eproc-jfrj-1g"])
        base = "https://eproc.jfrj.jus.br/eproc/controlador.php?acao="
        self.assertTrue(connector._allowed_document_url(base + "acessar_documento&doc=1"))
        for bad in (
            base + "processo_movimentar&evento=1",
            base + "citacao_intimacao_prazo_aberto_listar",
            "https://evil.example/eproc/controlador.php?acao=acessar_documento&doc=1",
            "http://eproc.jfrj.jus.br/eproc/controlador.php?acao=acessar_documento&doc=1",
        ):
            with self.assertRaises(ConnectorError, msg=bad):
                connector._allowed_document_url(bad)
        self.assertEqual(action_of(base + "processo_selecionar&num=1"), "processo_selecionar")

    def test_not_found_requires_the_eproc_message(self) -> None:
        self.assertTrue(NOT_FOUND_TEXT.search("Processo nao encontrado. [00000000000000000000]"))
        self.assertFalse(NOT_FOUND_TEXT.search("Painel do Advogado - Consulta Processual"))

    def test_rejects_non_eproc_source(self) -> None:
        with self.assertRaises(ValueError):
            EprocConnector(CATALOG["pje-tjrj-1g"])

    def test_events_table_extraction_in_real_browser(self) -> None:
        payload = _payload_from_edge()
        if payload is None:
            self.skipTest("Edge/Playwright indisponível (ex.: CI Linux)")
        items = items_from_payload(payload)
        self.assertEqual([item.event_id for item in items], ["12", "11", "10"])
        self.assertEqual(items[1].text, "Despacho/Decisão - Deferido")
        self.assertEqual(items[1].date_text, "27/09/2026 10:00:00")
        # O link "Peticionar" não é documento e nunca é coletado.
        self.assertEqual([doc.document_id for doc in items[1].documents], ["777"])
        # Evento de intimação: documento listado, mas bloqueado para abertura.
        self.assertFalse(items[0].documents_allowed)
        self.assertTrue(items[1].documents_allowed)


if __name__ == "__main__":
    unittest.main()
