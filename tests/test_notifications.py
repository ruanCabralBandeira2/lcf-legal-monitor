from __future__ import annotations

import unittest
from typing import Any

from legal_monitor.notifications.base import NotificationMessage
from legal_monitor.notifications.discord import (
    DiscordNotificationError,
    DiscordWebhookNotifier,
    JsonResponse,
)
from legal_monitor.notifications.fake import FakeNotifier


class RecordingTransport:
    def __init__(self, *, status: int = 200, provider_id: str = "message-123") -> None:
        self.status = status
        self.provider_id = provider_id
        self.url: str | None = None
        self.payload: dict[str, Any] | None = None
        self.timeout: float | None = None

    def post(self, url: str, payload: dict[str, Any], *, timeout: float) -> JsonResponse:
        self.url = url
        self.payload = payload
        self.timeout = timeout
        return JsonResponse(status=self.status, payload={"id": self.provider_id})


def _demo_message() -> NotificationMessage:
    return NotificationMessage(
        title="Prova técnica",
        body="Fixture sem dado processual real.",
        correlation_id="test-001",
        demo_only=True,
    )


class NotificationTests(unittest.TestCase):
    def test_fake_notifier_records_demo_without_network(self) -> None:
        notifier = FakeNotifier()
        receipt = notifier.send(_demo_message())

        self.assertTrue(receipt.accepted)
        self.assertEqual(receipt.channel, "FAKE")
        self.assertEqual(len(notifier.messages), 1)

    def test_discord_payload_disables_mentions_and_requests_confirmation(self) -> None:
        transport = RecordingTransport()
        notifier = DiscordWebhookNotifier(
            "https://discord.com/api/webhooks/123456/token-ficticio",
            transport=transport,
        )

        receipt = notifier.send(_demo_message())

        self.assertTrue(receipt.accepted)
        self.assertEqual(receipt.provider_id, "message-123")
        self.assertIsNotNone(transport.url)
        self.assertIn("wait=true", transport.url or "")
        self.assertEqual(transport.payload["allowed_mentions"], {"parse": []})

    def test_discord_rejects_non_official_or_non_https_url(self) -> None:
        for value in (
            "http://discord.com/api/webhooks/123/token",
            "https://example.com/api/webhooks/123/token",
            "https://discord.com/not-a-webhook/123/token",
        ):
            with self.subTest(value=value), self.assertRaises(DiscordNotificationError):
                DiscordWebhookNotifier(value)

    def test_discord_rejects_real_message_in_demo_adapter(self) -> None:
        notifier = DiscordWebhookNotifier(
            "https://discord.com/api/webhooks/123456/token-ficticio",
            transport=RecordingTransport(),
        )
        message = NotificationMessage(
            title="Mensagem",
            body="Não deve ser enviada.",
            correlation_id="test-002",
            demo_only=False,
        )

        with self.assertRaisesRegex(ValueError, "somente a fixture"):
            notifier.send(message)

    def test_discord_error_does_not_expose_webhook_token(self) -> None:
        secret = "token-secreto-nao-vazar"  # noqa: S105 - fixture de teste
        notifier = DiscordWebhookNotifier(
            f"https://discord.com/api/webhooks/123456/{secret}",
            transport=RecordingTransport(status=429),
        )

        with self.assertRaises(DiscordNotificationError) as raised:
            notifier.send(_demo_message())
        self.assertNotIn(secret, str(raised.exception))


if __name__ == "__main__":
    unittest.main()
