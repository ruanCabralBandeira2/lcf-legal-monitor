from __future__ import annotations

import subprocess
import unittest
from unittest.mock import patch

from legal_monitor.notifications.keychain import KeychainSecretError, MacOSKeychainSecretProvider


class KeychainSecretTests(unittest.TestCase):
    @patch("legal_monitor.notifications.keychain.subprocess.run")
    def test_reads_secret_without_putting_it_in_command(self, run_mock) -> None:
        secret = "https://discord.com/api/webhooks/123/token-ficticio-seguro-1234567890"  # noqa: S105
        run_mock.return_value = subprocess.CompletedProcess([], 0, stdout=f"{secret}\n", stderr="")

        result = MacOSKeychainSecretProvider().get(
            service="com.lcf.legal-monitor.discord.webhook",
            account="local-monitor",
        )

        self.assertEqual(result, secret)
        command = run_mock.call_args.args[0]
        self.assertNotIn(secret, command)
        self.assertEqual(command[0], "/usr/bin/security")

    @patch("legal_monitor.notifications.keychain.subprocess.run")
    def test_not_found_error_does_not_expose_stderr(self, run_mock) -> None:
        run_mock.return_value = subprocess.CompletedProcess(
            [], 44, stdout="", stderr="conteudo-sensivel"
        )

        with self.assertRaises(KeychainSecretError) as raised:
            MacOSKeychainSecretProvider().get(service="service", account="account")
        self.assertNotIn("conteudo-sensivel", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
