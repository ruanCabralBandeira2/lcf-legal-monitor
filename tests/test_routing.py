from __future__ import annotations

import unittest

from legal_monitor.connectors.routing import (
    CATALOG,
    SourceEndpoint,
    UnknownSourceError,
    candidate_sources,
    get_endpoint,
)
from legal_monitor.domain.cnj import CnjNumber
from legal_monitor.domain.enums import SourceSystem


def _cnj(justice: int, tribunal: int) -> CnjNumber:
    return CnjNumber.from_components(
        sequence=1, year=2026, justice=justice, tribunal=tribunal, origin=1
    )


class RoutingTests(unittest.TestCase):
    def test_tjrj_routes_to_eproc_then_pdpj(self) -> None:
        keys = [item.key for item in candidate_sources(_cnj(8, 19))]
        self.assertEqual(keys, ["eproc-tjrj-1g", "eproc-tjrj-2g", "pdpj"])

    def test_trf2_routes_to_eproc_trf2(self) -> None:
        keys = [item.key for item in candidate_sources(_cnj(4, 2))]
        self.assertEqual(keys, ["eproc-trf2", "pdpj"])

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
