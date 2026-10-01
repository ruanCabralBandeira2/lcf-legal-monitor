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


class LoginSequenceTests(unittest.TestCase):
    def test_sites_run_one_after_another_and_failures_do_not_stop(self) -> None:
        from types import SimpleNamespace
        from unittest import mock

        from legal_monitor import cli

        calls: list[str] = []

        def fake_run(site: str, timeout: int) -> int:
            calls.append(site)
            self.assertEqual(timeout, cli.RUN_MAX_SECONDS)
            if site == "b":
                raise RuntimeError("site b caiu")
            return 0

        with tempfile.TemporaryDirectory() as folder:
            settings = SimpleNamespace(temp_dir=Path(folder))
            with mock.patch.object(cli.Settings, "from_env", return_value=settings):
                self.assertEqual(cli.monitor_sequence(["a", "b", "c"], runner=fake_run), 0)
        self.assertEqual(calls, ["a", "b", "c"])

    def test_stuck_site_process_is_killed_and_reported(self) -> None:
        from unittest import mock

        from legal_monitor import cli

        def slow(*args: object, **kwargs: object) -> None:
            import subprocess

            raise subprocess.TimeoutExpired(cmd="monitor-run", timeout=1)

        with mock.patch("subprocess.run", side_effect=slow):
            self.assertEqual(cli._run_site_process("eproc-trf2", 1), 3)

    def test_watchdog_can_be_cancelled(self) -> None:
        from legal_monitor import cli

        timer = cli._start_watchdog("teste", 3600)
        self.assertTrue(timer.daemon)
        timer.cancel()

    def test_default_sequence_has_only_sites_with_readers(self) -> None:
        from legal_monitor.cli import LOGIN_SEQUENCE

        self.assertEqual(LOGIN_SEQUENCE, ("pje-tjrj-1g", "pje-tjrj-2g", "tjrj-portal"))
