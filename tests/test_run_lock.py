from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from legal_monitor.cli import _run_lock


class RunLockTests(unittest.TestCase):
    def test_second_run_of_same_site_is_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "rodada-tjrj-portal.lock"
            with _run_lock(path) as first:
                self.assertTrue(first)
                with _run_lock(path) as second:
                    self.assertFalse(second)
            with _run_lock(path) as again:
                self.assertTrue(again)

    def test_different_sites_do_not_block_each_other(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            with _run_lock(Path(folder) / "rodada-a.lock") as a:
                with _run_lock(Path(folder) / "rodada-b.lock") as b:
                    self.assertTrue(a and b)


if __name__ == "__main__":
    unittest.main()
