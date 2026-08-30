from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from urllib.parse import urlparse

DJEN_PRODUCTION_URL = "https://comunicaapi.pje.jus.br/api/v1"
DJEN_HOMOLOGATION_HOST = "hcomunicaapi.cnj.jus.br"


class ConfigError(ValueError):
    """Configuração insegura ou inconsistente."""


class AppEnvironment(StrEnum):
    DEVELOPMENT = "development"
    TEST = "test"
    PRODUCTION = "production"


def _parse_bool(value: str | bool | None, *, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ConfigError(f"Valor booleano inválido: {value!r}")


def _load_env_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ConfigError(f"Linha {line_number} inválida em {path.name}")
        key, value = line.split("=", 1)
        key = key.strip()
        if not key or any(char.isspace() for char in key):
            raise ConfigError(f"Chave inválida na linha {line_number} de {path.name}")
        values[key] = value.strip().strip('"').strip("'")
    return values


@dataclass(frozen=True, slots=True)
class Settings:
    app_env: AppEnvironment
    database_url: str
    storage_dir: Path
    temp_dir: Path
    max_document_bytes: int
    djen_base_url_prod: str
    log_level: str
    m0_approved: bool
    real_connectors_enabled: bool
    whatsapp_enabled: bool
    summary_enabled: bool
    scheduler_lease_seconds: int
    scheduler_batch_size: int
    scheduler_max_attempts: int
    scheduler_base_backoff_seconds: int
    scheduler_max_backoff_seconds: int
    worker_stale_seconds: int

    @classmethod
    def from_env(
        cls,
        environ: Mapping[str, str] | None = None,
        *,
        root_dir: Path | None = None,
        load_dotenv: bool = True,
    ) -> Settings:
        root = (root_dir or Path.cwd()).resolve()
        merged = _load_env_file(root / ".env") if load_dotenv else {}
        merged.update(dict(os.environ if environ is None else environ))

        try:
            app_env = AppEnvironment(merged.get("APP_ENV", "development").lower())
        except ValueError as exc:
            raise ConfigError("APP_ENV deve ser development, test ou production") from exc

        storage_dir = Path(merged.get("STORAGE_DIR", "./storage/documents"))
        temp_dir = Path(merged.get("TEMP_DIR", "./storage/tmp"))
        if not storage_dir.is_absolute():
            storage_dir = root / storage_dir
        if not temp_dir.is_absolute():
            temp_dir = root / temp_dir

        try:
            max_bytes = int(merged.get("MAX_DOCUMENT_BYTES", "52428800"))
        except ValueError as exc:
            raise ConfigError("MAX_DOCUMENT_BYTES deve ser inteiro") from exc
        if not 1_048_576 <= max_bytes <= 524_288_000:
            raise ConfigError("MAX_DOCUMENT_BYTES deve ficar entre 1 MiB e 500 MiB")

        settings = cls(
            app_env=app_env,
            database_url=merged.get(
                "DATABASE_URL",
                "postgresql://legal_monitor:legal_monitor_dev@127.0.0.1:5432/legal_monitor",
            ),
            storage_dir=storage_dir.resolve(),
            temp_dir=temp_dir.resolve(),
            max_document_bytes=max_bytes,
            djen_base_url_prod=merged.get("DJEN_BASE_URL_PROD", DJEN_PRODUCTION_URL).rstrip("/"),
            log_level=merged.get("LOG_LEVEL", "INFO").upper(),
            m0_approved=_parse_bool(merged.get("M0_APPROVED")),
            real_connectors_enabled=_parse_bool(merged.get("REAL_CONNECTORS_ENABLED")),
            whatsapp_enabled=_parse_bool(merged.get("WHATSAPP_ENABLED")),
            summary_enabled=_parse_bool(merged.get("SUMMARY_ENABLED")),
            scheduler_lease_seconds=_parse_int(
                merged,
                "SCHEDULER_LEASE_SECONDS",
                default=300,
                minimum=30,
                maximum=3_600,
            ),
            scheduler_batch_size=_parse_int(
                merged,
                "SCHEDULER_BATCH_SIZE",
                default=10,
                minimum=1,
                maximum=100,
            ),
            scheduler_max_attempts=_parse_int(
                merged,
                "SCHEDULER_MAX_ATTEMPTS",
                default=4,
                minimum=1,
                maximum=20,
            ),
            scheduler_base_backoff_seconds=_parse_int(
                merged,
                "SCHEDULER_BASE_BACKOFF_SECONDS",
                default=60,
                minimum=1,
                maximum=86_400,
            ),
            scheduler_max_backoff_seconds=_parse_int(
                merged,
                "SCHEDULER_MAX_BACKOFF_SECONDS",
                default=3_600,
                minimum=1,
                maximum=604_800,
            ),
            worker_stale_seconds=_parse_int(
                merged,
                "WORKER_STALE_SECONDS",
                default=600,
                minimum=60,
                maximum=86_400,
            ),
        )
        settings.validate()
        return settings

    def validate(self) -> None:
        parsed_djen = urlparse(self.djen_base_url_prod)
        if parsed_djen.scheme != "https":
            raise ConfigError("DJEN_BASE_URL_PROD exige HTTPS")
        if parsed_djen.hostname == DJEN_HOMOLOGATION_HOST:
            raise ConfigError("Host de homologação do DJEN não pode ser configurado como produção")
        if self.app_env is AppEnvironment.PRODUCTION:
            if self.djen_base_url_prod != DJEN_PRODUCTION_URL:
                raise ConfigError(f"Produção exige DJEN_BASE_URL_PROD={DJEN_PRODUCTION_URL}")
            if "legal_monitor_dev" in self.database_url:
                raise ConfigError(
                    "A senha fictícia de desenvolvimento não pode ser usada em produção"
                )
        if not self.database_url.startswith(("postgresql://", "postgresql+psycopg://")):
            raise ConfigError("DATABASE_URL deve apontar para PostgreSQL")
        if self.storage_dir == self.temp_dir:
            raise ConfigError("STORAGE_DIR e TEMP_DIR precisam ser diferentes")
        if self.real_connectors_enabled and not self.m0_approved:
            raise ConfigError("Conectores reais exigem M0_APPROVED=true")
        if self.whatsapp_enabled and not self.m0_approved:
            raise ConfigError("WhatsApp exige M0_APPROVED=true")
        if self.scheduler_base_backoff_seconds > self.scheduler_max_backoff_seconds:
            raise ConfigError(
                "SCHEDULER_BASE_BACKOFF_SECONDS não pode exceder SCHEDULER_MAX_BACKOFF_SECONDS"
            )


def _parse_int(
    values: Mapping[str, str],
    key: str,
    *,
    default: int,
    minimum: int,
    maximum: int,
) -> int:
    raw = values.get(key, str(default))
    try:
        parsed = int(raw)
    except ValueError as exc:
        raise ConfigError(f"{key} deve ser inteiro") from exc
    if not minimum <= parsed <= maximum:
        raise ConfigError(f"{key} deve ficar entre {minimum} e {maximum}")
    return parsed
