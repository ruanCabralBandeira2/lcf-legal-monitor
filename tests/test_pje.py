from __future__ import annotations

import unittest
from datetime import UTC, datetime
from pathlib import Path

from legal_monitor.connectors.pje import (
    FORBIDDEN_CONTROL,
    PjeConnector,
    items_from_payload,
    parse_pje_date,
)
from legal_monitor.connectors.routing import CATALOG
from legal_monitor.domain.cnj import CnjNumber
from legal_monitor.domain.models import DocumentRecord
from legal_monitor.monitoring.latest import build_movement_message

CNJ = CnjNumber.from_components(sequence=1, year=2026, justice=8, tribunal=19, origin=1)


class PjeParsingTests(unittest.TestCase):
    def test_parse_pje_dates(self) -> None:
        self.assertEqual(parse_pje_date("28 set. 2026"), datetime(2026, 9, 28, tzinfo=UTC))
        self.assertEqual(parse_pje_date("05 MAR 2025"), datetime(2025, 3, 5, tzinfo=UTC))
        self.assertEqual(parse_pje_date("01/02/2026 10:00"), datetime(2026, 2, 1, tzinfo=UTC))
        self.assertIsNone(parse_pje_date("sem data"))

    def test_items_from_payload_extracts_document_ids(self) -> None:
        payload = {
            "found": True,
            "items": [
                {
                    "date": "28 set. 2026",
                    "text": "Decisão (fictícia)",
                    "docs": [
                        {"tag": "0-0", "label": "Decisão", "hint": "x?idProcessoDocumento=987"}
                    ],
                },
                {"date": "27 set. 2026", "text": "Conclusos", "docs": []},
            ],
        }
        items = items_from_payload(payload)
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0].documents[0].document_id, "987")
        self.assertEqual(items[0].event_date, datetime(2026, 9, 28, tzinfo=UTC))
        self.assertEqual(items[1].documents, ())

    def test_write_controls_are_forbidden(self) -> None:
        for label in ("Peticionar", "Assinar documento", "Dar ciência", "Expedientes", "Sair"):
            self.assertTrue(FORBIDDEN_CONTROL.search(label), label)
        for label in ("Decisão", "Juntada de petição", "Despacho", "Sentença"):
            self.assertFalse(FORBIDDEN_CONTROL.search(label), label)

    def test_consulta_url_is_official_pje(self) -> None:
        connector = PjeConnector(CATALOG["pje-tjrj-1g"])
        self.assertEqual(
            connector.consulta_url,
            "https://tjrj.pje.jus.br/1g/Processo/ConsultaProcesso/listView.seam",
        )
        with self.assertRaises(ValueError):
            PjeConnector(CATALOG["eproc-tjrj-1g"])


class MovementMessageTests(unittest.TestCase):
    def test_message_with_attachment_and_warning(self) -> None:
        item = items_from_payload(
            {"items": [{"date": "28 set. 2026", "text": "Decisão fictícia", "docs": []}]}
        )[0]
        record = DocumentRecord(
            storage_path=Path("x/doc.pdf"),
            friendly_name="decisao_20260928.pdf",
            mime="application/pdf",
            bytes=100,
            page_count=2,
            sha256="a" * 64,
            collected_at=datetime(2026, 9, 28, tzinfo=UTC),
            text_extractable=True,
        )
        message = build_movement_message(CNJ, CATALOG["pje-tjrj-1g"], item, record, attached=True)
        self.assertIn(str(CNJ), message.title)
        self.assertIn("prazo não calculado", message.body)
        self.assertEqual(len(message.attachments), 1)
        long_item = items_from_payload({"items": [{"date": None, "text": "x" * 5000, "docs": []}]})[
            0
        ]
        short = build_movement_message(CNJ, CATALOG["pje-tjrj-1g"], long_item, None, attached=False)
        self.assertLessEqual(len(short.render_text()), 2000)


if __name__ == "__main__":
    unittest.main()
