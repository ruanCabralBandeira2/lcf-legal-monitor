from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol, runtime_checkable

from legal_monitor.domain.enums import SessionState, SourceSystem
from legal_monitor.domain.models import Movement, ProcessRef


@dataclass(frozen=True, slots=True)
class DiscoveryResult:
    found: bool
    system: SourceSystem
    confidence: float
    evidence_ref: str | None
    observed_at: datetime


@dataclass(frozen=True, slots=True)
class MovementBatch:
    movements: tuple[Movement, ...]
    next_cursor: str | None


@dataclass(frozen=True, slots=True)
class DownloadResult:
    target_path: Path
    source_ref: str
    observed_at: datetime


@dataclass(frozen=True, slots=True)
class SourceHealth:
    available: bool
    checked_at: datetime
    latency_ms: int
    detail: str


@runtime_checkable
class Connector(Protocol):
    @property
    def system(self) -> SourceSystem: ...

    def discover(self, process: ProcessRef) -> DiscoveryResult: ...

    def check_session(self) -> SessionState: ...

    def list_movements(self, process: ProcessRef, since_cursor: str | None) -> MovementBatch: ...

    def fetch_document(
        self,
        process: ProcessRef,
        document_ref: str,
        target_path: Path,
    ) -> DownloadResult: ...

    def healthcheck(self) -> SourceHealth: ...
