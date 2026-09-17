"""The V006 upgrade must honor the requested transport and required tools."""

from __future__ import annotations

import os
import unittest
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
            environment = upgrade._environment("sto_upgrade")
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
            environment = upgrade._environment("sto_upgrade")
        for name in ("PGHOST", "PGPORT", "PGUSER", "PGPASSWORD"):
            self.assertNotIn(name, environment)
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
            environment = upgrade._environment("sto_upgrade")
        for name, value in inherited.items():
            self.assertEqual(environment[name], value)
        self.assertEqual(environment["PGDATABASE"], "sto_upgrade")

    def test_unmapped_options_are_refused_not_silently_dropped(self):
        with (
            patch.object(upgrade, "ADMIN_URL", "postgresql:///postgres?unknown_option=value"),
            self.assertRaisesRegex(RuntimeError, "unknown_option"),
        ):
            upgrade._environment("sto_upgrade")


if __name__ == "__main__":
    unittest.main()
