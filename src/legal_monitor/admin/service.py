from __future__ import annotations

import re
from datetime import UTC, datetime

from legal_monitor.admin.models import DeactivationResult, LawyerRecord, ProcessRecord
from legal_monitor.admin.repository import PostgresAdminRepository
from legal_monitor.domain.cnj import CnjNumber
from legal_monitor.domain.enums import Sensitivity

REFERENCE_CODE = re.compile(r"^[a-z0-9][a-z0-9_-]{2,63}$")


class AdminValidationError(ValueError):
    """Entrada administrativa inválida."""


class AdminService:
    def __init__(
        self,
        repository: PostgresAdminRepository,
        *,
        scheduler_max_attempts: int = 4,
    ) -> None:
        self._repository = repository
        self._scheduler_max_attempts = scheduler_max_attempts

    def register_lawyer(
        self,
        *,
        reference_code: str,
        display_name: str,
        actor_id: str,
        now: datetime | None = None,
    ) -> LawyerRecord:
        code = reference_code.strip().lower()
        name = " ".join(display_name.split())
        actor = actor_id.strip()
        if not REFERENCE_CODE.fullmatch(code):
            raise AdminValidationError(
                "Código deve ter 3-64 caracteres: letras minúsculas, números, _ ou -"
            )
        if not 2 <= len(name) <= 120:
            raise AdminValidationError("Nome de exibição deve ter entre 2 e 120 caracteres")
        if not actor:
            raise AdminValidationError("actor_id não pode ser vazio")
        return self._repository.register_lawyer(
            reference_code=code,
            display_name=name,
            actor_id=actor,
            occurred_at=now or datetime.now(UTC),
        )

    def register_process(
        self,
        *,
        cnj_value: str,
        lawyer_reference: str,
        sensitivity: Sensitivity = Sensitivity.CONFIDENTIAL,
        actor_id: str,
        now: datetime | None = None,
    ) -> ProcessRecord:
        cnj = CnjNumber.parse(cnj_value)
        if cnj.tribunal_code != "19":
            raise AdminValidationError("O MVP aceita somente processos do TJRJ (código 19)")
        lawyer_code = lawyer_reference.strip().lower()
        if not REFERENCE_CODE.fullmatch(lawyer_code):
            raise AdminValidationError("Código do responsável inválido")
        actor = actor_id.strip()
        if not actor:
            raise AdminValidationError("actor_id não pode ser vazio")
        occurred_at = now or datetime.now(UTC)
        return self._repository.register_process(
            cnj=cnj,
            lawyer_reference=lawyer_code,
            sensitivity=sensitivity,
            actor_id=actor,
            occurred_at=occurred_at,
            first_check_at=occurred_at,
            max_attempts=self._scheduler_max_attempts,
        )

    def list_processes(self, *, include_inactive: bool = False) -> tuple[ProcessRecord, ...]:
        return self._repository.list_processes(include_inactive=include_inactive)

    def deactivate_process(
        self,
        *,
        cnj_value: str,
        actor_id: str,
        now: datetime | None = None,
    ) -> DeactivationResult:
        actor = actor_id.strip()
        if not actor:
            raise AdminValidationError("actor_id não pode ser vazio")
        return self._repository.deactivate_process(
            cnj=CnjNumber.parse(cnj_value),
            actor_id=actor,
            occurred_at=now or datetime.now(UTC),
        )
