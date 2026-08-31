from __future__ import annotations

import json
import re
import secrets
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse
from urllib.request import Request, urlopen

from legal_monitor.notifications.base import (
    NotificationAttachment,
    NotificationMessage,
    NotificationReceipt,
)

DISCORD_DEFAULT_ATTACHMENT_LIMIT = 10 * 1_024 * 1_024


class DiscordNotificationError(RuntimeError):
    """Falha sanitizada: nunca inclui a URL/token do webhook."""


@dataclass(frozen=True, slots=True)
class JsonResponse:
    status: int
    payload: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class PreparedAttachment:
    filename: str
    mime_type: str
    content: bytes


class DiscordTransport(Protocol):
    def post_json(
        self, url: str, payload: Mapping[str, Any], *, timeout: float
    ) -> JsonResponse: ...

    def post_multipart(
        self,
        url: str,
        payload: Mapping[str, Any],
        attachments: tuple[PreparedAttachment, ...],
        *,
        timeout: float,
    ) -> JsonResponse: ...


def _encode_multipart(
    payload: Mapping[str, Any], attachments: tuple[PreparedAttachment, ...]
) -> tuple[str, bytes]:
    boundary = f"lcf-legal-monitor-{secrets.token_hex(16)}"
    body = bytearray()

    def append_line(value: str = "") -> None:
        body.extend(value.encode("utf-8"))
        body.extend(b"\r\n")

    append_line(f"--{boundary}")
    append_line('Content-Disposition: form-data; name="payload_json"')
    append_line("Content-Type: application/json; charset=utf-8")
    append_line()
    append_line(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
    for index, attachment in enumerate(attachments):
        append_line(f"--{boundary}")
        append_line(
            f'Content-Disposition: form-data; name="files[{index}]"; '
            f'filename="{attachment.filename}"'
        )
        append_line(f"Content-Type: {attachment.mime_type}")
        append_line()
        body.extend(attachment.content)
        body.extend(b"\r\n")
    append_line(f"--{boundary}--")
    return f"multipart/form-data; boundary={boundary}", bytes(body)


class UrllibDiscordTransport:
    def _execute(self, request: Request, *, timeout: float) -> JsonResponse:
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

    def post_json(self, url: str, payload: Mapping[str, Any], *, timeout: float) -> JsonResponse:
        request = Request(  # noqa: S310 - URL HTTPS do Discord validada antes da chamada.
            url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "User-Agent": "lcf-legal-monitor-demo/0.5",
            },
            method="POST",
        )
        return self._execute(request, timeout=timeout)

    def post_multipart(
        self,
        url: str,
        payload: Mapping[str, Any],
        attachments: tuple[PreparedAttachment, ...],
        *,
        timeout: float,
    ) -> JsonResponse:
        content_type, body = _encode_multipart(payload, attachments)
        request = Request(  # noqa: S310 - URL HTTPS do Discord validada antes da chamada.
            url,
            data=body,
            headers={
                "Content-Type": content_type,
                "User-Agent": "lcf-legal-monitor-demo/0.5",
            },
            method="POST",
        )
        return self._execute(request, timeout=timeout)


def _validated_webhook_url(value: str) -> str:
    parsed = urlparse(value)
    try:
        port = parsed.port
    except ValueError:
        raise DiscordNotificationError(
            "Webhook guardado no Keychain não é uma URL HTTPS oficial do Discord"
        ) from None
    path_parts = [part for part in parsed.path.split("/") if part]
    valid_path = (
        len(path_parts) == 4
        and path_parts[0] == "api"
        and path_parts[1] == "webhooks"
        and path_parts[2].isdigit()
        and re.fullmatch(r"[A-Za-z0-9._-]{20,}", path_parts[3]) is not None
    )
    query_pairs = parse_qsl(parsed.query, keep_blank_values=True)
    valid_query = all(key == "wait" for key, _ in query_pairs)
    if (
        parsed.scheme != "https"
        or parsed.hostname != "discord.com"
        or parsed.username is not None
        or parsed.password is not None
        or port not in (None, 443)
        or parsed.fragment
        or not valid_path
        or not valid_query
    ):
        raise DiscordNotificationError(
            "Webhook guardado no Keychain não é uma URL HTTPS oficial do Discord"
        )

    query = dict(query_pairs)
    query["wait"] = "true"
    return urlunparse(parsed._replace(query=urlencode(query), fragment=""))


def _prepare_attachment(
    attachment: NotificationAttachment,
    *,
    maximum_bytes: int,
    allowed_root: str,
) -> PreparedAttachment:
    try:
        resolved_path = attachment.path.resolve(strict=True)
        resolved_root = Path(allowed_root).resolve(strict=True)
    except OSError:
        raise DiscordNotificationError("Anexo de demonstração não pôde ser resolvido") from None
    if not resolved_path.is_relative_to(resolved_root):
        raise DiscordNotificationError("Anexo está fora do diretório temporário da demonstração")
    try:
        size = resolved_path.stat().st_size
    except OSError:
        raise DiscordNotificationError("Anexo de demonstração não pôde ser lido") from None
    if size <= 0 or size > maximum_bytes:
        raise DiscordNotificationError(
            f"Anexo de demonstração deve ter entre 1 byte e {maximum_bytes} bytes"
        )
    try:
        with resolved_path.open("rb") as stream:
            content = stream.read(maximum_bytes + 1)
    except OSError:
        raise DiscordNotificationError("Anexo de demonstração não pôde ser lido") from None
    if len(content) != size or len(content) > maximum_bytes:
        raise DiscordNotificationError("Anexo mudou durante a leitura ou excedeu o limite")
    if not content.startswith(b"%PDF-"):
        raise DiscordNotificationError("Anexo de demonstração não possui assinatura PDF")
    return PreparedAttachment(
        filename=attachment.filename,
        mime_type=attachment.mime_type,
        content=content,
    )


class DiscordWebhookNotifier:
    """Canal de prova técnica; não integra o outbox nem aceita dados processuais reais."""

    def __init__(
        self,
        webhook_url: str,
        *,
        transport: DiscordTransport | None = None,
        timeout_seconds: float = 10.0,
        maximum_attachment_bytes: int = DISCORD_DEFAULT_ATTACHMENT_LIMIT,
        allowed_attachment_root: str | None = None,
    ) -> None:
        if (
            maximum_attachment_bytes < 1
            or maximum_attachment_bytes > DISCORD_DEFAULT_ATTACHMENT_LIMIT
        ):
            raise ValueError("Limite de anexo Discord fora da faixa permitida")
        self._webhook_url = _validated_webhook_url(webhook_url)
        self._transport = transport or UrllibDiscordTransport()
        self._timeout_seconds = timeout_seconds
        self._maximum_attachment_bytes = maximum_attachment_bytes
        self._allowed_attachment_root = allowed_attachment_root

    def send(self, message: NotificationMessage) -> NotificationReceipt:
        if not message.demo_only:
            raise ValueError(
                "O webhook Discord desta fase aceita somente a fixture de demonstração"
            )
        if len(message.attachments) > 1:
            raise ValueError("A prova Discord aceita no máximo um anexo fictício")
        if message.attachments and self._allowed_attachment_root is None:
            raise ValueError("Anexo Discord exige diretório temporário explicitamente permitido")
        payload = {
            "content": message.render_text(),
            "username": "LCF Legal Monitor — Demonstração",
            "allowed_mentions": {"parse": []},
        }
        prepared = tuple(
            _prepare_attachment(
                item,
                maximum_bytes=self._maximum_attachment_bytes,
                allowed_root=self._allowed_attachment_root or "",
            )
            for item in message.attachments
        )
        if prepared:
            response = self._transport.post_multipart(
                self._webhook_url,
                payload,
                prepared,
                timeout=self._timeout_seconds,
            )
        else:
            response = self._transport.post_json(
                self._webhook_url,
                payload,
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
