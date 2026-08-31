from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from legal_monitor.domain.enums import ErrorCode

BLOCKING_ERRORS = frozenset(
    {
        ErrorCode.AUTH_REQUIRED,
        ErrorCode.CAPTCHA_REQUIRED,
        ErrorCode.SOURCE_DIVERGENCE,
        ErrorCode.MIGRATION_DETECTED,
        ErrorCode.WORKER_MISCONFIGURED,
    }
)


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    base_seconds: int = 60
    maximum_seconds: int = 3_600
    jitter_ratio: float = 0.20

    def __post_init__(self) -> None:
        if self.base_seconds < 1:
            raise ValueError("base_seconds deve ser positivo")
        if self.maximum_seconds < self.base_seconds:
            raise ValueError("maximum_seconds deve ser maior ou igual a base_seconds")
        if not 0 <= self.jitter_ratio <= 0.5:
            raise ValueError("jitter_ratio deve ficar entre 0 e 0.5")

    def is_blocking(self, error_code: ErrorCode) -> bool:
        return error_code in BLOCKING_ERRORS

    def next_retry_at(
        self,
        *,
        job_id: UUID,
        attempt: int,
        max_attempts: int,
        error_code: ErrorCode,
        now: datetime,
        retry_after_seconds: int | None = None,
    ) -> datetime | None:
        if now.tzinfo is None:
            raise ValueError("now precisa conter fuso horário")
        if self.is_blocking(error_code) or attempt >= max_attempts:
            return None
        if retry_after_seconds is not None:
            delay = min(max(retry_after_seconds, 1), self.maximum_seconds)
        else:
            exponential = min(self.base_seconds * (2 ** max(attempt - 1, 0)), self.maximum_seconds)
            digest = hashlib.sha256(f"{job_id}:{attempt}".encode()).digest()
            unit = int.from_bytes(digest[:4], "big") / ((2**32) - 1)
            factor = 1 + ((unit * 2) - 1) * self.jitter_ratio
            delay = max(1, round(exponential * factor))
        return now + timedelta(seconds=delay)
