from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from legal_monitor.connectors.routing import SourceEndpoint
from legal_monitor.domain.enums import SessionState
from legal_monitor.notifications.base import NotificationMessage, Notifier

_ACTION_TYPE = {
    SessionState.AUTH_REQUIRED: "AUTH_REQUIRED",
    SessionState.CAPTCHA_REQUIRED: "CAPTCHA_REQUIRED",
}


class ManualActionStore(Protocol):
    def open_source_action(
        self, *, action_type: str, connector: str, opened_at: datetime, correlation_id: uuid.UUID
    ) -> bool:
        """Abre ação manual da fonte; retorna False se já havia uma aberta."""
        ...

    def resolve_source_actions(self, *, connector: str, resolved_at: datetime) -> int: ...


@dataclass(frozen=True, slots=True)
class AuthAlertOutcome:
    source: str
    state: SessionState
    action_opened: bool
    notified: bool
    resolved_actions: int = 0


def build_auth_message(
    endpoint: SourceEndpoint, state: SessionState, correlation_id: str
) -> NotificationMessage:
    if state is SessionState.CAPTCHA_REQUIRED:
        step = "resolva o CAPTCHA na janela que abrir"
    else:
        step = "confirme o token USB conectado e aprove o 2FA no celular quando pedir"
    return NotificationMessage(
        title=f"[LCF Monitor] Login necessário: {endpoint.key}",
        body=(
            f"A sessão de {_label(endpoint)} expirou e o robô pausou as consultas "
            f"dessa fonte.\n\n"
            f"O que fazer: no Mac mini, rode\n"
            f"    legal-monitor auth-open {endpoint.key}\n"
            f"e {step}. O robô retoma sozinho quando a sessão ficar válida.\n\n"
            "Nunca responda este e-mail com senha, PIN ou código."
        ),
        correlation_id=correlation_id,
        demo_only=False,
    )


def build_approval_message(endpoint: SourceEndpoint, correlation_id: str) -> NotificationMessage:
    return NotificationMessage(
        title=f"[LCF Monitor] Aprove o login no celular: {endpoint.key}",
        body=(
            f"O robô está entrando em {_label(endpoint)} com o certificado do token USB e a "
            "tela está aguardando a confirmação.\n\n"
            "Se chegou um pedido de 2FA no seu celular, aprove agora. Se o sistema pedir PIN "
            "do token, alguém precisa digitá-lo no Mac mini.\n\n"
            "O robô espera até 10 minutos e segue sozinho após a aprovação."
        ),
        correlation_id=correlation_id,
        demo_only=False,
    )


def _label(endpoint: SourceEndpoint) -> str:
    return endpoint.notes.split(";")[0]


class AuthAlertService:
    """Sessão inválida -> ação manual única por fonte -> um aviso ao operador."""

    def __init__(self, store: ManualActionStore, notifier: Notifier | None) -> None:
        self._store = store
        self._notifier = notifier

    def handle(
        self, endpoint: SourceEndpoint, state: SessionState, *, now: datetime
    ) -> AuthAlertOutcome:
        if state is SessionState.VALID:
            resolved = self._store.resolve_source_actions(connector=endpoint.key, resolved_at=now)
            return AuthAlertOutcome(endpoint.key, state, False, False, resolved)
        action_type = _ACTION_TYPE.get(state)
        if action_type is None:
            return AuthAlertOutcome(endpoint.key, state, False, False)
        correlation_id = uuid.uuid4()
        opened = self._store.open_source_action(
            action_type=action_type,
            connector=endpoint.key,
            opened_at=now,
            correlation_id=correlation_id,
        )
        notified = False
        if opened and self._notifier is not None:
            self._notifier.send(build_auth_message(endpoint, state, str(correlation_id)))
            notified = True
        return AuthAlertOutcome(endpoint.key, state, opened, notified)
