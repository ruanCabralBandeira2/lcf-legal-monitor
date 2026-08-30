from __future__ import annotations

import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from legal_monitor.connectors.base import (
    DiscoveryResult,
    DownloadResult,
    MovementBatch,
    SourceHealth,
)
from legal_monitor.connectors.errors import AuthenticationRequired, CaptchaRequired, ConnectorError
from legal_monitor.domain.enums import ErrorCode, SessionState, SourceSystem
from legal_monitor.domain.models import Movement, ProcessRef


class FakeConnector:
    """Conector determinístico para desenvolvimento; nunca acessa rede ou navegador."""

    def __init__(
        self,
        *,
        system: SourceSystem = SourceSystem.FAKE,
        movements: tuple[Movement, ...] = (),
        documents: dict[str, bytes] | None = None,
        session_state: SessionState = SessionState.VALID,
    ) -> None:
        self._system = system
        self._movements = movements
        self._documents = documents or {}
        self._session_state = session_state

    @property
    def system(self) -> SourceSystem:
        return self._system

    def discover(self, process: ProcessRef) -> DiscoveryResult:
        del process
        return DiscoveryResult(
            found=True,
            system=self._system,
            confidence=1.0,
            evidence_ref="fixture://fake/discovery",
            observed_at=datetime.now(UTC),
        )

    def check_session(self) -> SessionState:
        return self._session_state

    def _require_valid_session(self) -> None:
        if self._session_state is SessionState.AUTH_REQUIRED:
            raise AuthenticationRequired()
        if self._session_state is SessionState.CAPTCHA_REQUIRED:
            raise CaptchaRequired()
        if self._session_state is SessionState.UNAVAILABLE:
            raise ConnectorError(ErrorCode.SOURCE_UNAVAILABLE, "Fonte simulada indisponível")

    def list_movements(self, process: ProcessRef, since_cursor: str | None) -> MovementBatch:
        del process
        self._require_valid_session()
        try:
            start = int(since_cursor) if since_cursor is not None else 0
        except ValueError as exc:
            raise ConnectorError(ErrorCode.PARSE_ERROR, "Cursor simulado inválido") from exc
        if start < 0 or start > len(self._movements):
            raise ConnectorError(ErrorCode.PARSE_ERROR, "Cursor simulado fora da faixa")
        return MovementBatch(self._movements[start:], str(len(self._movements)))

    def fetch_document(
        self,
        process: ProcessRef,
        document_ref: str,
        target_path: Path,
    ) -> DownloadResult:
        del process
        self._require_valid_session()
        if document_ref not in self._documents:
            raise ConnectorError(ErrorCode.PARSE_ERROR, "Documento simulado não encontrado")
        target_path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary_name = tempfile.mkstemp(prefix=".download-", dir=target_path.parent)
        temporary_path = Path(temporary_name)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(self._documents[document_ref])
                stream.flush()
                os.fsync(stream.fileno())
            os.chmod(temporary_path, 0o600)
            os.replace(temporary_path, target_path)
        finally:
            temporary_path.unlink(missing_ok=True)
        return DownloadResult(target_path, document_ref, datetime.now(UTC))

    def healthcheck(self) -> SourceHealth:
        available = self._session_state is not SessionState.UNAVAILABLE
        return SourceHealth(
            available=available,
            checked_at=datetime.now(UTC),
            latency_ms=0,
            detail="fake connector",
        )
