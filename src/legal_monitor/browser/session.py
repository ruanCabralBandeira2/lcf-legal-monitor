from __future__ import annotations

import contextlib
import os
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

from legal_monitor.connectors.routing import SourceEndpoint
from legal_monitor.domain.enums import SessionState

if TYPE_CHECKING:
    from playwright.sync_api import BrowserContext, Page

NAVIGATION_TIMEOUT_MS = 45_000
CAPTCHA_SELECTOR = (
    "iframe[src*='recaptcha'], iframe[src*='hcaptcha'], iframe[src*='turnstile'], "
    ".g-recaptcha, .h-captcha"
)
PASSWORD_SELECTOR = "input[type='password']"  # noqa: S105 - seletor CSS, não é senha.


class BrowserUnavailableError(RuntimeError):
    """Playwright ou o navegador não estão instalados neste host."""


def classify_session(
    *, final_url: str, expected_host: str, has_password_field: bool, has_captcha: bool
) -> SessionState:
    """Regra conservadora: qualquer sinal de login ou desafio nunca vira sessão válida."""
    if has_captcha:
        return SessionState.CAPTCHA_REQUIRED
    host = urlparse(final_url).hostname or ""
    if host != expected_host or "sso" in host or has_password_field:
        return SessionState.AUTH_REQUIRED
    return SessionState.VALID


@dataclass(frozen=True, slots=True)
class SessionCheck:
    source: str
    state: SessionState
    final_host: str


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
    ) -> None:
        self._root = profile_root.resolve()
        self._headless = headless
        # Autorizado pelo operador em 28/09/2026: fontes que recusam headless usam janela
        # visível do navegador comum. Nunca técnicas antifingerprint ou de evasão.
        self._visible_for_blocked = visible_for_blocked
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
        self, endpoint: SourceEndpoint, *, headless: bool | None = None
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
        with sync_playwright() as playwright:
            launch: dict[str, Any] = {"headless": self._headless if headless is None else headless}
            if self._channel:
                launch["channel"] = self._channel
            browser = playwright.chromium.launch(**launch)
            try:
                options: dict[str, Any] = {
                    "locale": "pt-BR",
                    "timezone_id": "America/Sao_Paulo",
                    "accept_downloads": True,
                }
                if state_path.is_file():
                    options["storage_state"] = str(state_path)
                context = browser.new_context(**options)
                context.set_default_navigation_timeout(NAVIGATION_TIMEOUT_MS)
                try:
                    yield context
                finally:
                    self._save_state(context, state_path)
                    context.close()
            finally:
                browser.close()

    def login(
        self,
        endpoint: SourceEndpoint,
        *,
        click_certificate: bool,
        on_waiting_approval: Callable[[], None],
        timeout_seconds: int = 600,
        notify_after_seconds: int = 20,
        poll_seconds: float = 3.0,
    ) -> SessionCheck:
        """Login em janela visível pela opção oficial de certificado (token USB).

        O robô apenas clica no botão público "Certificado Digital". Seleção do certificado,
        PIN do token e aprovação do 2FA no celular ficam com a pessoa. Se a sessão não ficar
        válida em `notify_after_seconds`, `on_waiting_approval` é chamado uma única vez.
        """
        with self.context(endpoint, headless=False) as context:
            page = context.pages[0] if context.pages else context.new_page()
            page.goto(endpoint.base_url, wait_until="domcontentloaded")
            if click_certificate and endpoint.certificate_login_label:
                with contextlib.suppress(Exception):
                    page.get_by_text(endpoint.certificate_login_label, exact=False).first.click(
                        timeout=10_000
                    )
            started = time.monotonic()
            notified = False
            check = SessionCheck(endpoint.key, SessionState.AUTH_REQUIRED, "")
            while time.monotonic() - started < timeout_seconds:
                active = context.pages[-1] if context.pages else page
                check = self._inspect(active, endpoint, settle=False)
                if check.state is SessionState.VALID:
                    return check
                if not notified and time.monotonic() - started >= notify_after_seconds:
                    on_waiting_approval()
                    notified = True
                active.wait_for_timeout(int(poll_seconds * 1000))
            return check

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
        state = classify_session(
            final_url=final_url,
            expected_host=endpoint.host,
            has_password_field=page.locator(PASSWORD_SELECTOR).count() > 0,
            has_captcha=page.locator(CAPTCHA_SELECTOR).count() > 0,
        )
        return SessionCheck(endpoint.key, state, urlparse(final_url).hostname or "")

    @staticmethod
    def _save_state(context: BrowserContext, state_path: Path) -> None:
        temporary = state_path.with_suffix(".tmp")
        context.storage_state(path=str(temporary))
        os.chmod(temporary, 0o600)
        os.replace(temporary, state_path)
