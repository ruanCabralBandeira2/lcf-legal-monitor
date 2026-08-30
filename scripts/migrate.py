from __future__ import annotations

import hashlib
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from legal_monitor.config import Settings  # noqa: E402

LOCK_ID = 4_819_202_608_30


def main() -> int:
    try:
        import psycopg
    except ImportError:
        print("psycopg não instalado; execute: python -m pip install -r requirements.lock")
        return 2

    settings = Settings.from_env(root_dir=PROJECT_ROOT)
    database_url = settings.database_url.replace("postgresql+psycopg://", "postgresql://", 1)
    migration_files = sorted((PROJECT_ROOT / "migrations").glob("[0-9][0-9][0-9]_*.sql"))
    if not migration_files:
        print("Nenhuma migração encontrada")
        return 1

    with psycopg.connect(database_url) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migration (
                version text PRIMARY KEY,
                sha256 char(64) NOT NULL,
                applied_at timestamptz NOT NULL DEFAULT now()
            )
            """
        )
        connection.execute("SELECT pg_advisory_xact_lock(%s)", (LOCK_ID,))
        applied_rows = connection.execute(
            "SELECT version, sha256 FROM schema_migration"
        ).fetchall()
        applied = dict(applied_rows)
        for path in migration_files:
            version = path.name.split("_", 1)[0]
            sql = path.read_text(encoding="utf-8")
            checksum = hashlib.sha256(sql.encode("utf-8")).hexdigest()
            if version in applied:
                if applied[version] != checksum:
                    raise RuntimeError(f"Migração aplicada foi alterada: {path.name}")
                print(f"{path.name}: já aplicada")
                continue
            connection.execute(sql)
            connection.execute(
                "INSERT INTO schema_migration (version, sha256) VALUES (%s, %s)",
                (version, checksum),
            )
            print(f"{path.name}: aplicada")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
