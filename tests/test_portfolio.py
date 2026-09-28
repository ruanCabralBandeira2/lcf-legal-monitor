from __future__ import annotations

import unittest

from legal_monitor.admin.portfolio import parse_portfolio
from legal_monitor.domain.cnj import CnjNumber
from legal_monitor.domain.enums import Sensitivity


def _n(sequence: int, year: int, justice: int, tribunal: int, origin: int) -> str:
    return str(
        CnjNumber.from_components(
            sequence=sequence, year=year, justice=justice, tribunal=tribunal, origin=origin
        )
    )


class PortfolioTests(unittest.TestCase):
    def test_parses_separates_by_site_and_flags(self) -> None:
        tjrj_legacy = _n(12345, 2022, 8, 19, 1)
        tjrj_pje = _n(876543, 2025, 8, 19, 209)
        jfrj = _n(5000001, 2025, 4, 2, 5101)
        trt = _n(100001, 2026, 5, 1, 29)
        trf4 = _n(5000002, 2026, 4, 4, 0).replace("-", ".", 1)  # formato vindo do Astrea
        text = "\n".join(
            [
                "# comentário",
                tjrj_legacy,
                f"{tjrj_pje};RESTRICTED",
                jfrj,
                jfrj,  # duplicado
                trt,
                trf4,
                "04/353.021/2020",  # processo administrativo, não é CNJ
                "0000001-00.2026.8.19.0001",  # dígito verificador errado
                "",
            ]
        )
        portfolio = parse_portfolio(text)
        self.assertEqual(len(portfolio.entries), 5)
        self.assertEqual(portfolio.duplicates, 1)
        self.assertEqual(portfolio.not_cnj, ["04/353.021/2020"])
        self.assertEqual(portfolio.invalid, ["0000001-00.2026.8.19.0001"])
        sites = {site: len(entries) for site, entries in portfolio.by_site().items()}
        self.assertEqual(
            sites,
            {
                "eproc-tjrj-1g": 1,
                "pje-tjrj-1g": 1,
                "eproc-jfrj-1g": 1,
                "pje-trt1-1g": 1,
                "eproc-trf4-2g": 1,
            },
        )
        restricted = [e for e in portfolio.entries if e.sensitivity is Sensitivity.RESTRICTED]
        self.assertEqual([str(e.cnj) for e in restricted], [tjrj_pje])

    def test_site_override_for_appeal_in_tribunal(self) -> None:
        number = _n(12345, 2015, 4, 2, 5101)
        portfolio = parse_portfolio(f"{number};SITE=eproc-trf2\n{_n(1, 2026, 4, 2, 5101)};SITE=xx")
        self.assertEqual(portfolio.entries[0].likely_site, "eproc-trf2")
        self.assertEqual(len(portfolio.entries), 1)
        self.assertIn("site desconhecido", portfolio.invalid[0])

    def test_unsupported_tribunal_goes_to_no_robot_bucket(self) -> None:
        portfolio = parse_portfolio(_n(1, 2026, 8, 26, 1))  # TJSP
        self.assertEqual(list(portfolio.by_site()), ["sem-robo"])


if __name__ == "__main__":
    unittest.main()
