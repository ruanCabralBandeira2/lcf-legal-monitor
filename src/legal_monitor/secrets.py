from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

SERVICE_PREFIX = "com.lcf.legal-monitor"


class SecretStoreError(RuntimeError):
    """Falha sanitizada; nunca inclui o valor do segredo."""


class SecretStore(Protocol):
    def get(self, name: str, account: str) -> str: ...

    def set(self, name: str, account: str, value: str) -> None: ...


def _validate(value: str, *, label: str) -> str:
    normalized = value.strip()
    if not normalized or len(normalized) > 128 or any(char in normalized for char in "\r\n\0"):
        raise SecretStoreError(f"Identificador inválido para {label}")
    return normalized


@dataclass(frozen=True, slots=True)
class KeyringSecretStore:
    """Keychain no macOS, Gerenciador de Credenciais no Windows, via `keyring`."""

    prefix: str = SERVICE_PREFIX

    def _service(self, name: str) -> str:
        return f"{self.prefix}.{_validate(name, label='nome do segredo')}"

    def get(self, name: str, account: str) -> str:
        import keyring
        from keyring.errors import KeyringError

        try:
            value = keyring.get_password(self._service(name), _validate(account, label="conta"))
        except KeyringError:
            raise SecretStoreError("Cofre de segredos do sistema indisponível") from None
        if not value:
            raise SecretStoreError(
                f"Segredo {name!r} não configurado; rode: legal-monitor secret-set {name}"
            )
        return value

    def set(self, name: str, account: str, value: str) -> None:
        import keyring
        from keyring.errors import KeyringError

        if not value or any(char in value for char in "\r\n\0"):
            raise SecretStoreError("Valor de segredo vazio ou com caractere inválido")
        try:
            keyring.set_password(self._service(name), _validate(account, label="conta"), value)
        except KeyringError:
            raise SecretStoreError("Não foi possível gravar no cofre de segredos") from None


@dataclass
class MemorySecretStore:
    """Somente para testes."""

    values: dict[tuple[str, str], str]

    def get(self, name: str, account: str) -> str:
        try:
            return self.values[(name, account)]
        except KeyError:
            raise SecretStoreError(f"Segredo {name!r} não configurado") from None

    def set(self, name: str, account: str, value: str) -> None:
        self.values[(name, account)] = value
