from __future__ import annotations

import hashlib
import os
import re
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from legal_monitor.domain.models import DocumentRecord, ProcessRef

SAFE_NAME = re.compile(r"[^a-z0-9]+")


class DocumentValidationError(ValueError):
    """Arquivo não atende aos critérios mínimos de integridade."""


class DocumentService:
    def __init__(self, storage_dir: Path, *, max_bytes: int = 52_428_800) -> None:
        self.storage_dir = storage_dir.resolve()
        self.max_bytes = max_bytes

    def store_pdf(
        self,
        source_path: Path,
        *,
        process: ProcessRef,
        movement_type: str,
        observed_at: datetime,
    ) -> DocumentRecord:
        if observed_at.tzinfo is None:
            raise DocumentValidationError("observed_at precisa conter fuso horário")
        if source_path.is_symlink():
            raise DocumentValidationError("Links simbólicos não são aceitos como documento")
        if not source_path.is_file():
            raise DocumentValidationError("Documento de origem não encontrado")

        collected_at = datetime.now(UTC)
        logical_dir = (
            self.storage_dir
            / self._safe_segment(process.tribunal)
            / f"{observed_at.year:04d}"
            / process.cnj.digits
        )
        logical_dir.mkdir(parents=True, exist_ok=True, mode=0o700)

        fd, temporary_name = tempfile.mkstemp(prefix=".pending-", suffix=".pdf", dir=logical_dir)
        temporary_path = Path(temporary_name)
        digest = hashlib.sha256()
        total = 0
        try:
            with source_path.open("rb") as source, os.fdopen(fd, "wb") as target:
                first = source.read(5)
                if first != b"%PDF-":
                    raise DocumentValidationError("Assinatura PDF ausente ou inválida")
                target.write(first)
                digest.update(first)
                total += len(first)
                while chunk := source.read(1024 * 1024):
                    total += len(chunk)
                    if total > self.max_bytes:
                        raise DocumentValidationError("Documento excede o limite configurado")
                    target.write(chunk)
                    digest.update(chunk)
                target.flush()
                os.fsync(target.fileno())
            os.chmod(temporary_path, 0o600)
            page_count, text_extractable = self._inspect_pdf(temporary_path)
            sha256 = digest.hexdigest()
            timestamp = observed_at.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
            kind = self._safe_segment(movement_type) or "documento"
            filename = f"{timestamp}_{kind}_{sha256[:12]}.pdf"
            destination = logical_dir / filename

            already_existed = False
            try:
                os.link(temporary_path, destination)
            except FileExistsError as exc:
                if self._sha256(destination) != sha256:
                    raise DocumentValidationError(
                        "Colisão de nome com conteúdo divergente"
                    ) from exc
                already_existed = True
            friendly = f"{kind}_{observed_at.astimezone(UTC).strftime('%Y%m%d')}.pdf"
            return DocumentRecord(
                storage_path=destination,
                friendly_name=friendly,
                mime="application/pdf",
                bytes=total,
                page_count=page_count,
                sha256=sha256,
                collected_at=collected_at,
                text_extractable=text_extractable,
                already_existed=already_existed,
            )
        finally:
            temporary_path.unlink(missing_ok=True)

    @staticmethod
    def _inspect_pdf(path: Path) -> tuple[int, bool]:
        try:
            from pypdf import PdfReader
        except ImportError as exc:
            raise DocumentValidationError("Dependência pypdf não instalada") from exc
        try:
            reader = PdfReader(path, strict=True)
            if reader.is_encrypted:
                raise DocumentValidationError("PDF criptografado exige fluxo humano específico")
            page_count = len(reader.pages)
            if page_count < 1:
                raise DocumentValidationError("PDF não contém páginas")
            text_extractable = any(
                bool((reader.pages[index].extract_text() or "").strip())
                for index in range(min(page_count, 3))
            )
            return page_count, text_extractable
        except DocumentValidationError:
            raise
        except Exception as exc:
            raise DocumentValidationError("PDF corrompido ou ilegível") from exc

    @staticmethod
    def _safe_segment(value: str) -> str:
        normalized = value.strip().lower()
        return SAFE_NAME.sub("-", normalized).strip("-")[:80]

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
        return digest.hexdigest()
