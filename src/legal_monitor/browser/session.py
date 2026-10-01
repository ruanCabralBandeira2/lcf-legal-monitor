from __future__ import annotations

import contextlib
import json
import os
import re
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

from legal_monitor.connectors.routing import SourceEndpoint
from legal_monitor.domain.enums import SessionState

try:
    from playwright.sync_api import Error as PlaywrightError
except ImportError:  # Playwright é opcional (extra "browser").

    class PlaywrightError(Exception):  # type: ignore[no-redef]
        pass


if TYPE_CHECKING:
    from playwright.sync_api import BrowserContext, Page

NAVIGATION_TIMEOUT_MS = 45_000
CAPTCHA_SELECTOR = (
    "iframe[src*='recaptcha'], iframe[src*='hcaptcha'], iframe[src*='turnstile'], "
    ".g-recaptcha, .h-captcha"
)
STALE_LOGIN_COOKIES = (
    "KC_RESTART",
    "OAuth_Token_Request_State",
    "AUTH_SESSION_ID",
    "AUTH_SESSION_ID_LEGACY",
)
PASSWORD_SELECTOR = "input[type='password']"  # noqa: S105 - seletor CSS, não é senha.


class BrowserUnavailableError(RuntimeError):
    """Playwright ou o navegador não estão instalados neste host."""


LOGIN_REFUSED = re.compile(
    r"invalid user|authentication.{0,3}s failed|usu[aá]rio inv[aá]lido|usu[aá]rio n[aã]o "
    r"(?:cadastrado|encontrado)|certificado (?:inv[aá]lido|n[aã]o cadastrado|revogado)",
    re.IGNORECASE,
)


def _login_refusal(page: Page) -> str:
    """Mensagem de recusa do site de login (texto da tela de erro do SSO, não do processo)."""
    try:
        text = page.locator("body").inner_text(timeout=2_000)
    except Exception:
        return ""
    if LOGIN_REFUSED.search(text):
        return (
            "O site recusou o login: o usuário do certificado não está cadastrado ou não é "
            "aceito neste tribunal. É preciso fazer o cadastro/credenciamento no próprio site."
        )
    return ""


CDP_QUEUE_SECONDS = 50 * 60

# Sites do PJe que conversam com o PJeOffice no próprio Mac (localhost). Sem a permissão
# "acessar apps deste dispositivo", o Chrome pergunta em toda rodada, porque cada rodada usa
# um contexto limpo (relato do operador, 01/10/2026). Só estes endereços recebem a permissão.
PJE_LOCAL_APP_ORIGINS = (
    "https://sso.cloud.pje.jus.br",
    "https://tjrj.pje.jus.br",
    "https://pje.trt1.jus.br",
)


def allow_local_apps(context: Any, endpoint: SourceEndpoint) -> None:
    """Libera o PJeOffice (localhost) só para os sites oficiais do PJe."""
    if endpoint.system.value != "PJE":
        return
    origins = {*PJE_LOCAL_APP_ORIGINS, f"https://{endpoint.host}"}
    for origin in sorted(origins):
        with contextlib.suppress(Exception):
            context.grant_permissions(["local-network-access"], origin=origin)


@contextlib.contextmanager
def _exclusive_lock(path: Path, wait_seconds: float, poll_seconds: float = 2.0) -> Iterator[None]:
    """Espera a vez de usar o Chrome do robô; o sistema libera a trava se o processo morrer."""
    import fcntl

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as handle:
        deadline = time.monotonic() + wait_seconds
        while True:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    minutes = int(wait_seconds // 60)
                    raise BrowserUnavailableError(
                        f"Chrome do robô ocupado por outro robô há mais de {minutes} min"
                    ) from None
                time.sleep(poll_seconds)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def minimize_window(page: Any) -> None:
    """Minimiza a janela da página no Chrome do robô (não pula na tela de quem usa o Mac)."""
    with contextlib.suppress(Exception):
        session = page.context.new_cdp_session(page)
        window = session.send("Browser.getWindowForTarget")
        session.send(
            "Browser.setWindowBounds",
            {"windowId": window["windowId"], "bounds": {"windowState": "minimized"}},
        )
        session.detach()


def _host_path(url: str) -> str:
    parsed = urlparse(url)
    return f"{parsed.hostname or ''}{parsed.path}"


# Páginas que existem só para quem NÃO está logado (eproc: controlador externo; PJe: login).
LOGGED_OUT_PATHS = ("externo_controlador", "login.seam", "idserverjus-front")


def classify_session(
    *,
    final_url: str,
    expected_host: str,
    has_password_field: bool,
    has_captcha: bool,
    has_logged_in_marker: bool | None = None,
) -> SessionState:
    """Regra conservadora: qualquer sinal de login ou desafio nunca vira sessão válida.

    `has_logged_in_marker` (quando a fonte define um marcador) exige prova positiva de
    sessão: no eproc, a busca rápida ou o link "Encerrar Sessão", que só existem logado.
    """
    if has_captcha:
        return SessionState.CAPTCHA_REQUIRED
    parsed = urlparse(final_url)
    host = parsed.hostname or ""
    if host != expected_host or "sso" in host or has_password_field:
        return SessionState.AUTH_REQUIRED
    if any(marker in parsed.path for marker in LOGGED_OUT_PATHS):
        return SessionState.AUTH_REQUIRED
    if has_logged_in_marker is False:
        return SessionState.AUTH_REQUIRED
    return SessionState.VALID


@dataclass(frozen=True, slots=True)
class SessionCheck:
    source: str
    state: SessionState
    final_host: str
    # Motivo legível quando o site recusou o login (ex.: certificado sem cadastro).
    detail: str = ""


class BrowserSessionManager:
    """Sessões humanas reaproveitadas pelo robô.

    O login e o 2FA são feitos sempre por uma pessoa em janela visível (`open_for_login`).
    O robô só reutiliza o estado salvo e nunca digita senha ou código.
    """

    def __init__(
        self,
        profile_root: Path,
        *,
        headless: bool = True,
        channel: str = "",
        visible_for_blocked: bool = False,
        cdp_url: str = "",
        minimize: bool = True,
    ) -> None:
        self._root = profile_root.resolve()
        # Chrome do robô sempre aberto (ideia A): conectar em vez de abrir um Chrome novo,
        # porque o macOS guarda o PIN do token por processo do Chrome.
        self._cdp_url = cdp_url
        self._minimize = minimize
        self._headless = headless
        # Autorizado pelo operador em 28/09/2026: fontes que recusam headless usam janela
        # visível do navegador comum. Nunca técnicas antifingerprint ou de evasão.
        self._visible_for_blocked = visible_for_blocked
        self.last_trace_path: Path | None = None
        # "chrome" usa o Google Chrome instalado, que enxerga o certificado do token USB
        # pelo repositório do sistema. Vazio = Chromium do Playwright.
        self._channel = channel

    def state_path(self, endpoint: SourceEndpoint) -> Path:
        return self._root / endpoint.auth_realm / "storage_state.json"

    def headless_for(self, endpoint: SourceEndpoint) -> bool:
        if endpoint.headless_blocked and self._visible_for_blocked:
            return False
        return self._headless

    def has_saved_state(self, endpoint: SourceEndpoint) -> bool:
        return self.state_path(endpoint).is_file()

    @contextlib.contextmanager
    def context(
        self,
        endpoint: SourceEndpoint,
        *,
        headless: bool | None = None,
        minimize: bool | None = None,
    ) -> Iterator[BrowserContext]:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            raise BrowserUnavailableError(
                "Playwright não instalado; rode: pip install -e .[browser] e "
                "python -m playwright install chromium"
            ) from None
        state_path = self.state_path(endpoint)
        state_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        options: dict[str, Any] = {
            "locale": "pt-BR",
            "timezone_id": "America/Sao_Paulo",
            "accept_downloads": True,
        }
        if state_path.is_file():
            options["storage_state"] = str(state_path)
        with sync_playwright() as playwright:
            if self._cdp_url:
                # Fila: um robô por vez no Chrome do robô (01/10/2026). Com dois clientes
                # conectados, cada janela nova espera os dois a liberarem; um robô ocupado
                # fora do navegador congelava as janelas do outro (TRF2/TRF4, PJe).
                with _exclusive_lock(self._root / "chrome-robo-uso.lock", CDP_QUEUE_SECONDS):
                    yield from self._cdp_context(
                        playwright,
                        options,
                        state_path,
                        self._minimize if minimize is None else minimize,
                        endpoint,
                    )
                return
            launch: dict[str, Any] = {"headless": self._headless if headless is None else headless}
            if self._channel:
                launch["channel"] = self._channel
            browser = playwright.chromium.launch(**launch)
            try:
                context = browser.new_context(**options)
                context.set_default_navigation_timeout(NAVIGATION_TIMEOUT_MS)
                allow_local_apps(context, endpoint)
                try:
                    yield context
                finally:
                    # Se a pessoa fechou a janela, o navegador já morreu: salvar/fechar de novo
                    # travava o programa para sempre (casos de 28/09/2026 no PJe e no TRF4).
                    if browser.is_connected():
                        self._save_state(context, state_path)
                        with contextlib.suppress(PlaywrightError):
                            context.close()
            finally:
                if browser.is_connected():
                    with contextlib.suppress(PlaywrightError):
                        browser.close()

    def _cdp_context(
        self,
        playwright: Any,
        options: dict[str, Any],
        state_path: Path,
        minimize: bool,
        endpoint: SourceEndpoint,
    ) -> Iterator[BrowserContext]:
        """Contexto isolado (cookies próprios) dentro do Chrome do robô já aberto. Só o
        contexto é fechado no fim: o Chrome continua aberto com o token desbloqueado."""
        try:
            browser = playwright.chromium.connect_over_cdp(self._cdp_url, timeout=15_000)
        except PlaywrightError as exc:
            raise BrowserUnavailableError(
                "Chrome do robô não está aberto (ops/launchd/registrar-robos.sh)"
            ) from exc
        context = browser.new_context(**options)
        context.set_default_navigation_timeout(NAVIGATION_TIMEOUT_MS)
        allow_local_apps(context, endpoint)
        if minimize:
            context.on("page", minimize_window)
        try:
            yield context
        finally:
            if browser.is_connected():
                self._save_state(context, state_path, cookies_only=True)
                with contextlib.suppress(PlaywrightError):
                    context.close()

    def login(
        self,
        endpoint: SourceEndpoint,
        *,
        click_certificate: bool,
        on_waiting_approval: Callable[[], None],
        timeout_seconds: int = 600,
        notify_after_seconds: int = 20,
        poll_seconds: float = 3.0,
        visible: bool = True,
    ) -> SessionCheck:
        """Login em janela visível pela opção oficial de certificado (token USB).

        O robô apenas clica no botão público "Certificado Digital". Seleção do certificado,
        PIN do token e aprovação do 2FA no celular ficam com a pessoa. Se a sessão não ficar
        válida em `notify_after_seconds`, `on_waiting_approval` é chamado uma única vez.
        """
        # Login com gente (2FA, "Não usar o 2FA neste dispositivo") precisa da janela à vista.
        with self.context(endpoint, headless=False, minimize=not visible) as context:
            # Cookies de "login em andamento" de tentativas interrompidas fazem o SSO
            # recusar a próxima tentativa. A sessão já estabelecida (KEYCLOAK_IDENTITY,
            # cookies do eproc) é preservada.
            for name in STALE_LOGIN_COOKIES:
                with contextlib.suppress(PlaywrightError):
                    context.clear_cookies(name=name)
            self._trace(context, endpoint)
            page = context.pages[0] if context.pages else context.new_page()
            page.goto(endpoint.base_url, wait_until="domcontentloaded")
            if click_certificate and endpoint.certificate_login_selector:
                with contextlib.suppress(Exception):
                    page.wait_for_selector(endpoint.certificate_login_selector, timeout=15_000)
                    page.locator(endpoint.certificate_login_selector).first.click(timeout=10_000)
            elif click_certificate and endpoint.certificate_login_label:
                with contextlib.suppress(Exception):
                    page.get_by_text(endpoint.certificate_login_label, exact=False).first.click(
                        timeout=10_000
                    )
            started = time.monotonic()
            notified = False
            reopened = False
            check = SessionCheck(endpoint.key, SessionState.AUTH_REQUIRED, "")
            while time.monotonic() - started < timeout_seconds:
                # O login por certificado abre e fecha janelas auxiliares (permissão do
                # navegador, PJeOffice, popups do SSO). Qualquer aba pode sumir a qualquer
                # momento; olhamos todas as abertas e nunca dependemos de uma só.
                try:
                    pages = [item for item in context.pages if not item.is_closed()]
                except PlaywrightError:
                    return check  # navegador inteiro fechado pela pessoa
                if not pages:
                    # A aba principal fechou; os cookies podem já estar gravados. Reabre UMA
                    # vez (fluxo do PJe); se fechar de novo, a pessoa desistiu.
                    if reopened:
                        return check
                    reopened = True
                    try:
                        page = context.new_page()
                        page.goto(endpoint.base_url, wait_until="domcontentloaded")
                        pages = [page]
                    except PlaywrightError:
                        return check
                for active in reversed(pages):
                    try:
                        current = self._inspect(active, endpoint, settle=False)
                    except PlaywrightError:
                        continue  # aba fechando ou no meio de uma navegação
                    if current.state is SessionState.VALID:
                        return current
                    check = current
                    refusal = _login_refusal(active)
                    if refusal:
                        # O site recusou o login (ex.: certificado sem cadastro): esperar não
                        # adianta; para e explica.
                        return SessionCheck(
                            endpoint.key, SessionState.AUTH_REQUIRED, current.final_host, refusal
                        )
                if not notified and time.monotonic() - started >= notify_after_seconds:
                    on_waiting_approval()
                    notified = True
                try:
                    pages[0].wait_for_timeout(int(poll_seconds * 1000))
                except PlaywrightError:
                    time.sleep(poll_seconds)
            return check

    def _trace(self, context: BrowserContext, endpoint: SourceEndpoint) -> None:
        """Registro de diagnóstico do login: só host e caminho, nunca query, texto ou cookie."""
        log_path = self._root / f"login-trace-{endpoint.key}.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        stream = log_path.open("w", encoding="utf-8")
        self.last_trace_path = log_path

        def write(event: str, detail: str = "") -> None:
            stamp = time.strftime("%H:%M:%S")
            with contextlib.suppress(ValueError):
                stream.write(f"{stamp} {event} {detail}\n")
                stream.flush()

        def attach(page: Page) -> None:
            write("aba-aberta")
            page.on(
                "framenavigated",
                lambda frame: frame == page.main_frame and write("navegou", _host_path(frame.url)),
            )
            page.on("close", lambda _page: write("aba-fechada"))
            page.on("crash", lambda _page: write("aba-travou"))

        context.on("page", attach)
        context.on("close", lambda _context: (write("navegador-fechado"), stream.close()))
        for existing in context.pages:
            attach(existing)

    def check(self, endpoint: SourceEndpoint) -> SessionCheck:
        if not self.has_saved_state(endpoint):
            return SessionCheck(endpoint.key, SessionState.AUTH_REQUIRED, "")
        headless = self.headless_for(endpoint)
        if headless and endpoint.headless_blocked:
            # A fonte recusa navegador sem janela e o modo visível não foi autorizado.
            return SessionCheck(endpoint.key, SessionState.UNAVAILABLE, "headless-blocked")
        try:
            with self.context(endpoint, headless=headless) as context:
                page = context.new_page()
                page.goto(endpoint.base_url, wait_until="domcontentloaded")
                return self._inspect(page, endpoint)
        except BrowserUnavailableError:
            raise
        except Exception:
            return SessionCheck(endpoint.key, SessionState.UNAVAILABLE, "")

    @staticmethod
    def _inspect(page: Page, endpoint: SourceEndpoint, *, settle: bool = True) -> SessionCheck:
        if settle:
            with contextlib.suppress(Exception):
                page.wait_for_load_state("networkidle", timeout=15_000)
        final_url = page.url
        marker = (
            page.locator(endpoint.logged_in_selector).count() > 0
            if endpoint.logged_in_selector
            else None
        )
        state = classify_session(
            final_url=final_url,
            expected_host=endpoint.host,
            has_password_field=page.locator(PASSWORD_SELECTOR).count() > 0,
            has_captcha=page.locator(CAPTCHA_SELECTOR).count() > 0,
            has_logged_in_marker=marker,
        )
        return SessionCheck(endpoint.key, state, urlparse(final_url).hostname or "")

    @staticmethod
    def _save_state(
        context: BrowserContext, state_path: Path, *, cookies_only: bool = False
    ) -> None:
        temporary = state_path.with_suffix(".tmp")
        try:
            if cookies_only:
                # Chrome do robô (CDP): storage_state() ficou preso para sempre em 01/10/2026
                # (TRF2/TRF4). Cookies bastam para as sessões e para o "Não usar o 2FA neste
                # dispositivo"; o localStorage salvo antes é preservado.
                origins: list[Any] = []
                with contextlib.suppress(OSError, ValueError):
                    origins = json.loads(state_path.read_text(encoding="utf-8")).get("origins", [])
                temporary.write_text(
                    json.dumps({"cookies": context.cookies(), "origins": origins}),
                    encoding="utf-8",
                )
            else:
                context.storage_state(path=str(temporary))
        except PlaywrightError:
            return  # navegador já fechado: mantém o último estado salvo
        os.chmod(temporary, 0o600)
        os.replace(temporary, state_path)
