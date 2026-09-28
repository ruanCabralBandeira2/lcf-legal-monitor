from __future__ import annotations

import unittest

from legal_monitor.connectors.routing import (
    CATALOG,
    SourceEndpoint,
    UnknownSourceError,
    candidate_keys,
    candidate_sources,
    get_endpoint,
    tribunal_for,
)
from legal_monitor.domain.cnj import CnjNumber
from legal_monitor.domain.enums import SourceSystem


def _cnj(justice: int, tribunal: int, *, origin: int = 1) -> CnjNumber:
    return CnjNumber.from_components(
        sequence=1, year=2026, justice=justice, tribunal=tribunal, origin=origin
    )


class RoutingTests(unittest.TestCase):
    def test_tjrj_legacy_numbering_routes_eproc_then_portal(self) -> None:
        keys = [item.key for item in candidate_sources(_cnj(8, 19))]
        self.assertEqual(
            keys,
            ["eproc-tjrj-1g", "tjrj-portal", "pje-tjrj-1g", "eproc-tjrj-2g", "pje-tjrj-2g", "pdpj"],
        )

    def test_tjrj_portal_uses_certificate_image_and_official_host(self) -> None:
        portal = CATALOG["tjrj-portal"]
        self.assertIs(portal.system, SourceSystem.LEGACY_DCP)
        self.assertEqual(portal.host, "www3.tjrj.jus.br")
        self.assertIn("user-card", portal.certificate_login_selector or "")

    def test_pje_tjrj_shares_jusbr_login_and_is_marked_headless_blocked(self) -> None:
        pje = CATALOG["pje-tjrj-1g"]
        self.assertIs(pje.system, SourceSystem.PJE)
        self.assertEqual(pje.auth_realm, "jusbr")
        self.assertTrue(pje.headless_blocked)

    def test_trf2_first_instance_goes_to_jfrj_then_trf2(self) -> None:
        keys = [item.key for item in candidate_sources(_cnj(4, 2, origin=5101))]
        self.assertEqual(keys, ["eproc-jfrj-1g", "eproc-trf2", "pdpj"])

    def test_second_instance_origin_0000_goes_to_tribunal_first(self) -> None:
        self.assertEqual(candidate_keys(_cnj(4, 2, origin=0))[0], "eproc-trf2")
        self.assertEqual(candidate_keys(_cnj(8, 19, origin=0))[0], "eproc-tjrj-2g")
        self.assertEqual(candidate_keys(_cnj(4, 4, origin=0))[0], "eproc-trf4-2g")
        self.assertEqual(candidate_keys(_cnj(5, 1, origin=0))[0], "pje-trt1-2g")

    def test_tjrj_pje_numbering_tries_pje_first(self) -> None:
        cnj = CnjNumber.from_components(
            sequence=876_543, year=2025, justice=8, tribunal=19, origin=209
        )
        self.assertEqual(
            candidate_keys(cnj),
            ("pje-tjrj-1g", "eproc-tjrj-1g", "pje-tjrj-2g", "eproc-tjrj-2g", "pdpj"),
        )

    def test_labor_court_routes_to_pje_trt1(self) -> None:
        self.assertEqual(candidate_keys(_cnj(5, 1, origin=29))[:2], ("pje-trt1-1g", "pje-trt1-2g"))

    def test_supported_tribunals(self) -> None:
        self.assertEqual(tribunal_for(_cnj(8, 19)), "TJRJ")
        self.assertEqual(tribunal_for(_cnj(5, 1)), "TRT1")
        self.assertEqual(tribunal_for(_cnj(4, 4, origin=0)), "TRF4")
        self.assertIsNone(tribunal_for(_cnj(8, 26)))

    def test_unknown_tribunal_falls_back_to_pdpj(self) -> None:
        self.assertEqual([item.key for item in candidate_sources(_cnj(8, 26))], ["pdpj"])

    def test_jusbr_sources_share_login_realm(self) -> None:
        self.assertEqual(CATALOG["eproc-tjrj-1g"].auth_realm, CATALOG["pdpj"].auth_realm)
        self.assertNotEqual(CATALOG["eproc-trf2"].auth_realm, CATALOG["pdpj"].auth_realm)

    def test_catalog_only_official_https_hosts(self) -> None:
        for endpoint in CATALOG.values():
            self.assertTrue(endpoint.base_url.startswith("https://"))
            self.assertTrue(endpoint.host.endswith(".jus.br"))
        with self.assertRaises(ValueError):
            SourceEndpoint("x", "X", SourceSystem.EPROC, "https://evil.example/", "r", "n")

    def test_unknown_source_key(self) -> None:
        with self.assertRaises(UnknownSourceError):
            get_endpoint("nao-existe")


if __name__ == "__main__":
    unittest.main()
