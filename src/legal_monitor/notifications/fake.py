from __future__ import annotations

from legal_monitor.notifications.base import NotificationMessage, NotificationReceipt


class FakeNotifier:
    """Coletor determinístico em memória; não usa rede nem entrega mensagens reais."""

    def __init__(self) -> None:
        self.messages: list[NotificationMessage] = []

    def send(self, message: NotificationMessage) -> NotificationReceipt:
        if not message.demo_only:
            raise ValueError("FakeNotifier desta fase aceita somente mensagens de demonstração")
        self.messages.append(message)
        return NotificationReceipt(
            channel="FAKE",
            provider_id=f"fake-{len(self.messages)}",
            accepted=True,
        )
