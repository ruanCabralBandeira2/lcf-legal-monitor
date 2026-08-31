from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from legal_monitor.domain.cnj import CnjNumber
from legal_monitor.domain.enums import MonitorStatus, Sensitivity, SourceSystem


@dataclass(frozen=True, slots=True)
class LawyerRecord:
    id: UUID
    reference_code: str
    display_name: str
    active: bool
    created_at: datetime
    created: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "reference_code": self.reference_code,
            "display_name": self.display_name,
            "active": self.active,
            "created_at": self.created_at.isoformat(),
            "created": self.created,
        }


@dataclass(frozen=True, slots=True)
class ProcessRecord:
    id: UUID
    cnj: CnjNumber
    tribunal: str
    lawyer_reference: str
    current_system: SourceSystem
    sensitivity: Sensitivity
    monitor_status: MonitorStatus
    last_success_at: datetime | None
    next_check_at: datetime | None
    active: bool
    created_at: datetime
    initial_job_id: UUID | None = None
    created: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "process": self.cnj.masked(),
            "tribunal": self.tribunal,
            "lawyer_reference": self.lawyer_reference,
            "current_system": self.current_system.value,
            "sensitivity": self.sensitivity.value,
            "monitor_status": self.monitor_status.value,
            "last_success_at": (self.last_success_at.isoformat() if self.last_success_at else None),
            "next_check_at": self.next_check_at.isoformat() if self.next_check_at else None,
            "active": self.active,
            "created_at": self.created_at.isoformat(),
            "initial_job_id": str(self.initial_job_id) if self.initial_job_id else None,
            "created": self.created,
        }


@dataclass(frozen=True, slots=True)
class DeactivationResult:
    process_id: UUID
    cnj: CnjNumber
    changed: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "process_id": str(self.process_id),
            "process": self.cnj.masked(),
            "changed": self.changed,
            "monitor_status": MonitorStatus.DISABLED.value,
        }
