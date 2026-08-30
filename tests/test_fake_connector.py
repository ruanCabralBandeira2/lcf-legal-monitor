from __future__ import annotations

import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

from legal_monitor.connectors.errors import AuthenticationRequired
from legal_monitor.connectors.fake import FakeConnector
from legal_monitor.domain.cnj import CnjNumber
from legal_monitor.domain.enums import SessionState, SourceSystem
from legal_monitor.domain.models import Movement, ProcessRef
from tests.helpers import blank_pdf_bytes


def _process() -> ProcessRef:
    return ProcessRef(
        CnjNumber.from_components(
            sequence=1,
            year=2026,
            justice=8,
            tribunal=19,
            origin=1,
        ),
        current_system=SourceSystem.FAKE,
    )


class FakeConnectorTests(unittest.TestCase):
    def test_cursor_and_document_download_are_deterministic(self) -> None:
        observed = datetime(2026, 8, 30, tzinfo=UTC)
        movement = Movement(
            source=SourceSystem.FAKE,
            source_event_id="fixture-1",
            event_at=observed,
            observed_at=observed,
            type_raw="Decisão",
            type_normalized="decisao",
            description="Fixture",
            document_ref="doc-1",
        )
        connector = FakeConnector(
            movements=(movement,),
            documents={"doc-1": blank_pdf_bytes()},
        )
        first = connector.list_movements(_process(), None)
        second = connector.list_movements(_process(), first.next_cursor)
        self.assertEqual(first.movements, (movement,))
        self.assertEqual(second.movements, ())
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "doc.pdf"
            connector.fetch_document(_process(), "doc-1", target)
            self.assertTrue(target.read_bytes().startswith(b"%PDF-"))

    def test_auth_required_never_returns_empty_success(self) -> None:
        connector = FakeConnector(session_state=SessionState.AUTH_REQUIRED)
        with self.assertRaises(AuthenticationRequired):
            connector.list_movements(_process(), None)


if __name__ == "__main__":
    unittest.main()
