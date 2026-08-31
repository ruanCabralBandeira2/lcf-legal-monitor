from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from legal_monitor.config import (
    DISCORD_KEYCHAIN_ACCOUNT,
    DISCORD_KEYCHAIN_SERVICE,
    DJEN_PRODUCTION_URL,
    ConfigError,
    Settings,
)


class SettingsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_safe_defaults(self) -> None:
        settings = Settings.from_env({}, root_dir=self.root, load_dotenv=False)
        self.assertFalse(settings.real_connectors_enabled)
        self.assertFalse(settings.whatsapp_enabled)
        self.assertFalse(settings.discord_demo_enabled)
        self.assertEqual(settings.discord_webhook_keychain_service, DISCORD_KEYCHAIN_SERVICE)
        self.assertEqual(settings.discord_webhook_keychain_account, DISCORD_KEYCHAIN_ACCOUNT)
        self.assertFalse(settings.m0_approved)
        self.assertEqual(settings.djen_base_url_prod, DJEN_PRODUCTION_URL)
        self.assertTrue(settings.storage_dir.is_absolute())

    def test_rejects_djen_homologation_host(self) -> None:
        with self.assertRaisesRegex(ConfigError, "homologação"):
            Settings.from_env(
                {"DJEN_BASE_URL_PROD": "https://hcomunicaapi.cnj.jus.br/api/v1"},
                root_dir=self.root,
                load_dotenv=False,
            )

    def test_rejects_real_connector_without_m0_approval(self) -> None:
        with self.assertRaisesRegex(ConfigError, "M0_APPROVED"):
            Settings.from_env(
                {"REAL_CONNECTORS_ENABLED": "true"},
                root_dir=self.root,
                load_dotenv=False,
            )

    def test_production_rejects_development_database_password(self) -> None:
        with self.assertRaisesRegex(ConfigError, "senha fictícia"):
            Settings.from_env(
                {"APP_ENV": "production"},
                root_dir=self.root,
                load_dotenv=False,
            )

    def test_production_accepts_approved_safe_settings(self) -> None:
        settings = Settings.from_env(
            {
                "APP_ENV": "production",
                "DATABASE_URL": "postgresql://legal_monitor:secret-from-keychain@localhost/db",
                "M0_APPROVED": "true",
            },
            root_dir=self.root,
            load_dotenv=False,
        )
        self.assertEqual(settings.app_env.value, "production")

    def test_rejects_backoff_base_greater_than_maximum(self) -> None:
        with self.assertRaisesRegex(ConfigError, "não pode exceder"):
            Settings.from_env(
                {
                    "SCHEDULER_BASE_BACKOFF_SECONDS": "120",
                    "SCHEDULER_MAX_BACKOFF_SECONDS": "60",
                },
                root_dir=self.root,
                load_dotenv=False,
            )

    def test_discord_rejects_invalid_keychain_identifier(self) -> None:
        with self.assertRaisesRegex(ConfigError, "KEYCHAIN_SERVICE"):
            Settings.from_env(
                {"DISCORD_WEBHOOK_KEYCHAIN_SERVICE": "invalid\nservice"},
                root_dir=self.root,
                load_dotenv=False,
            )

    def test_discord_demo_is_forbidden_in_production(self) -> None:
        with self.assertRaisesRegex(ConfigError, "Discord de demonstração"):
            Settings.from_env(
                {
                    "APP_ENV": "production",
                    "DATABASE_URL": "postgresql://legal_monitor:secret@localhost/db",
                    "M0_APPROVED": "true",
                    "DISCORD_DEMO_ENABLED": "true",
                },
                root_dir=self.root,
                load_dotenv=False,
            )


if __name__ == "__main__":
    unittest.main()
