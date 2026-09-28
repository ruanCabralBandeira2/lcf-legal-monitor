from __future__ import annotations

import unittest
from datetime import UTC, datetime

from legal_monitor.browser.session import classify_session
from legal_monitor.connectors.routing import CATALOG
from legal_monitor.domain.enums import SessionState
from legal_monitor.monitoring.auth_alert import AuthAlertService, build_approval_message
from legal_monitor.monitoring.repository import MemoryManualActionStore
from legal_monitor.notifications.base import NotificationMessage, NotificationReceipt

NOW = datetime(2026, 9, 28, 12, tzinfo=UTC)


class RecordingNotifier:
    def __init__(self) -> None:
        self.sent: list[NotificationMessage] = []

    def send(self, message: NotificationMessage) -> NotificationReceipt:
        self.sent.append(message)
        return NotificationReceipt(channel="TEST", provider_id=None, accepted=True)


class ClassifySessionTests(unittest.TestCase):
    def test_redirect_to_sso_means_auth_required(self) -> None:
        state = classify_session(
            final_url="https://eproc-sso.tjrj.jus.br/realms/eproc/protocol/openid-connect/auth",
            expected_host="eproc1g.tjrj.jus.br",
            has_password_field=True,
            has_captcha=False,
        )
        self.assertIs(state, SessionState.AUTH_REQUIRED)

    def test_password_field_on_expected_host_is_not_valid(self) -> None:
        state = classify_session(
            final_url="https://eproc.trf2.jus.br/eproc/",
            expected_host="eproc.trf2.jus.br",
            has_password_field=True,
            has_captcha=False,
        )
        self.assertIs(state, SessionState.AUTH_REQUIRED)

    def test_captcha_wins(self) -> None:
        state = classify_session(
            final_url="https://eproc.trf2.jus.br/eproc/",
            expected_host="eproc.trf2.jus.br",
            has_password_field=False,
            has_captcha=True,
        )
        self.assertIs(state, SessionState.CAPTCHA_REQUIRED)

    def test_logged_page_is_valid(self) -> None:
        state = classify_session(
            final_url="https://eproc1g.tjrj.jus.br/eproc/controlador.php?acao=painel",
            expected_host="eproc1g.tjrj.jus.br",
            has_password_field=False,
            has_captcha=False,
        )
        self.assertIs(state, SessionState.VALID)


class LoggedOutPagesTests(unittest.TestCase):
    def test_eproc_external_controller_is_never_a_valid_session(self) -> None:
        # Caso real de 28/09/2026: a tela de login da JFRJ foi tomada por sessão válida.
        state = classify_session(
            final_url="https://eproc.jfrj.jus.br/eproc/externo_controlador.php",
            expected_host="eproc.jfrj.jus.br",
            has_password_field=False,
            has_captcha=False,
        )
        self.assertIs(state, SessionState.AUTH_REQUIRED)

    def test_marker_is_required_when_source_defines_it(self) -> None:
        common = {
            "final_url": "https://eproc.jfrj.jus.br/eproc/controlador.php?acao=painel",
            "expected_host": "eproc.jfrj.jus.br",
            "has_password_field": False,
            "has_captcha": False,
        }
        self.assertIs(
            classify_session(**common, has_logged_in_marker=False), SessionState.AUTH_REQUIRED
        )
        self.assertIs(classify_session(**common, has_logged_in_marker=True), SessionState.VALID)

    def test_every_eproc_source_has_logged_in_marker(self) -> None:
        for endpoint in CATALOG.values():
            if endpoint.system.value == "EPROC":
                self.assertIn("txtNumProcessoPesquisaRapida", endpoint.logged_in_selector or "")


class VisibleWindowPolicyTests(unittest.TestCase):
    def test_blocked_source_uses_visible_window_only_when_authorized(self) -> None:
        from pathlib import Path

        from legal_monitor.browser.session import BrowserSessionManager

        pje = CATALOG["pje-tjrj-1g"]
        eproc = CATALOG["eproc-tjrj-1g"]
        default = BrowserSessionManager(Path("x"), headless=True)
        allowed = BrowserSessionManager(Path("x"), headless=True, visible_for_blocked=True)
        self.assertTrue(default.headless_for(pje))
        self.assertFalse(allowed.headless_for(pje))
        self.assertTrue(allowed.headless_for(eproc))


class AuthAlertServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store = MemoryManualActionStore()
        self.notifier = RecordingNotifier()
        self.service = AuthAlertService(self.store, self.notifier)
        self.endpoint = CATALOG["eproc-tjrj-1g"]

    def test_notifies_once_per_open_action(self) -> None:
        first = self.service.handle(self.endpoint, SessionState.AUTH_REQUIRED, now=NOW)
        second = self.service.handle(self.endpoint, SessionState.AUTH_REQUIRED, now=NOW)
        self.assertTrue(first.notified)
        self.assertFalse(second.notified)
        self.assertEqual(len(self.notifier.sent), 1)
        body = self.notifier.sent[0].body
        self.assertIn("legal-monitor auth-open eproc-tjrj-1g", body)
        self.assertIn("celular", body)

    def test_valid_session_resolves_and_rearms(self) -> None:
        self.service.handle(self.endpoint, SessionState.AUTH_REQUIRED, now=NOW)
        resolved = self.service.handle(self.endpoint, SessionState.VALID, now=NOW)
        self.assertEqual(resolved.resolved_actions, 1)
        again = self.service.handle(self.endpoint, SessionState.AUTH_REQUIRED, now=NOW)
        self.assertTrue(again.notified)

    def test_unavailable_source_does_not_ask_for_login(self) -> None:
        outcome = self.service.handle(self.endpoint, SessionState.UNAVAILABLE, now=NOW)
        self.assertFalse(outcome.notified)
        self.assertEqual(self.notifier.sent, [])

    def test_approval_message_never_asks_for_code(self) -> None:
        message = build_approval_message(self.endpoint, "c-1")
        self.assertIn("aprove", message.body.lower())
        self.assertNotIn("envie o código", message.body.lower())


if __name__ == "__main__":
    unittest.main()


class LoginRefusalTests(unittest.TestCase):
    def test_recognizes_sso_refusal_messages(self) -> None:
        from legal_monitor.browser.session import LOGIN_REFUSED

        self.assertTrue(LOGIN_REFUSED.search("X509 certificate authentication's failed."))
        self.assertTrue(LOGIN_REFUSED.search("Invalid user"))
        self.assertTrue(LOGIN_REFUSED.search("Usuário não cadastrado no sistema"))
        self.assertFalse(LOGIN_REFUSED.search("Painel do Advogado"))


class TjrjPortalLoginPageTests(unittest.TestCase):
    def test_idserverjus_login_page_is_not_a_session(self) -> None:
        state = classify_session(
            final_url="https://www3.tjrj.jus.br/idserverjus-front/#/login?sgSist=PORTALSERVICOS",
            expected_host="www3.tjrj.jus.br",
            has_password_field=False,
            has_captcha=False,
        )
        self.assertIs(state, SessionState.AUTH_REQUIRED)
