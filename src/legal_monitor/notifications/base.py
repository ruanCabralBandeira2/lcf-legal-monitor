from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class NotificationMessage:
    """Mensagem mínima; o comando Discord aceita somente uma fixture controlada."""

    title: str
    body: str
    correlation_id: str
    demo_only: bool

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
