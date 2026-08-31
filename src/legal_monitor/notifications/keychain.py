from __future__ import annotations

import subprocess
from dataclasses import dataclass


class KeychainSecretError(RuntimeError):
    """Falha sanitizada; nunca inclui o segredo nem a saída do Keychain."""


def _validate_identifier(value: str, *, label: str) -> str:
    normalized = value.strip()
    if not normalized or len(normalized) > 128 or any(char in normalized for char in "\r\n\0"):
        raise KeychainSecretError(f"Identificador inválido para {label} do Keychain")
    return normalized


@dataclass(frozen=True, slots=True)
class MacOSKeychainSecretProvider:
    timeout_seconds: float = 5.0

    def get(self, *, service: str, account: str) -> str:
        safe_service = _validate_identifier(service, label="serviço")
        safe_account = _validate_identifier(account, label="conta")
        try:
            result = subprocess.run(  # noqa: S603 - binário absoluto e argumentos validados.
                [
                    "/usr/bin/security",
                    "find-generic-password",
                    "-s",
                    safe_service,
                    "-a",
                    safe_account,
                    "-w",
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
            )
        except (OSError, subprocess.TimeoutExpired):
            raise KeychainSecretError("Não foi possível consultar o Keychain do macOS") from None
        if result.returncode != 0:
            raise KeychainSecretError(
                "Webhook Discord não encontrado no Keychain; consulte o runbook de configuração"
            )
        secret = result.stdout.rstrip("\r\n")
        if not secret:
            raise KeychainSecretError("O item do webhook no Keychain está vazio")
        return secret
