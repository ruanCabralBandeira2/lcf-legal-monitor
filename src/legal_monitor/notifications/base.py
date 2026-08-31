from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class NotificationAttachment:
    path: Path
    filename: str
    mime_type: str = "application/pdf"

    def __post_init__(self) -> None:
        if not self.filename or self.filename != Path(self.filename).name:
            raise ValueError("Nome do anexo deve ser simples e não pode conter diretório")
        if any(char in self.filename for char in ("\r", "\n", '"')):
            raise ValueError("Nome do anexo contém caractere inseguro")
        if self.mime_type != "application/pdf":
            raise ValueError("Nesta fase somente anexos PDF são permitidos")


@dataclass(frozen=True, slots=True)
class NotificationMessage:
    """Mensagem mínima; o comando Discord aceita somente uma fixture controlada."""

    title: str
    body: str
    correlation_id: str
    demo_only: bool
    attachments: tuple[NotificationAttachment, ...] = ()

    def __post_init__(self) -> None:
        if not self.title.strip() or not self.body.strip() or not self.correlation_id.strip():
            raise ValueError("Título, corpo e correlação da notificação são obrigatórios")
        if len(self.render_text()) > 2_000:
            raise ValueError("Notificação excede o limite de 2.000 caracteres")

    def render_text(self) -> str:
        return f"**{self.title.strip()}**\n{self.body.strip()}"


@dataclass(frozen=True, slots=True)
class NotificationReceipt:
    channel: str
    provider_id: str | None
    accepted: bool


@runtime_checkable
class Notifier(Protocol):
    def send(self, message: NotificationMessage) -> NotificationReceipt: ...
