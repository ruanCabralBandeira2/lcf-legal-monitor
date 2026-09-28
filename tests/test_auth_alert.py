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
