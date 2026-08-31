from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import Any

from legal_monitor.notifications.base import NotificationAttachment, NotificationMessage
from legal_monitor.notifications.discord import (
    DiscordNotificationError,
    DiscordWebhookNotifier,
    JsonResponse,
    PreparedAttachment,
    _encode_multipart,
)
from legal_monitor.notifications.fake import FakeNotifier
from tests.helpers import blank_pdf_bytes

WEBHOOK = "https://discord.com/api/webhooks/123456/token-ficticio-seguro-1234567890"


class RecordingTransport:
    def __init__(self, *, status: int = 200, provider_id: str = "message-123") -> None:
        self.status = status
        self.provider_id = provider_id
        self.url: str | None = None
        self.payload: dict[str, Any] | None = None
        self.attachments: tuple[PreparedAttachment, ...] = ()
        self.timeout: float | None = None
        self.kind: str | None = None

    def _record(
        self,
        *,
        kind: str,
        url: str,
        payload: dict[str, Any],
        timeout: float,
        attachments: tuple[PreparedAttachment, ...] = (),
    ) -> JsonResponse:
        self.kind = kind
        self.url = url
        self.payload = payload
        self.attachments = attachments
        self.timeout = timeout
        return JsonResponse(status=self.status, payload={"id": self.provider_id})

    def post_json(self, url: str, payload: dict[str, Any], *, timeout: float) -> JsonResponse:
        return self._record(kind="json", url=url, payload=payload, timeout=timeout)

    def post_multipart(
        self,
        url: str,
        payload: dict[str, Any],
        attachments: tuple[PreparedAttachment, ...],
        *,
        timeout: float,
    ) -> JsonResponse:
        return self._record(
            kind="multipart",
            url=url,
            payload=payload,
            attachments=attachments,
            timeout=timeout,
        )


def _demo_message(
    attachments: tuple[NotificationAttachment, ...] = (),
) -> NotificationMessage:
    return NotificationMessage(
        title="Prova técnica",
        body="Fixture sem dado processual real.",
        correlation_id="test-001",
        demo_only=True,
        attachments=attachments,
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
            WEBHOOK,
            transport=transport,
        )

        receipt = notifier.send(_demo_message())

        self.assertTrue(receipt.accepted)
        self.assertEqual(receipt.provider_id, "message-123")
        self.assertEqual(transport.kind, "json")
        self.assertIsNotNone(transport.url)
        self.assertIn("wait=true", transport.url or "")
        self.assertIsNotNone(transport.payload)
        self.assertEqual((transport.payload or {})["allowed_mentions"], {"parse": []})

    def test_discord_sends_one_valid_fictitious_pdf_as_multipart(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "fixture.pdf"
            path.write_bytes(blank_pdf_bytes())
            transport = RecordingTransport()
            notifier = DiscordWebhookNotifier(
                WEBHOOK,
                transport=transport,
                allowed_attachment_root=temporary,
            )
            receipt = notifier.send(
                _demo_message((NotificationAttachment(path=path, filename="fixture.pdf"),))
            )

        self.assertTrue(receipt.accepted)
        self.assertEqual(transport.kind, "multipart")
        self.assertEqual(len(transport.attachments), 1)
        self.assertEqual(transport.attachments[0].filename, "fixture.pdf")
        self.assertTrue(transport.attachments[0].content.startswith(b"%PDF-"))

    def test_multipart_contains_payload_and_attachment_without_secret(self) -> None:
        content_type, body = _encode_multipart(
            {"content": "fixture"},
            (PreparedAttachment("fixture.pdf", "application/pdf", b"%PDF-fixture"),),
        )

        self.assertTrue(content_type.startswith("multipart/form-data; boundary="))
        self.assertIn(b'name="payload_json"', body)
        self.assertIn(b'name="files[0]"; filename="fixture.pdf"', body)
        self.assertIn(b"%PDF-fixture", body)

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
            WEBHOOK,
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

    def test_discord_rejects_non_pdf_attachment(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "not-pdf.pdf"
            path.write_bytes(b"not a pdf")
            notifier = DiscordWebhookNotifier(
                WEBHOOK,
                transport=RecordingTransport(),
                allowed_attachment_root=temporary,
            )
            with self.assertRaisesRegex(DiscordNotificationError, "assinatura PDF"):
                notifier.send(
                    _demo_message((NotificationAttachment(path=path, filename="fixture.pdf"),))
                )

    def test_discord_enforces_configured_attachment_limit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "fixture.pdf"
            path.write_bytes(blank_pdf_bytes())
            notifier = DiscordWebhookNotifier(
                WEBHOOK,
                transport=RecordingTransport(),
                maximum_attachment_bytes=8,
                allowed_attachment_root=temporary,
            )
            with self.assertRaisesRegex(DiscordNotificationError, "entre 1 byte"):
                notifier.send(
                    _demo_message((NotificationAttachment(path=path, filename="fixture.pdf"),))
                )

    def test_discord_rejects_attachment_outside_allowed_demo_directory(self) -> None:
        with (
            tempfile.TemporaryDirectory() as allowed,
            tempfile.TemporaryDirectory() as other,
        ):
            path = Path(other) / "fixture.pdf"
            path.write_bytes(blank_pdf_bytes())
            notifier = DiscordWebhookNotifier(
                WEBHOOK,
                transport=RecordingTransport(),
                allowed_attachment_root=allowed,
            )
            with self.assertRaisesRegex(DiscordNotificationError, "fora do diretório"):
                notifier.send(
                    _demo_message((NotificationAttachment(path=path, filename="fixture.pdf"),))
                )

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
