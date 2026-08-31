from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse
from urllib.request import Request, urlopen

from legal_monitor.notifications.base import NotificationMessage, NotificationReceipt


class DiscordNotificationError(RuntimeError):
    """Falha sanitizada: nunca inclui a URL/token do webhook."""


@dataclass(frozen=True, slots=True)
class JsonResponse:
    status: int
    payload: Mapping[str, Any]


class JsonTransport(Protocol):
    def post(self, url: str, payload: Mapping[str, Any], *, timeout: float) -> JsonResponse: ...


class UrllibJsonTransport:
    def post(self, url: str, payload: Mapping[str, Any], *, timeout: float) -> JsonResponse:
        request = Request(  # noqa: S310 - URL HTTPS do Discord validada antes da chamada.
            url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "User-Agent": "lcf-legal-monitor-demo/0.4",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=timeout) as response:  # noqa: S310
                raw = response.read(1_048_577)
                if len(raw) > 1_048_576:
                    raise DiscordNotificationError("Resposta do Discord excedeu o limite seguro")
                decoded = json.loads(raw) if raw else {}
                if not isinstance(decoded, dict):
                    raise DiscordNotificationError("Resposta inesperada do Discord")
                return JsonResponse(status=response.status, payload=decoded)
        except HTTPError as exc:
            raise DiscordNotificationError(
                f"Discord recusou a mensagem de demonstração (HTTP {exc.code})"
            ) from None
        except URLError:
            raise DiscordNotificationError("Não foi possível alcançar o Discord") from None
        except TimeoutError:
            raise DiscordNotificationError("Tempo esgotado ao alcançar o Discord") from None
        except json.JSONDecodeError:
            raise DiscordNotificationError("Resposta inválida do Discord") from None


def _validated_webhook_url(value: str) -> str:
    parsed = urlparse(value)
    try:
        port = parsed.port
    except ValueError:
        raise DiscordNotificationError(
            "DISCORD_WEBHOOK_URL não é um webhook HTTPS oficial do Discord"
        ) from None
    path_parts = [part for part in parsed.path.split("/") if part]
    valid_path = (
        len(path_parts) == 4
        and path_parts[0] == "api"
        and path_parts[1] == "webhooks"
        and path_parts[2].isdigit()
        and bool(path_parts[3])
    )
    if (
        parsed.scheme != "https"
        or parsed.hostname != "discord.com"
        or parsed.username is not None
        or parsed.password is not None
        or port not in (None, 443)
        or parsed.fragment
        or not valid_path
    ):
        raise DiscordNotificationError(
            "DISCORD_WEBHOOK_URL não é um webhook HTTPS oficial do Discord"
        )

    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query["wait"] = "true"
    return urlunparse(parsed._replace(query=urlencode(query), fragment=""))


class DiscordWebhookNotifier:
    """Canal de prova técnica; não integra o outbox nem aceita dados processuais reais."""

    def __init__(
        self,
        webhook_url: str,
        *,
        transport: JsonTransport | None = None,
        timeout_seconds: float = 10.0,
    ) -> None:
        self._webhook_url = _validated_webhook_url(webhook_url)
        self._transport = transport or UrllibJsonTransport()
        self._timeout_seconds = timeout_seconds

    def send(self, message: NotificationMessage) -> NotificationReceipt:
        if not message.demo_only:
            raise ValueError(
                "O webhook Discord desta fase aceita somente a fixture de demonstração"
            )
        response = self._transport.post(
            self._webhook_url,
            {
                "content": message.render_text(),
                "username": "LCF Legal Monitor — Demonstração",
                "allowed_mentions": {"parse": []},
            },
            timeout=self._timeout_seconds,
        )
        if response.status < 200 or response.status >= 300:
            raise DiscordNotificationError(
                f"Discord recusou a mensagem de demonstração (HTTP {response.status})"
            )
        provider_id = response.payload.get("id")
        return NotificationReceipt(
            channel="DISCORD_DEMO",
            provider_id=str(provider_id) if provider_id is not None else None,
            accepted=True,
        )
