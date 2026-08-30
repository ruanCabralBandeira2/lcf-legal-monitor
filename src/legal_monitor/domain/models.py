from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from legal_monitor.domain.cnj import CnjNumber
from legal_monitor.domain.enums import SourceSystem


def utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class ProcessRef:
    cnj: CnjNumber
    tribunal: str = "TJRJ"
    current_system: SourceSystem = SourceSystem.UNKNOWN


@dataclass(frozen=True, slots=True)
class Movement:
    source: SourceSystem
    source_event_id: str | None
    event_at: datetime | None
    observed_at: datetime
    type_raw: str
    type_normalized: str
    description: str
    document_ref: str | None = None
    raw_payload_ref: str | None = None
    correlation_id: str | None = None
    fingerprint: str = field(init=False)

    def __post_init__(self) -> None:
        if self.observed_at.tzinfo is None:
            raise ValueError("observed_at precisa conter fuso horário")
        canonical = {
            "source": self.source.value,
            "source_event_id": self.source_event_id,
            "event_at": self.event_at.isoformat() if self.event_at else None,
            "type": self.type_normalized.strip().casefold(),
            "description": " ".join(self.description.split()).casefold(),
            "document_ref": self.document_ref,
        }
        digest = hashlib.sha256(
            json.dumps(canonical, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()
        object.__setattr__(self, "fingerprint", digest)


@dataclass(frozen=True, slots=True)
class DocumentRecord:
    storage_path: Path
    friendly_name: str
    mime: str
    bytes: int
    page_count: int
    sha256: str
    collected_at: datetime
    text_extractable: bool
    already_existed: bool = False

    def __post_init__(self) -> None:
        if len(self.sha256) != 64 or any(c not in "0123456789abcdef" for c in self.sha256):
            raise ValueError("SHA-256 inválido")

    def as_audit_metadata(self) -> dict[str, Any]:
        return {
            "storage_path": str(self.storage_path),
            "mime": self.mime,
            "bytes": self.bytes,
            "page_count": self.page_count,
            "sha256": self.sha256,
            "collected_at": self.collected_at.isoformat(),
            "text_extractable": self.text_extractable,
            "already_existed": self.already_existed,
        }
