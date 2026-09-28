from __future__ import annotations

import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

from legal_monitor.documents.service import DocumentService, DocumentValidationError
from legal_monitor.domain.cnj import CnjNumber
from legal_monitor.domain.enums import SourceSystem
from legal_monitor.domain.models import ProcessRef
from tests.helpers import blank_pdf_bytes


class DocumentServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.process = ProcessRef(
            CnjNumber.from_components(
                sequence=1,
                year=2026,
                justice=8,
                tribunal=19,
                origin=1,
            ),
            current_system=SourceSystem.FAKE,
        )
        self.observed = datetime(2026, 8, 30, 18, tzinfo=UTC)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_stores_valid_pdf_with_reproducible_hash(self) -> None:
        source = self.root / "source.pdf"
        source.write_bytes(blank_pdf_bytes(2))
        service = DocumentService(self.root / "documents")
        first = service.store_pdf(
            source,
            process=self.process,
            movement_type="Decisão Interlocutória",
            observed_at=self.observed,
        )
        second = service.store_pdf(
            source,
            process=self.process,
            movement_type="Decisão Interlocutória",
            observed_at=self.observed,
        )
        self.assertEqual(first.sha256, second.sha256)
        self.assertEqual(first.page_count, 2)
        self.assertTrue(first.storage_path.exists())
        self.assertFalse(first.already_existed)
        self.assertTrue(second.already_existed)
        self.assertIn("tjrj/2026/00000016920268190001", first.storage_path.as_posix())

    def test_rejects_non_pdf(self) -> None:
        source = self.root / "malicious.pdf"
        source.write_text("not a pdf", encoding="utf-8")
        with self.assertRaisesRegex(DocumentValidationError, "Assinatura PDF"):
            DocumentService(self.root / "documents").store_pdf(
                source,
                process=self.process,
                movement_type="decisao",
                observed_at=self.observed,
            )

    def test_rejects_symlink(self) -> None:
        original = self.root / "original.pdf"
        original.write_bytes(blank_pdf_bytes())
        link = self.root / "link.pdf"
        try:
            link.symlink_to(original)
        except OSError:
            self.skipTest("Sistema sem permissão para criar links simbólicos (Windows)")
        with self.assertRaisesRegex(DocumentValidationError, "simbólicos"):
            DocumentService(self.root / "documents").store_pdf(
                link,
                process=self.process,
                movement_type="decisao",
                observed_at=self.observed,
            )


if __name__ == "__main__":
    unittest.main()
