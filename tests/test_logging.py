from __future__ import annotations

import json
import logging
import unittest

from legal_monitor.logging import JsonFormatter, redact


class LoggingTests(unittest.TestCase):
    def test_redacts_cnj_and_cpf(self) -> None:
        value = redact("Processo 0000001-69.2026.8.19.0001 CPF 123.456.789-00")
        self.assertNotIn("0000001", value)
        self.assertNotIn("123.456", value)

    def test_formatter_emits_json_without_traceback_content(self) -> None:
        record = logging.LogRecord(
            name="test",
            level=logging.ERROR,
            pathname=__file__,
            lineno=1,
            msg="Falha no processo 0000001-69.2026.8.19.0001",
            args=(),
            exc_info=None,
        )
        payload = json.loads(JsonFormatter().format(record))
        self.assertEqual(payload["level"], "ERROR")
        self.assertNotIn("0000001", payload["message"])


if __name__ == "__main__":
    unittest.main()
