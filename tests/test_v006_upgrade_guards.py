"""The V006 upgrade must honor the requested transport and required tools."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import test_v006_upgrade as upgrade


class V006UpgradeGuardTests(unittest.TestCase):
    def test_required_psql_absence_is_failure_not_skip(self):
        with (
            patch.object(upgrade, "psycopg", object()),
            patch.object(upgrade, "REQUIRE_DB", True),
            patch.object(upgrade.shutil, "which", return_value=None),
            self.assertRaisesRegex(RuntimeError, "STO_REQUIRE_DB=1.*psql"),
        ):
            upgrade._reachable()

    def test_optional_psql_absence_remains_a_skip(self):
        with (
            patch.object(upgrade, "psycopg", object()),
            patch.object(upgrade, "REQUIRE_DB", False),
            patch.object(upgrade.shutil, "which", return_value=None),
        ):
            self.assertFalse(upgrade._reachable())

    def test_database_and_migrator_keep_nondefault_connection_options(self):
        source = (
            "postgresql://operator:p%40ss@db.example:6543/postgres"
            "?sslmode=require&application_name=upgrade-test&connect_timeout=11"
        )
        with patch.object(upgrade, "ADMIN_URL", source), patch.dict(os.environ, {}, clear=True):
            environment = upgrade._environment("sto_upgrade", host="db.example", port=6543, user="operator")
        self.assertEqual(environment["PGHOST"], "db.example")
        self.assertEqual(environment["PGPORT"], "6543")
        self.assertEqual(environment["PGUSER"], "operator")
        self.assertEqual(environment["PGPASSWORD"], "p@ss")
        self.assertEqual(environment["PGDATABASE"], "sto_upgrade")
        self.assertEqual(environment["PGSSLMODE"], "require")
        self.assertEqual(environment["PGAPPNAME"], "upgrade-test")
        self.assertEqual(environment["PGCONNECT_TIMEOUT"], "11")
        self.assertEqual(
            upgrade._database_url(source, "sto_upgrade"),
            source.replace("/postgres?", "/sto_upgrade?"),
        )

    def test_socket_url_does_not_manufacture_tcp_defaults(self):
        source = "postgresql:///postgres?sslmode=disable"
        with patch.object(upgrade, "ADMIN_URL", source), patch.dict(os.environ, {}, clear=True):
            environment = upgrade._environment("sto_upgrade", host="/var/run/postgresql", port=5432, user="peer-user")
        self.assertEqual(environment["PGHOST"], "/var/run/postgresql")
        self.assertEqual(environment["PGPORT"], "5432")
        self.assertEqual(environment["PGUSER"], "peer-user")
        self.assertNotIn("PGPASSWORD", environment)
        self.assertEqual(environment["PGDATABASE"], "sto_upgrade")
        self.assertEqual(environment["PGSSLMODE"], "disable")
        self.assertEqual(
            upgrade._database_url(source, "sto_upgrade"),
            "postgresql:///sto_upgrade?sslmode=disable",
        )

    def test_socket_url_preserves_inherited_libpq_settings(self):
        inherited = {"PGHOST": "/var/run/postgresql", "PGPORT": "5544", "PGUSER": "peer-user"}
        with (
            patch.object(upgrade, "ADMIN_URL", "postgresql:///postgres"),
            patch.dict(os.environ, inherited, clear=True),
        ):
            environment = upgrade._environment("sto_upgrade", host=inherited["PGHOST"], port=5544, user=inherited["PGUSER"])
        for name, value in inherited.items():
            self.assertEqual(environment[name], value)
        self.assertEqual(environment["PGDATABASE"], "sto_upgrade")

    def test_unmapped_options_are_refused_not_silently_dropped(self):
        with (
            patch.object(upgrade, "ADMIN_URL", "postgresql:///postgres?unknown_option=value"),
            self.assertRaisesRegex(RuntimeError, "unknown_option"),
        ):
            upgrade._environment("sto_upgrade", host="/var/run/postgresql", port=5432, user="peer-user")

    def test_uri_options_keep_literal_plus_and_percent_decoding_through_scripts(self):
        shell = shutil.which("sh")
        if shell is None:
            self.skipTest("POSIX sh is required for the migration-script boundary")
        source = (
            "postgresql://operator:p+%2B%20%252B@db.example:6543/postgres"
            "?sslcert=%2Ftmp%2Fclient+one%2Btwo%20three%252B%26%3D.pem"
            "&application_name=upgrade+one%2Btwo%20three%252B"
            "&options=-c%20application_name%3Dsession+one%2Btwo%20three%252B"
        )
        expected = [
            "/tmp/client+one+two three%2B&=.pem",
            "upgrade+one+two three%2B",
            "-c application_name=session+one+two three%2B",
            "p++ %2B",
        ]
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            fake_psql = temporary / "psql"
            fake_psql.write_text(
                '#!/bin/sh\nprintf "%s\\n" "$PGSSLCERT" "$PGAPPNAME" '
                '"$PGOPTIONS" "$PGPASSWORD" > "$STO_PSQL_CAPTURE"\nexit 73\n',
                encoding="utf-8",
            )
            fake_psql.chmod(0o700)
            with (
                patch.object(upgrade, "ADMIN_URL", source),
                patch.dict(os.environ, {"PATH": str(temporary) + os.pathsep + os.defpath}, clear=True),
            ):
                environment = upgrade._environment(
                    "sto_upgrade", host="db.example", port=6543, user="operator"
                )
            self.assertEqual(
                upgrade._database_url(source, "sto_upgrade"),
                source.replace("/postgres?", "/sto_upgrade?"),
            )
            for name in ("apply-migrations.sh", "check-schema-drift.sh"):
                with self.subTest(script=name):
                    capture = temporary / "options.txt"
                    capture.unlink(missing_ok=True)
                    result = subprocess.run(
                        [shell, str(upgrade.ROOT / "scripts" / "db" / name)],
                        env=environment | {"STO_PSQL_CAPTURE": str(capture)},
                        capture_output=True, text=True, timeout=10,
                    )
                    self.assertNotEqual(result.returncode, 0)
                    self.assertTrue(capture.exists(), result.stdout + result.stderr)
                    self.assertEqual(capture.read_text(encoding="utf-8").splitlines(), expected)

    def test_resolved_endpoint_survives_both_real_shell_entry_points(self):
        shell = shutil.which("sh")
        if shell is None:
            self.skipTest("POSIX sh is required for the migration-script boundary")
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            fake_psql = temporary / "psql"
            # Stop before any database command: this probe inspects the actual
            # scripts' subprocess environment, not a copy of their shell logic.
            fake_psql.write_text(
                '#!/bin/sh\nprintf "%s\\n" "$PGHOST" "$PGPORT" "$PGUSER" '
                '"$PGDATABASE" "$PGSSLMODE" > "$STO_PSQL_CAPTURE"\nexit 73\n',
                encoding="utf-8",
            )
            fake_psql.chmod(0o700)
            cases = (
                ("postgresql:///postgres?sslmode=disable", "/var/run/postgresql", 5432, "peer-user", "disable"),
                ("postgresql://operator@db.example:6543/postgres?sslmode=require", "db.example", 6543, "operator", "require"),
                ("postgresql:///postgres?host=%2Fvar%2Frun%2Fpostgresql&sslmode=disable", "/var/run/postgresql", 5432, "peer-user", "disable"),
                ("postgresql:///postgres?port=5544&sslmode=disable", "/var/run/postgresql", 5544, "peer-user", "disable"),
                ("postgresql:///postgres?user=peer%2Duser&sslmode=disable", "/var/run/postgresql", 5432, "peer-user", "disable"),
                (
                    "postgresql://ignored@db.example:6543/postgres"
                    "?host=%2Ftmp%2Fsto+socket&port=5544&user=peer%2Duser&sslmode=disable",
                    "/tmp/sto+socket", 5544, "peer-user", "disable",
                ),
            )
            for source, host, port, user, sslmode in cases:
                with (
                    patch.object(upgrade, "ADMIN_URL", source),
                    patch.dict(os.environ, {"PATH": str(temporary) + os.pathsep + os.defpath}, clear=True),
                ):
                    environment = upgrade._environment(
                        "sto_upgrade", host=host, port=port, user=user
                    )
                for name in ("apply-migrations.sh", "check-schema-drift.sh"):
                    with self.subTest(source=source, script=name):
                        capture = temporary / "connection.txt"
                        capture.unlink(missing_ok=True)
                        result = subprocess.run(
                            [shell, str(upgrade.ROOT / "scripts" / "db" / name)],
                            env=environment | {"STO_PSQL_CAPTURE": str(capture)},
                            capture_output=True, text=True, timeout=10,
                        )
                        self.assertNotEqual(result.returncode, 0)
                        self.assertTrue(capture.exists(), result.stdout + result.stderr)
                        self.assertEqual(
                            capture.read_text(encoding="utf-8").splitlines(),
                            [host, str(port), user, "sto_upgrade", sslmode],
                        )


if __name__ == "__main__":
    unittest.main()
