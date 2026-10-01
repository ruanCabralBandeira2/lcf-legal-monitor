from __future__ import annotations

import base64
import shutil
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from legal_monitor.connectors.routing import CATALOG
from legal_monitor.connectors.tjrj_portal import (
    TjrjPortalConnector,
    _answer_browser_dialog,
    is_session_prompt,
    item_from_card,
    keep_session,
)
from legal_monitor.monitoring.monitor import connector_for

CHROME = "/Applications/Google Chrome.app"


class PortalCardTests(unittest.TestCase):
    def test_card_with_date_and_description(self) -> None:
        item = item_from_card(
            {
                "type": "Ato Ordinatório Praticado",
                "fields": [["Data", "23/09/2026"], ["Descrição", "Ao perito (texto fictício)"]],
            }
        )
        assert item is not None
        self.assertEqual(item.date_text, "23/09/2026")
        self.assertEqual(
            item.text, "Ato Ordinatório Praticado | Descrição: Ao perito (texto fictício)"
        )
        self.assertEqual(item.event_date.year, 2026)

    def test_card_with_only_a_named_date(self) -> None:
        item = item_from_card(
            {"type": "Envio de Documento Eletrônico", "fields": [["Data da remessa", "24/07/2026"]]}
        )
        assert item is not None
        self.assertEqual(item.date_text, "24/07/2026")
        self.assertEqual(item.text, "Envio de Documento Eletrônico")
        self.assertEqual(item.documents, ())

    def test_empty_card_is_ignored(self) -> None:
        self.assertIsNone(item_from_card({"type": "", "fields": [], "all": ""}))

    def test_portal_uses_its_own_connector_with_login_in_run(self) -> None:
        connector = connector_for(CATALOG["tjrj-portal"])
        self.assertIsInstance(connector, TjrjPortalConnector)
        self.assertTrue(connector.login_per_run)
        with self.assertRaises(ValueError):
            TjrjPortalConnector(CATALOG["pje-tjrj-1g"])


if __name__ == "__main__":
    unittest.main()


class SessionPromptTests(unittest.TestCase):
    def test_only_session_prompts_are_recognized(self) -> None:
        for text in (
            "Sua sessão irá expirar em 2 minutos. Deseja prolongar sua sessão?",
            "Deseja estender a sessão?",
            "A sessão está prestes a expirar. Deseja continuar?",
        ):
            self.assertTrue(is_session_prompt(text), text)
        for text in (
            "Deseja protocolar a petição?",
            "Confirma a ciência da intimação?",
            "Deseja sair do portal?",
        ):
            self.assertFalse(is_session_prompt(text), text)

    def test_native_dialog_accepts_only_session_prompt(self) -> None:
        class Dialog:
            def __init__(self, message: str) -> None:
                self.message = message
                self.result = ""

            def accept(self) -> None:
                self.result = "accept"

            def dismiss(self) -> None:
                self.result = "dismiss"

        session = Dialog("Deseja prolongar sua sessão?")
        other = Dialog("Confirma a ciência da intimação?")
        _answer_browser_dialog(session)
        _answer_browser_dialog(other)
        self.assertEqual((session.result, other.result), ("accept", "dismiss"))


_PAGE = """<html><body>
<div role="dialog" id="outro"><p>Deseja protocolar a petição?</p>
<button id="ruim">Sim</button></div>
<iframe srcdoc='<div class="p-dialog"><p>Sua sessão vai expirar. Deseja prolongar sua sessão?</p>
<button onclick="parent.document.body.dataset.ok=1">Sim</button>
<button>Não</button></div>'></iframe>
<script>document.getElementById('ruim').onclick = () => document.body.dataset.ruim = 1</script>
</body></html>"""


@unittest.skipUnless(shutil.which("open") and Path(CHROME).exists(), "Google Chrome ausente")
class SessionPromptBrowserTests(unittest.TestCase):
    def test_clicks_yes_only_on_session_modal_inside_frame(self) -> None:
        def run() -> tuple[bool, object, object]:
            from playwright.sync_api import sync_playwright

            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(channel="chrome", headless=True)
                try:
                    page = browser.new_page()
                    page.set_content(_PAGE)
                    page.wait_for_timeout(500)
                    clicked = keep_session(page)
                    return (
                        clicked,
                        page.evaluate("document.body.dataset.ok"),
                        page.evaluate("document.body.dataset.ruim"),
                    )
                finally:
                    browser.close()

        # Thread própria: outros testes deixam um laço asyncio que a API síncrona recusa.
        with ThreadPoolExecutor(max_workers=1) as pool:
            clicked, ok, wrong = pool.submit(run).result(timeout=120)
        self.assertTrue(clicked)
        self.assertEqual(ok, "1")
        self.assertIsNone(wrong)


_CARDS_PAGE = """<html><body>
<app-movimento><div>Tipo do Movimento: Conclusão ao Juiz</div>
<label class="control-label">Data:</label><label class="form-dados-estaticos">20/09/2026</label>
</app-movimento>
<app-movimento><div>Tipo do Movimento: Despacho fictício</div>
<label class="control-label">Data:</label><label class="form-dados-estaticos">25/09/2026</label>
<button>Ver Íntegra do(a) Despacho (Simplificado)</button>
<a href="#" id="ato">Visualizar Ato Assinado Digitalmente</a>
</app-movimento>
<script>
document.getElementById('ato').onclick = (e) => {
  e.preventDefault();
  const pdf = '%PDF-1.4\\n1 0 obj<<>>endobj\\ntrailer<<>>\\n%%EOF';
  const url = URL.createObjectURL(new Blob([pdf], {type: 'application/pdf'}));
  const embed = document.createElement('embed');
  embed.type = 'application/pdf'; embed.src = url; document.body.appendChild(embed);
};
</script></body></html>"""


@unittest.skipUnless(Path(CHROME).exists(), "Google Chrome ausente")
class PortalDocumentBrowserTests(unittest.TestCase):
    def test_reads_best_control_and_captures_embedded_pdf(self) -> None:
        def run() -> tuple[list[tuple[str, int]], bytes]:
            from playwright.sync_api import sync_playwright

            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(channel="chrome", headless=True)
                try:
                    context = browser.new_context()
                    page = context.new_page()
                    page.set_content(_CARDS_PAGE)
                    connector = TjrjPortalConnector(CATALOG["tjrj-portal"])
                    connector._page = page
                    items = connector.read_timeline(page.main_frame)
                    summary = [(item.text, len(item.documents)) for item in items]
                    document = next(item for item in items if item.documents).documents[0]
                    with tempfile.TemporaryDirectory() as folder:
                        target = Path(folder) / "documento.pdf"
                        connector.download_document(context, page.main_frame, document, target)
                        return summary, target.read_bytes()
                finally:
                    browser.close()

        with ThreadPoolExecutor(max_workers=1) as pool:
            summary, data = pool.submit(run).result(timeout=120)
        self.assertEqual(summary[0], ("Conclusão ao Juiz", 0))
        self.assertEqual(summary[1][1], 1)
        self.assertTrue(data.startswith(b"%PDF-1.4"), data[:120])

    def test_best_document_prefers_signed_act(self) -> None:
        card = {
            "all": "x",
            "docs": [
                {"label": "Ver Íntegra do(a) Decisão (Simplificado)", "mark": "0-0"},
                {"label": "Ver Íntegra Do(A) Decisão (Original)", "mark": "0-1"},
                {"label": "Visualizar Ato Assinado Digitalmente", "mark": "0-2"},
            ],
        }
        item = item_from_card({**card, "type": "Decisão", "fields": [["Data", "01/09/2026"]]}, 2)
        assert item is not None
        self.assertEqual(item.documents[0].label, "Visualizar Ato Assinado Digitalmente")
        self.assertTrue(item.documents[0].href.startswith("portal:2:"))


class ShortenTests(unittest.TestCase):
    def test_cuts_at_word_boundary_with_ellipsis(self) -> None:
        from legal_monitor.monitoring.monitor import shorten

        text = (
            "Arquivamento | Tipo de arquivamento: definitivo | Situação: Em fase de encaminhamento"
        )
        self.assertEqual(shorten(text, 200), text)
        self.assertEqual(
            shorten(text, 60), "Arquivamento | Tipo de arquivamento: definitivo | Situação…"
        )
        self.assertTrue(shorten("palavra " * 40, 50).endswith("palavra…"))


class PortalCaptureHelperTests(unittest.TestCase):
    class Response:
        def __init__(self, kind: str, body: bytes, url: str = "https://www3.tjrj.jus.br/x") -> None:
            self.headers = {"content-type": kind}
            self._body = body
            self.url = url

        def body(self) -> bytes:
            return self._body

        def text(self) -> str:
            return self._body.decode("utf-8")

    def test_binary_and_base64_json_pdf_are_accepted(self) -> None:
        from legal_monitor.connectors.tjrj_portal import _pdf_from_response

        pdf = b"%PDF-1.4\n" + b"0" * 300 + b"\n%%EOF"
        encoded = base64.b64encode(pdf).decode().replace("/", "\\/")
        cases = {
            "application/pdf": pdf,
            "application/octet-stream": pdf,
            "application/json": f'{{"arquivo": "{encoded}"}}'.encode(),
        }
        for kind, body in cases.items():
            self.assertEqual(_pdf_from_response(self.Response(kind, body)), pdf, kind)
        self.assertIsNone(_pdf_from_response(self.Response("text/html", b"<html>pdf</html>")))
        self.assertIsNone(_pdf_from_response(self.Response("application/pdf", b"<html>")))

    def test_masked_url_hides_numbers_and_tokens(self) -> None:
        from legal_monitor.connectors.tjrj_portal import _mask_url

        masked = _mask_url(
            "https://www3.tjrj.jus.br/visproc/#/0hrZj8Eia6ocIr5usZCRTZBw3SmRJibitKye1q?x=1"
        )
        self.assertEqual(masked, "www3.tjrj.jus.br/visproc/#/…")
        self.assertEqual(_mask_url("blob:https://www3.tjrj.jus.br/abc"), "blob:…")
        self.assertNotIn("0041299", _mask_url("https://x.jus.br/p/0041299/doc"))


_BLOB_TAB_PAGE = _CARDS_PAGE.replace(
    "const embed = document.createElement('embed');\n"
    "  embed.type = 'application/pdf'; embed.src = url; document.body.appendChild(embed);",
    "window.open(url, '_blank');",
)


@unittest.skipUnless(Path(CHROME).exists(), "Google Chrome ausente")
class PortalBlobTabBrowserTests(unittest.TestCase):
    def test_captures_pdf_opened_in_blob_tab(self) -> None:
        self.assertIn("window.open", _BLOB_TAB_PAGE)

        def run() -> bytes:
            from playwright.sync_api import sync_playwright

            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(channel="chrome", headless=True)
                try:
                    context = browser.new_context()
                    page = context.new_page()
                    page.set_content(_BLOB_TAB_PAGE)
                    connector = TjrjPortalConnector(CATALOG["tjrj-portal"])
                    connector._page = page
                    items = connector.read_timeline(page.main_frame)
                    document = next(item for item in items if item.documents).documents[0]
                    with tempfile.TemporaryDirectory() as folder:
                        target = Path(folder) / "documento.pdf"
                        connector.download_document(context, page.main_frame, document, target)
                        return target.read_bytes()
                finally:
                    browser.close()

        with ThreadPoolExecutor(max_workers=1) as pool:
            data = pool.submit(run).result(timeout=120)
        self.assertTrue(data.startswith(b"%PDF-1.4"), data[:80])


class PdfViewerResponseTests(unittest.TestCase):
    def test_refetches_when_chrome_viewer_holds_the_body(self) -> None:
        from legal_monitor.connectors.tjrj_portal import _pdf_from_response

        pdf = b"%PDF-1.7\n%%EOF"

        class ViewerResponse:
            url = "https://www3.tjrj.jus.br/gedcacheweb/default.aspx?id=fake"

            def __init__(self) -> None:
                self.headers = {"content-type": "application/pdf"}

            def body(self) -> bytes:
                raise RuntimeError("Response body is unavailable")

        class Again:
            ok = True

            def body(self) -> bytes:
                return pdf

        class Request:
            def __init__(self) -> None:
                self.urls: list[str] = []

            def get(self, url: str, timeout: int) -> Again:
                self.urls.append(url)
                return Again()

        class Context:
            request = Request()

        context = Context()
        self.assertEqual(_pdf_from_response(ViewerResponse(), context), pdf)
        self.assertEqual(context.request.urls, [ViewerResponse.url])
        self.assertIsNone(_pdf_from_response(ViewerResponse()))


_PROFILE_PAGE = """<html><body>
<p>Selecione o perfil de acesso</p>
<button id="abrir" aria-haspopup="listbox"
  onclick="document.getElementById('lista').style.display='block'">Selecione</button>
<ul id="lista" role="listbox" style="display:none">
  <li role="option" onclick="document.body.dataset.perfil='servidor'">Servidor</li>
  <li role="option" onclick="document.body.dataset.perfil='advogado'">Advogado</li>
</ul>
<button onclick="document.body.dataset.ok=document.body.dataset.perfil">Confirmar</button>
</body></html>"""


@unittest.skipUnless(Path(CHROME).exists(), "Google Chrome ausente")
class PortalProfileBrowserTests(unittest.TestCase):
    def test_opens_list_then_picks_lawyer_and_confirms(self) -> None:
        def run() -> object:
            from playwright.sync_api import sync_playwright

            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(channel="chrome", headless=True)
                try:
                    page = browser.new_page()
                    page.set_content(_PROFILE_PAGE)
                    connector = TjrjPortalConnector(CATALOG["tjrj-portal"])
                    with tempfile.TemporaryDirectory() as folder:
                        connector.diagnostics_dir = Path(folder)
                        connector._choose_lawyer_profile(page, dump=True)
                    return page.evaluate("document.body.dataset.ok")
                finally:
                    browser.close()

        with ThreadPoolExecutor(max_workers=1) as pool:
            self.assertEqual(pool.submit(run).result(timeout=120), "advogado")


# Cópia da estrutura real da tela "Trocar perfil" do Portal (gravada em 30/09/2026).
_TROCAR_PERFIL = """<html><body>
<div class="modal fade" style="display:none"><div class="modal-footer">
  <a role="button" onclick="document.body.dataset.ok='janela-escondida'">
  <div class="rodape-confirma">Confirmar</div></a></div></div>
<app-trocar-perfil><div class="modal-content">
<div class="modal-body"><app-dropdown id="dropdownPerfil">
<label class="control-label">Perfil</label>
<div class="select-autocomplete">
  <div class="form-inline ajustado-form"><input type="text" placeholder="Selecione"
    onclick="document.querySelector('.box-resultados').style.display='block'"></div>
  <div class="box-resultados" style="display:none"><ul>
    <li onclick="escolher('Servidor')">Servidor</li>
    <li onclick="escolher('Advogado')">Advogado</li></ul></div>
</div></app-dropdown></div>
<div class="modal-footer">
  <a id="entrar" class="isDisabled" role="button" href="javascript:void(0)" style="display:contents"
     onclick="if (!this.classList.contains('isDisabled'))
       document.body.dataset.ok = document.body.dataset.perfil">
     <div class="rodape-confirma">Entrar</div></a>
  <a class="isDisabled" role="button"><div class="rodape-cancela">Cancelar</div></a>
</div></div></app-trocar-perfil>
<script>function escolher(p){ document.body.dataset.perfil=p;
  document.getElementById('entrar').classList.remove('isDisabled'); }</script>
</body></html>"""


@unittest.skipUnless(Path(CHROME).exists(), "Google Chrome ausente")
class PortalTrocarPerfilBrowserTests(unittest.TestCase):
    def test_real_structure_box_lawyer_then_green_enter(self) -> None:
        def run() -> object:
            from playwright.sync_api import sync_playwright

            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(channel="chrome", headless=True)
                try:
                    page = browser.new_page()
                    page.set_content(_TROCAR_PERFIL)
                    connector = TjrjPortalConnector(CATALOG["tjrj-portal"])
                    with tempfile.TemporaryDirectory() as folder:
                        connector.diagnostics_dir = Path(folder)
                        connector._choose_lawyer_profile(page)
                    return page.evaluate("document.body.dataset.ok")
                finally:
                    browser.close()

        with ThreadPoolExecutor(max_workers=1) as pool:
            self.assertEqual(pool.submit(run).result(timeout=120), "Advogado")
