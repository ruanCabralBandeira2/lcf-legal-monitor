"""Conector do Portal de Serviços do TJRJ (processo eletrônico legado), somente leitura.

Fluxo mapeado pela gravação guiada e por vídeo do operador em 30/09/2026 (ADR-010):
- login IdServerJus pelo botão de certificado (imagem); a escolha do certificado e o PIN
  ficam com a pessoa, salvo seleção automática configurada no próprio Chrome;
- a sessão vive na aba (não sobrevive a uma janela nova): o login acontece dentro da rodada;
- a consulta roda num quadro embutido (`consultaprocessual`): aba "Por Número", numeração
  "Única", número em duas partes (`NNNNNNN-DD.AAAA` + `.8.19.` fixo + `OOOO`), "Pesquisar";
- os detalhes mostram cartões `app-movimento` ("Tipo do Movimento: ...", datas e descrição),
  paginados, do mais recente para o mais antigo.

Regras de segurança: só a consulta; nunca clicar em Petição Eletrônica, Push, Distribuição
ou qualquer controle de escrita; peças (Visualizador) ficam para a próxima etapa.
"""

from __future__ import annotations

import base64
import contextlib
import hashlib
import json
import re
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

from legal_monitor.connectors.errors import AuthenticationRequired, ConnectorError
from legal_monitor.connectors.pje import TimelineDocument, TimelineItem
from legal_monitor.connectors.routing import SourceEndpoint
from legal_monitor.domain.cnj import CnjNumber
from legal_monitor.domain.enums import ErrorCode

if TYPE_CHECKING:
    from playwright.sync_api import BrowserContext, Frame, Page

PORTAL_HOME = "https://www3.tjrj.jus.br/portalservicos/#/dashboard"
CONSULTA_URL = "https://www3.tjrj.jus.br/portalservicos/#/consproc/consultaportal"
CONSULTA_FRAME = "consultaprocessual"
LOGIN_TIMEOUT_SECONDS = 600  # 10 min: login pelo Parsec do celular (30/09/2026)
MAX_PAGES = 40
# Motivo mostrado no e-mail enquanto o download pelo Visualizador não existe.
NO_DOCUMENTS_REASON = (
    'esta movimentação do Portal não tem peça para abrir (sem "Ver Íntegra" nem '
    '"Ato Assinado"); se houver peça, ela está no Visualizador do Portal'
)
# Preferência: ato assinado (PDF oficial) > íntegra original > íntegra simplificada.
_DOC_PRIORITY = (
    re.compile(r"Ato Assinado", re.I),
    re.compile(r"Original", re.I),
    re.compile(r"Simplificad", re.I),
)
DOWNLOAD_TIMEOUT_S = 60
NOT_FOUND_TEXT = re.compile(
    r"n[aã]o (?:foi |foram )?encontrad|nenhum (?:processo|registro)", re.IGNORECASE
)
# Aviso do Portal no meio da rodada (30/09/2026, ~10 min após o login): "deseja prolongar
# sua sessão?". Só essa pergunta recebe "Sim"; qualquer outra caixa é recusada.
SESSION_PROMPT = re.compile(
    r"sess[aã]o.{0,80}(prolong|estend|renov|expir|continu|encerr)"
    r"|(prolong|estend|renov|expir|continu|encerr).{0,80}sess[aã]o",
    re.IGNORECASE | re.DOTALL,
)
_MODALS = (
    "[role=dialog]:visible, [role=alertdialog]:visible, .p-dialog:visible, "
    ".p-confirm-dialog:visible, .modal.show, .modal-dialog:visible, .swal2-popup:visible, "
    ".rich-mpnl-content:visible, .ui-dialog:visible"
)
_YES = re.compile(r"^\s*(sim|prolongar|continuar|renovar|manter)", re.IGNORECASE)


def is_session_prompt(text: str) -> bool:
    return bool(SESSION_PROMPT.search(" ".join((text or "").split())))


def _answer_browser_dialog(dialog: Any) -> None:
    """alert/confirm nativo: aceita só o de prolongar a sessão; recusa todo o resto."""
    with contextlib.suppress(Exception):
        if is_session_prompt(str(dialog.message)):
            dialog.accept()
        else:
            dialog.dismiss()


def keep_session(page: Page | None) -> bool:
    """Clica "Sim" no aviso de prolongar a sessão, na página ou em qualquer quadro."""
    if page is None:
        return False
    with contextlib.suppress(Exception):
        if page.is_closed():
            return False
        for target in [page.main_frame, *page.frames]:
            with contextlib.suppress(Exception):
                modals = target.locator(_MODALS)
                for index in range(min(modals.count(), 5)):
                    modal = modals.nth(index)
                    if not is_session_prompt(modal.inner_text(timeout=1_000)):
                        continue
                    button = modal.get_by_role("button", name=_YES)
                    if not button.count():
                        button = modal.locator("button, a.btn, [role=button]").filter(has_text=_YES)
                    if button.count():
                        button.first.click(timeout=5_000)
                        page.wait_for_timeout(1_000)
                        return True
    return False


# Lê os cartões de movimento: "Tipo do Movimento: X" + pares rótulo/valor (Data..., Descrição...).
_CARDS_JS = r"""
() => [...document.querySelectorAll('app-movimento')].map((card, index) => {
  const clean = s => (s || '').replace(/\s+/g, ' ').trim();
  const all = clean(card.innerText);
  const typeMatch = all.match(/Tipo do Movimento:\s*(.+?)(?=\s+(?:Data|Descri)|$)/i);
  const fields = [];
  card.querySelectorAll('label.control-label').forEach(label => {
    let value = label.nextElementSibling;
    while (value && !(value.classList && value.classList.contains('form-dados-estaticos'))) {
      value = value.nextElementSibling;
    }
    if (!value) {
      const box = label.parentElement;
      value = box ? box.querySelector('.form-dados-estaticos') : null;
    }
    fields.push([clean(label.innerText).replace(/:$/, ''), clean(value ? value.innerText : '')]);
  });
  // Controles de peça do cartão (só leitura): marcados para o Python clicar no elemento lido.
  const docs = [];
  card.querySelectorAll('a, button, [role=button]').forEach(control => {
    const label = clean(control.innerText || control.getAttribute('title') || '');
    if (/Visualizar Ato Assinado|Ver [IÍ]ntegra/i.test(label)) {
      control.setAttribute('data-lcf-doc', `${index}-${docs.length}`);
      docs.push({label, mark: `${index}-${docs.length}`});
    }
  });
  return {type: typeMatch ? clean(typeMatch[1]) : '', fields, all: all.slice(0, 1500), docs};
})
"""

# Lê um PDF de endereço blob: dentro da própria página (base64 para atravessar a ponte).
_BLOB_JS = r"""
async (url) => {
  const bytes = new Uint8Array(await (await fetch(url)).arrayBuffer());
  let text = '';
  for (let i = 0; i < bytes.length; i++) text += String.fromCharCode(bytes[i]);
  return btoa(text);
}
"""

_DATE = re.compile(r"\d{2}/\d{2}/\d{4}(?:\s+\d{2}:\d{2}(?::\d{2})?)?")


def card_key(card: dict[str, Any]) -> str:
    """Identifica o cartão na tela (para voltar a ele na hora de baixar a peça)."""
    return hashlib.sha256(str(card.get("all") or "").encode("utf-8")).hexdigest()[:16]


def best_document(card: dict[str, Any], page_no: int) -> TimelineDocument | None:
    """Um controle de peça por cartão (o melhor); evita anexar a mesma decisão duas vezes."""
    docs = [d for d in card.get("docs", []) if d.get("label")]
    for pattern in _DOC_PRIORITY:
        chosen = next((d for d in docs if pattern.search(d["label"])), None)
        if chosen:
            break
    else:
        chosen = docs[0] if docs else None
    if chosen is None:
        return None
    # href guarda onde achar o controle de novo: página da lista, cartão e rótulo.
    return TimelineDocument(
        "portal-peca", chosen["label"], None, f"portal:{page_no}:{card_key(card)}"
    )


def item_from_card(card: dict[str, Any], page_no: int = 1) -> TimelineItem | None:
    """Um cartão do Portal vira um item da linha do tempo (texto estável entre rodadas)."""
    fields = [(str(k), str(v)) for k, v in card.get("fields", []) if k or v]
    date_text = next(
        (m.group(0) for k, v in fields if k.lower().startswith("data") and (m := _DATE.search(v))),
        None,
    )
    kind = str(card.get("type") or "").strip()
    details = [f"{k}: {v}" for k, v in fields if v and not k.lower().startswith("data")]
    extra_dates = [
        f"{k}: {v}"
        for k, v in fields
        if v
        and k.lower().startswith("data")
        and _DATE.search(v)
        and _DATE.search(v).group(0) != date_text
    ]
    text = " | ".join(part for part in [kind, *details, *extra_dates] if part)
    if not text:
        text = str(card.get("all") or "").strip()
    if not text:
        return None
    document = best_document(card, page_no)
    return TimelineItem(date_text, text, (document,) if document else ())


def _mask_url(url: str) -> str:
    """Endereço sem query e com números longos mascarados (diagnóstico sem conteúdo)."""
    parsed = urlparse(url)
    if parsed.scheme in ("blob", "data", "about", "chrome-extension"):
        return f"{parsed.scheme}:…"
    path = re.sub(r"\d{3,}", "N", parsed.path)
    path = re.sub(r"[A-Za-z0-9_-]{24,}", "…", path)
    fragment = re.sub(r"\d{3,}", "N", parsed.fragment.split("?")[0])
    fragment = re.sub(r"[A-Za-z0-9_%+=-]{24,}", "…", fragment)[:50]
    return f"{parsed.hostname or ''}{path[:120]}" + (f"#{fragment}" if fragment else "")


def _describe_control(control: Any) -> dict[str, str]:
    """Tag e atributos do controle de peça (mascarados), para entender o que ele abre."""
    with contextlib.suppress(Exception):
        attrs = control.evaluate(
            "e => ({tag: e.tagName, ...Object.fromEntries("
            "[...e.attributes].map(a => [a.name, a.value]))})"
        )
        return {k: re.sub(r"\d{3,}", "N", str(v))[:160] for k, v in attrs.items()}
    return {}


_BASE64_PDF = re.compile(r"JVBERi0[A-Za-z0-9+/=\\]{200,}")


def _pdf_from_response(response: Any, context: Any = None) -> bytes | None:
    """PDF binário (application/pdf, octet-stream...) ou PDF em base64 dentro de JSON/texto.

    1º teste real (30/09/2026): "Visualizar Ato Assinado" abre uma aba em
    `gedcacheweb/default.aspx` com `application/pdf`; o visualizador do Chrome toma o corpo
    da resposta, então o mesmo endereço é pedido de novo com a sessão do contexto."""
    with contextlib.suppress(Exception):
        if not response.url.startswith("http"):
            return None
        kind = (response.headers or {}).get("content-type", "").lower()
        if any(word in kind for word in ("pdf", "octet-stream", "download", "binary")):
            body = b""
            with contextlib.suppress(Exception):
                body = response.body()
            if not body.startswith(b"%PDF") and context is not None:
                again = context.request.get(response.url, timeout=60_000)
                body = again.body() if again.ok else b""
            return body if body.startswith(b"%PDF") else None
        if "json" in kind or "text/plain" in kind:
            found = _BASE64_PDF.search(response.text())
            if found:
                data = base64.b64decode(found.group(0).replace("\\/", "/").replace("\\", ""))
                return data if data.startswith(b"%PDF") else None
    return None


class TjrjPortalConnector:
    """Mesma interface do PJe/eproc: `open_autos`, `read_timeline`, `download_document`."""

    # O monitor faz o login dentro da rodada (a sessão do Portal vive na aba).
    login_per_run = True
    no_documents_reason = NO_DOCUMENTS_REASON

    def __init__(self, endpoint: SourceEndpoint) -> None:
        if endpoint.key != "tjrj-portal":
            raise ValueError("TjrjPortalConnector exige a fonte tjrj-portal do catálogo")
        self.endpoint = endpoint
        self._page: Page | None = None
        self.diagnostics_dir = Path("storage/tmp/diagnostico")

    # --- login -------------------------------------------------------------------------
    def login(
        self, context: BrowserContext, on_waiting: Any = None, timeout_seconds: int | None = None
    ) -> bool:
        """Abre o login oficial e clica no botão público de certificado. A escolha do
        certificado e o PIN são humanos (ou a seleção automática do Chrome). Retorna True
        quando o Portal abre logado."""
        context.on("dialog", _answer_browser_dialog)
        page = context.new_page()
        page.goto(self.endpoint.base_url, wait_until="domcontentloaded")
        with contextlib.suppress(Exception):
            page.wait_for_selector(
                self.endpoint.certificate_login_selector or "img", timeout=20_000
            )
            page.locator(self.endpoint.certificate_login_selector or "img").first.click(
                timeout=10_000
            )
        started = time.monotonic()
        notified = False
        profile_tries = 0
        limit = timeout_seconds or LOGIN_TIMEOUT_SECONDS
        while time.monotonic() - started < limit:
            for tab in list(context.pages):
                with contextlib.suppress(Exception):
                    if "alterar-perfil" in tab.url and profile_tries < 5:
                        profile_tries += 1
                        self._choose_lawyer_profile(tab, dump=profile_tries == 1)
            portal = self._portal_tab(context)
            if portal is not None:
                with contextlib.suppress(Exception):
                    portal.wait_for_load_state("networkidle", timeout=20_000)
                self._page = portal
                # Se o aviso de sessão cobrir a tela antes de um clique do robô, responde antes.
                with contextlib.suppress(Exception):
                    portal.add_locator_handler(
                        portal.locator(_MODALS).filter(has_text=SESSION_PROMPT),
                        lambda _modal, tab=portal: keep_session(tab),
                        no_wait_after=True,
                    )
                return True
            if not notified and on_waiting is not None and time.monotonic() - started > 30:
                with contextlib.suppress(Exception):
                    on_waiting()
                notified = True
            try:
                page.wait_for_timeout(2_000)
            except Exception:
                time.sleep(2)
        return False

    def _choose_lawyer_profile(self, tab: Page, *, dump: bool = False) -> None:
        """Depois do login o Portal pede o perfil (tela `alterar-perfil`); antes era a pessoa
        quem clicava em "Advogado" (relato do operador, 30/09/2026). Escolhe esse perfil e
        confirma. Sem sucesso, grava a estrutura (sem conteúdo) para ajuste."""
        lawyer = re.compile(r"^\s*Advogad[oa]\b", re.I)
        tab.wait_for_timeout(1_500)
        for select in tab.locator("select:visible").all():
            with contextlib.suppress(Exception):
                labels = select.locator("option").all_inner_texts()
                choice = next((label for label in labels if lawyer.search(label)), None)
                if choice:
                    select.select_option(label=choice)
        if dump:
            # Estrutura da tela de perfil (sem conteúdo), na 1ª tentativa, para ajustes.
            with contextlib.suppress(Exception):
                from legal_monitor.connectors.eproc import EprocConnector

                self.diagnostics_dir.mkdir(parents=True, exist_ok=True)
                EprocConnector.dump_structure(
                    tab,
                    self.diagnostics_dir / f"portal-perfil-{time.strftime('%Y%m%d-%H%M%S')}.json",
                )

        def visible_lawyer() -> Any:
            for candidate in (
                tab.get_by_role("option", name=lawyer),
                tab.get_by_role("radio", name=lawyer),
                tab.get_by_text(lawyer),
            ):
                visible = candidate.filter(visible=True) if hasattr(candidate, "filter") else None
                if visible is not None and visible.count():
                    return visible.first
            return None

        # Tela real (estrutura gravada em 30/09/2026): janela "Trocar perfil" com a caixa
        # #dropdownPerfil; o clique no "quadrado" abre a lista .box-resultados; o botão verde
        # (.rodape-confirma, "Entrar") fica desabilitado até escolher o perfil.
        results = tab.locator("#dropdownPerfil .box-resultados").get_by_text(lawyer)
        if tab.locator("#dropdownPerfil").count():
            for selector in (
                "#dropdownPerfil input:visible",
                "#dropdownPerfil .ajustado-form:visible",
                "#dropdownPerfil .select-autocomplete:visible",
            ):
                if results.filter(visible=True).count():
                    break
                with contextlib.suppress(Exception):
                    target = tab.locator(selector)
                    if target.count():
                        target.first.click(timeout=5_000)
                        tab.wait_for_timeout(800)
            if not results.filter(visible=True).count():
                with contextlib.suppress(Exception):
                    typing = tab.locator("#dropdownPerfil input:visible")
                    if typing.count():
                        typing.first.press_sequentially("Advog", delay=60)
                        tab.wait_for_timeout(800)
            steps: list[str] = []
            # Só o "Entrar" visível da janela de perfil: o Portal tem outras janelas ocultas com o
            # mesmo botão verde (1º teste real, 01/10/2026: o clique ia para uma delas).
            enter = tab.locator(
                "app-trocar-perfil .modal-footer a:has(.rodape-confirma), "
                ".modal-footer a:has(.rodape-confirma)"
            ).filter(visible=True)

            def enter_enabled() -> bool:
                with contextlib.suppress(Exception):
                    return bool(enter.count()) and "isDisabled" not in (
                        enter.first.get_attribute("class") or ""
                    )
                return False

            def wait_enabled(seconds: float) -> bool:
                for _ in range(int(seconds / 0.3)):
                    if enter_enabled():
                        return True
                    tab.wait_for_timeout(300)
                return enter_enabled()

            with contextlib.suppress(Exception):
                visible = results.filter(visible=True)
                steps.append(f"opcoes_visiveis={visible.count()}")
                if visible.count():
                    visible.first.click(timeout=5_000)
                    steps.append("clicou_advogado")
                if not wait_enabled(6):
                    # A caixa autocompleta pode só registrar a escolha pelo teclado.
                    typing = tab.locator("#dropdownPerfil input:visible")
                    if typing.count():
                        typing.first.focus()
                        typing.first.press("ArrowDown")
                        typing.first.press("Enter")
                        steps.append("teclado_seta_enter")
                    if not wait_enabled(4) and visible.count():
                        visible.first.dispatch_event("mousedown")
                        visible.first.dispatch_event("mouseup")
                        visible.first.dispatch_event("click")
                        steps.append("eventos_mouse")
                enabled = wait_enabled(3)
                steps.append(f"entrar_habilitado={enabled}")
                if enter.count():
                    target = (
                        enter.first
                        if enabled
                        else tab.locator(".rodape-confirma").filter(visible=True).first
                    )
                    target.click(timeout=5_000, force=not enabled)
                    steps.append("clicou_entrar" if enabled else "clicou_entrar_forcado")
                tab.wait_for_timeout(2_500)
                steps.append(f"saiu_da_tela={'alterar-perfil' not in tab.url}")
            with contextlib.suppress(Exception):
                self.diagnostics_dir.mkdir(parents=True, exist_ok=True)
                (
                    self.diagnostics_dir
                    / f"portal-perfil-passos-{time.strftime('%Y%m%d-%H%M%S')}.txt"
                ).write_text("\n".join(steps), encoding="utf-8")
            if "alterar-perfil" not in tab.url:
                return

        option = visible_lawyer()
        if option is None:
            # A opção só aparece depois de abrir a lista de perfis (vídeo do operador).
            trigger = tab.locator(
                "p-dropdown:visible, .p-dropdown:visible, [role=combobox]:visible, "
                "mat-select:visible, .ng-select:visible, .dropdown-toggle:visible, "
                "button:has-text('Perfil'):visible, [aria-haspopup]:visible"
            )
            with contextlib.suppress(Exception):
                if trigger.count():
                    trigger.first.click(timeout=5_000)
                    tab.wait_for_timeout(800)
            option = visible_lawyer()
        with contextlib.suppress(Exception):
            if option is not None:
                option.click(timeout=5_000)
        confirm = tab.get_by_role(
            "button", name=re.compile(r"Confirmar|Selecionar|Continuar|Entrar|Acessar|Ok", re.I)
        )
        with contextlib.suppress(Exception):
            if confirm.count():
                confirm.first.click(timeout=5_000)
        tab.wait_for_timeout(2_000)

    @staticmethod
    def _portal_tab(context: BrowserContext) -> Page | None:
        for tab in reversed(context.pages):
            with contextlib.suppress(Exception):
                if tab.is_closed():
                    continue
                url = tab.url
                # "alterar-perfil" é passagem automática para o painel: esperar o painel, senão
                # o redirecionamento atropela a ida à consulta (1ª rodada real, 30/09/2026).
                if "/portalservicos/" in url and ("dashboard" in url or "consproc" in url):
                    return tab
        return None

    # --- consulta ----------------------------------------------------------------------
    def _consulta_frame(self, page: Page, timeout_s: int = 40) -> Frame:
        for _ in range(timeout_s):
            for frame in page.frames:
                if CONSULTA_FRAME in frame.url:
                    return frame
            page.wait_for_timeout(1_000)
        if "login" in page.url or "idserverjus" in page.url:
            raise AuthenticationRequired()
        raise ConnectorError(ErrorCode.PARSE_ERROR, "Quadro da consulta do Portal não carregou")

    def _search_form(self, page: Page) -> Frame:
        """Quadro da consulta com o formulário de pesquisa visível. Depois de um processo o
        quadro fica nos detalhes e o endereço da página não muda: volta pelo botão "Voltar"
        do próprio Portal ou, se não der, recarrega a consulta passando pelo painel."""
        for attempt in range(3):
            keep_session(page)
            if attempt == 2 or CONSULTA_FRAME not in "".join(f.url for f in page.frames):
                with contextlib.suppress(Exception):
                    page.goto(PORTAL_HOME, wait_until="domcontentloaded")
                    page.wait_for_timeout(2_000)
                page.goto(CONSULTA_URL, wait_until="domcontentloaded")
            frame = self._consulta_frame(page)
            with contextlib.suppress(Exception):
                frame.wait_for_load_state("networkidle", timeout=20_000)
            tab = frame.get_by_text("Por Número", exact=True)
            with contextlib.suppress(Exception):
                tab.first.wait_for(state="visible", timeout=10_000)
                return frame
            if attempt == 0:
                with contextlib.suppress(Exception):
                    frame.get_by_role("button", name=re.compile(r"^\s*Voltar", re.I)).first.click(
                        timeout=5_000
                    )
                    page.wait_for_timeout(2_000)
        raise ConnectorError(ErrorCode.PARSE_ERROR, "Formulário de consulta do Portal não abriu")

    def open_autos(self, context: BrowserContext, cnj: CnjNumber) -> Frame:
        page = self._page
        if page is None or page.is_closed():
            raise AuthenticationRequired()
        frame = self._search_form(page)
        try:
            frame.get_by_text("Por Número", exact=True).first.click(timeout=15_000)
            frame.get_by_text("Única", exact=True).first.click(timeout=10_000)
            area = (
                frame.locator("div")
                .filter(has_text=re.compile(r"N[uú]mero do processo"))
                .filter(has=frame.locator("input"))
                .last
            )
            inputs = area.locator("input[type='text']:visible, input:not([type]):visible")
            if inputs.count() < 2:
                raise ConnectorError(
                    ErrorCode.PARSE_ERROR, "Campos do número no Portal não reconhecidos"
                )
        except ConnectorError:
            raise
        except Exception as exc:
            raise ConnectorError(
                ErrorCode.PARSE_ERROR, "Formulário de consulta do Portal mudou"
            ) from exc
        digits = cnj.digits
        first = f"{digits[0:7]}-{digits[7:9]}.{digits[9:13]}"
        origin = digits[16:20]
        inputs.nth(0).click()
        inputs.nth(0).fill("")
        inputs.nth(0).press_sequentially(first, delay=40)
        inputs.nth(inputs.count() - 1).click()
        inputs.nth(inputs.count() - 1).fill("")
        inputs.nth(inputs.count() - 1).press_sequentially(origin, delay=40)
        frame.get_by_role("button", name=re.compile(r"Pesquisar", re.IGNORECASE)).first.click(
            timeout=10_000
        )
        # Resultado: detalhes direto, uma lista para escolher ou "não encontrado".
        for _ in range(45):
            page.wait_for_timeout(1_000)
            keep_session(page)
            if frame.locator("app-movimento, app-detalhes-processo").count():
                break
            link = frame.get_by_text(str(cnj), exact=False)
            if "detalhes" not in frame.url and link.count() and frame.locator("table").count():
                with contextlib.suppress(Exception):
                    link.first.click(timeout=5_000)
                continue
            body = ""
            with contextlib.suppress(Exception):
                body = frame.locator("body").inner_text(timeout=2_000)
            if NOT_FOUND_TEXT.search(body):
                raise ConnectorError(
                    ErrorCode.SOURCE_UNAVAILABLE, "Processo não encontrado nesta fonte"
                )
        else:
            raise ConnectorError(ErrorCode.PARSE_ERROR, "Detalhes do processo não abriram em 45 s")
        with contextlib.suppress(Exception):
            frame.wait_for_selector("app-movimento", timeout=30_000)
        keep_session(page)
        self._show_all_movements(frame)
        return frame

    @staticmethod
    def _show_all_movements(frame: Frame) -> None:
        """Os detalhes mostram só a "Última Movimentação"; o botão de leitura "Todos Os
        Movimentos" abre a lista completa (vídeo do operador, 30/09/2026)."""
        button = frame.get_by_role("button", name=re.compile(r"Todos\s+os\s+Movimentos", re.I))
        if not button.count():
            button = frame.get_by_text(re.compile(r"Todos\s+os\s+Movimentos", re.I))
        if not button.count():
            raise ConnectorError(
                ErrorCode.PARSE_ERROR, "Botão Todos Os Movimentos não encontrado no Portal"
            )
        before = frame.locator("app-movimento").count()
        button.first.click(timeout=10_000)
        stable, last = 0, -1
        for _ in range(30):
            frame.wait_for_timeout(500)
            count = frame.locator("app-movimento").count()
            stable = stable + 1 if count == last else 0
            last = count
            if count > before and stable >= 3:
                return
            if frame.locator("p-paginator").count() and stable >= 4:
                return

    def read_timeline(self, autos: Frame) -> tuple[TimelineItem, ...]:
        items: list[TimelineItem] = []
        seen_pages: set[str] = set()
        for page_no in range(1, MAX_PAGES + 1):
            keep_session(self._page)
            cards = autos.evaluate(_CARDS_JS)
            signature = "|".join(str(card.get("all", ""))[:80] for card in cards[:3])
            if signature in seen_pages:
                break
            seen_pages.add(signature)
            items += [item for card in cards if (item := item_from_card(card, page_no)) is not None]
            # A paginação dos movimentos é a que vem logo depois dos cartões (a janela de
            # personagens tem outra).
            paginator = autos.locator("xpath=(//app-movimento)[last()]/following::p-paginator[1]")
            next_button = paginator.locator("button.p-paginator-next")
            if not next_button.count() or "p-disabled" in (
                next_button.first.get_attribute("class") or ""
            ):
                break
            next_button.first.click(timeout=10_000)
            for _ in range(20):
                autos.wait_for_timeout(500)
                fresh = autos.evaluate(_CARDS_JS)
                if "|".join(str(c.get("all", ""))[:80] for c in fresh[:3]) != signature:
                    break
        if not items:
            raise ConnectorError(ErrorCode.PARSE_ERROR, "Movimentações do Portal não reconhecidas")
        return tuple(items)

    # --- peças -------------------------------------------------------------------------
    def _paginator(self, autos: Frame) -> Any:
        return autos.locator("xpath=(//app-movimento)[last()]/following::p-paginator[1]")

    def _go_to_page(self, autos: Frame, page_no: int) -> None:
        """Volta à página `page_no` da lista (a leitura terminou na última)."""

        def signature() -> str:
            return "|".join(str(c.get("all", ""))[:80] for c in autos.evaluate(_CARDS_JS)[:3])

        def click_and_wait(selector: str) -> bool:
            button = self._paginator(autos).locator(selector)
            if not button.count() or "p-disabled" in (button.first.get_attribute("class") or ""):
                return False
            before = signature()
            button.first.click(timeout=10_000)
            for _ in range(20):
                autos.wait_for_timeout(500)
                if signature() != before:
                    break
            return True

        click_and_wait("button.p-paginator-first")
        for _ in range(page_no - 1):
            if not click_and_wait("button.p-paginator-next"):
                break

    def download_document(
        self, context: BrowserContext, autos: Frame, document: TimelineDocument, target: Path
    ) -> Path:
        """Clica no controle de peça do cartão e captura o PDF por qualquer via: download,
        nova aba com PDF ou janela com PDF embutido. Nunca abre intimação/citação (o monitor
        já filtra por `documents_allowed`)."""
        try:
            _, page_text, key = (document.href or "").split(":", 2)
            page_no = int(page_text)
        except ValueError as exc:
            raise ConnectorError(ErrorCode.PARSE_ERROR, "Referência da peça do Portal") from exc
        keep_session(self._page)
        self._go_to_page(autos, page_no)
        cards = autos.evaluate(_CARDS_JS)
        card = next((c for c in cards if card_key(c) == key), None)
        if card is None:
            raise ConnectorError(ErrorCode.PARSE_ERROR, "Cartão da peça não reapareceu na lista")
        mark = next((d["mark"] for d in card.get("docs", []) if d["label"] == document.label), None)
        if mark is None:
            raise ConnectorError(ErrorCode.PARSE_ERROR, "Controle da peça sumiu do cartão")

        responses: list[Any] = []
        downloads: list[Any] = []
        pages_before = set(context.pages)

        def on_response(response: Any) -> None:
            responses.append(response)  # o corpo é lido fora do evento (API síncrona)

        def on_download(download: Any) -> None:
            downloads.append(download)

        def on_page(tab: Any) -> None:
            tab.on("download", on_download)

        portal = self._page
        context.on("response", on_response)
        context.on("page", on_page)
        if portal is not None:
            portal.on("download", on_download)
        control = autos.locator(f"[data-lcf-doc='{mark}']").first
        clicked = _describe_control(control)
        try:
            control.click(timeout=10_000)
            deadline = time.monotonic() + DOWNLOAD_TIMEOUT_S
            checked = 0
            while time.monotonic() < deadline:
                (portal or autos.page).wait_for_timeout(500)
                if downloads:
                    downloads[0].save_as(str(target))
                    return target
                while checked < len(responses):
                    data = _pdf_from_response(responses[checked], context)
                    checked += 1
                    if data:
                        target.write_bytes(data)
                        return target
                for tab in set(context.pages) - pages_before:
                    with contextlib.suppress(Exception):
                        if tab.url.startswith("blob:"):
                            # Aba blob: com o PDF; o endereço é da mesma origem do quadro.
                            data = base64.b64decode(autos.evaluate(_BLOB_JS, tab.url))
                            if data.startswith(b"%PDF"):
                                target.write_bytes(data)
                                return target
                embedded = self._embedded_pdf(context)
                if embedded:
                    target.write_bytes(embedded)
                    return target
            report = self._download_report(context, pages_before, responses, clicked)
            raise ConnectorError(
                ErrorCode.PARSE_ERROR,
                f"Portal: nenhum PDF recebido ao abrir '{document.label[:40]}'"
                + (f" | diagnóstico: {report}" if report else ""),
            )
        finally:
            with contextlib.suppress(Exception):
                context.remove_listener("response", on_response)
                context.remove_listener("page", on_page)
                if portal is not None:
                    portal.remove_listener("download", on_download)
            for tab in set(context.pages) - pages_before:
                with contextlib.suppress(Exception):
                    tab.close()
            # Fecha a janela da peça, se abriu sobre a lista.
            with contextlib.suppress(Exception):
                (portal or autos.page).keyboard.press("Escape")

    def _download_report(
        self, context: BrowserContext, pages_before: set[Any], responses: list[Any], clicked: dict
    ) -> str:
        """Diagnóstico sem conteúdo do clique na peça: controle, abas e respostas mascaradas."""
        with contextlib.suppress(Exception):
            portal = self._page
            report = {
                "controle": clicked,
                "abas_novas": [_mask_url(t.url) for t in set(context.pages) - pages_before],
                "quadros": [_mask_url(f.url) for f in portal.frames] if portal else [],
                "respostas": [
                    f"{r.status} {(r.headers or {}).get('content-type', '')[:40]} "
                    f"{r.request.resource_type} {_mask_url(r.url)}"
                    for r in responses[:80]
                ],
            }
            self.diagnostics_dir.mkdir(parents=True, exist_ok=True)
            path = self.diagnostics_dir / f"portal-peca-{time.strftime('%Y%m%d-%H%M%S')}.json"
            path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            return str(path)
        return ""

    @staticmethod
    def _embedded_pdf(context: BrowserContext) -> bytes | None:
        """PDF exibido num iframe/embed/object (inclusive endereço blob:) após o clique."""
        for tab in context.pages:
            for frame in tab.frames:
                if not frame.url.startswith(("http", "about:")):
                    continue  # visualizador interno do Chrome (chrome-extension://)
                with contextlib.suppress(Exception):
                    sources = frame.evaluate(
                        "() => [...document.querySelectorAll('iframe, embed, object')]"
                        ".map(e => e.src || e.data || '')"
                        ".filter(s => /^blob:|^https?:.*pdf/i.test(s))"
                    )
                    for source in sources:
                        if source.startswith("blob:"):
                            data = base64.b64decode(frame.evaluate(_BLOB_JS, source))
                        else:
                            response = context.request.get(source, timeout=60_000)
                            data = response.body() if response.ok else b""
                        if data.startswith(b"%PDF"):
                            return data
        return None
