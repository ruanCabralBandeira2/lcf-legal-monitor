from __future__ import annotations

import tempfile
import unittest
from email.message import EmailMessage
from pathlib import Path

from legal_monitor.notifications.base import NotificationAttachment, NotificationMessage
from legal_monitor.notifications.email import EmailNotificationError, EmailNotifier
from tests.helpers import blank_pdf_bytes


class RecordingTransport:
    def __init__(self) -> None:
        self.sent: list[EmailMessage] = []

    def send(self, message: EmailMessage) -> None:
        self.sent.append(message)


class EmailNotifierTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.transport = RecordingTransport()
        self.notifier = EmailNotifier(
            sender="robo@example.com",
            recipients=("advogado@example.com",),
            transport=self.transport,
            allowed_attachment_root=self.root,
            maximum_attachment_bytes=1_048_576,
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _message(self, *attachments: NotificationAttachment) -> NotificationMessage:
        return NotificationMessage(
            title="[LCF Monitor] Teste",
            body="Corpo fictício",
            correlation_id="c-1",
            demo_only=True,
            attachments=attachments,
        )

    def test_sends_pdf_attachment(self) -> None:
        pdf = self.root / "peca.pdf"
        pdf.write_bytes(blank_pdf_bytes())
        receipt = self.notifier.send(self._message(NotificationAttachment(pdf, "peca.pdf")))
        self.assertEqual(receipt.channel, "EMAIL")
        sent = self.transport.sent[0]
        self.assertEqual(sent["To"], "advogado@example.com")
        self.assertEqual(sent["X-LCF-Correlation-Id"], "c-1")
        names = [part.get_filename() for part in sent.iter_attachments()]
        self.assertEqual(names, ["peca.pdf"])

    def test_rejects_attachment_outside_root(self) -> None:
        with tempfile.TemporaryDirectory() as other:
            pdf = Path(other) / "fora.pdf"
            pdf.write_bytes(blank_pdf_bytes())
            with self.assertRaisesRegex(EmailNotificationError, "fora do diretório"):
                self.notifier.send(self._message(NotificationAttachment(pdf, "fora.pdf")))

    def test_rejects_non_pdf(self) -> None:
        fake = self.root / "falso.pdf"
        fake.write_text("nao e pdf", encoding="utf-8")
        with self.assertRaisesRegex(EmailNotificationError, "assinatura PDF"):
            self.notifier.send(self._message(NotificationAttachment(fake, "falso.pdf")))

    def test_rejects_attachments_over_limit(self) -> None:
        pdf = self.root / "grande.pdf"
        pdf.write_bytes(b"%PDF-" + b"0" * 1_100_000)
        with self.assertRaisesRegex(EmailNotificationError, "limite"):
            self.notifier.send(self._message(NotificationAttachment(pdf, "grande.pdf")))

    def test_rejects_invalid_address(self) -> None:
        with self.assertRaises(EmailNotificationError):
            EmailNotifier(
                sender="invalido",
                recipients=("a@example.com",),
                transport=self.transport,
                allowed_attachment_root=self.root,
            )


if __name__ == "__main__":
    unittest.main()
