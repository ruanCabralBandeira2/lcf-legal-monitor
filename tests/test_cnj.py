from __future__ import annotations

import unittest

from legal_monitor.domain.cnj import CnjNumber, InvalidCnjNumber


class CnjNumberTests(unittest.TestCase):
    def test_builds_and_validates_fictitious_tjrj_number(self) -> None:
        cnj = CnjNumber.from_components(
            sequence=1,
            year=2026,
            justice=8,
            tribunal=19,
            origin=1,
        )
        self.assertEqual(str(cnj), "0000001-69.2026.8.19.0001")
        self.assertEqual(cnj.digits, "00000016920268190001")
        self.assertEqual(cnj.tribunal_code, "19")

    def test_accepts_compact_representation(self) -> None:
        self.assertEqual(
            str(CnjNumber.parse("00000016920268190001")),
            "0000001-69.2026.8.19.0001",
        )

    def test_rejects_invalid_check_digits(self) -> None:
        with self.assertRaises(InvalidCnjNumber):
            CnjNumber.parse("0000001-68.2026.8.19.0001")

    def test_masks_sequence_and_origin(self) -> None:
        cnj = CnjNumber.parse("0000001-69.2026.8.19.0001")
        self.assertEqual(cnj.masked(), "*******-**.2026.*.**.****")


if __name__ == "__main__":
    unittest.main()
