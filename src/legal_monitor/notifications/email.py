from __future__ import annotations

import re
import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import make_msgid
from pathlib import Path
from typing import Protocol

from legal_monitor.notifications.base import NotificationMessage, NotificationReceipt

EMAIL_DEFAULT_ATTACHMENT_LIMIT = 20 * 1_024 * 1_024
EMAIL_ADDRESS = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")


class EmailNotificationError(RuntimeError):
    """Falha sanitizada: nunca inclui senha nem conteúdo de anexo."""


def validate_address(value: str) -> str:
    normalized = value.strip()
    if not EMAIL_ADDRESS.fullmatch(normalized):
        raise EmailNotificationError("Endereço de e-mail inválido na configuração")
    return normalized


class SmtpTransport(Protocol):
    def send(self, message: EmailMessage) -> None: ...


@dataclass(frozen=True, slots=True)
class SmtpSslTransport:
    host: str
    port: int
    username: str
    password: str
    timeout_seconds: float = 30.0

    def send(self, message: EmailMessage) -> None:
        context = ssl.create_default_context()
        try:
            with smtplib.SMTP_SSL(
                self.host, self.port, context=context, timeout=self.timeout_seconds
            ) as client:
                client.login(self.username, self.password)
                client.send_message(message)
        except smtplib.SMTPAuthenticationError:
            raise EmailNotificationError(
                "SMTP recusou o login; confira usuário e senha de app no cofre"
            ) from None
        except (smtplib.SMTPException, OSError, TimeoutError) as exc:
            raise EmailNotificationError(f"Falha ao enviar e-mail ({type(exc).__name__})") from None


class EmailNotifier:
    """Canal e-mail: texto simples e PDFs validados dentro de uma raiz permitida."""

    def __init__(
        self,
        *,
        sender: str,
        recipients: tuple[str, ...],
        transport: SmtpTransport,
        allowed_attachment_root: Path,
        maximum_attachment_bytes: int = EMAIL_DEFAULT_ATTACHMENT_LIMIT,
    ) -> None:
        if not recipients:
            raise EmailNotificationError("Nenhum destinatário de e-mail configurado")
        self._sender = validate_address(sender)
        self._recipients = tuple(validate_address(item) for item in recipients)
        self._transport = transport
        self._root = allowed_attachment_root.resolve()
        self._maximum = maximum_attachment_bytes

    def build(self, message: NotificationMessage) -> EmailMessage:
        email = EmailMessage()
        email["Subject"] = message.title.strip()
        email["From"] = self._sender
        email["To"] = ", ".join(self._recipients)
        email["Message-ID"] = make_msgid(domain="lcf-legal-monitor.local")
        email["X-LCF-Correlation-Id"] = message.correlation_id
        email.set_content(
            f"{message.body.strip()}\n\n--\nLCF Legal Monitor. Mensagem automática; "
            "prazo não calculado. Confira sempre no sistema do tribunal.\n"
        )
        total = 0
        for attachment in message.attachments:
            content = self._read_pdf(attachment.path)
            total += len(content)
            if total > self._maximum:
                raise EmailNotificationError("Anexos excedem o limite configurado para e-mail")
            email.add_attachment(
                content, maintype="application", subtype="pdf", filename=attachment.filename
            )
        return email

    def send(self, message: NotificationMessage) -> NotificationReceipt:
        email = self.build(message)
        self._transport.send(email)
        return NotificationReceipt(
            channel="EMAIL", provider_id=str(email["Message-ID"]), accepted=True
        )

    def _read_pdf(self, path: Path) -> bytes:
        try:
            resolved = path.resolve(strict=True)
        except OSError:
            raise EmailNotificationError("Anexo não encontrado") from None
        if not resolved.is_relative_to(self._root):
            raise EmailNotificationError("Anexo fora do diretório permitido")
        content = resolved.read_bytes()
        if not content.startswith(b"%PDF-"):
            raise EmailNotificationError("Anexo não possui assinatura PDF")
        return content
