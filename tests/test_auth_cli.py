"""The first-user workflow accepts passwords only from an interactive prompt."""

from __future__ import annotations

import argparse
import io
import unittest
import uuid
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

from sto.cli.main import build_parser

try:
    import sto.api.auth  # noqa: F401 - availability gate for the optional edge
except ImportError:
    AUTH_EXTRA = False
else:
    AUTH_EXTRA = True


class _BootstrapService:
    def bootstrap_admin(self, **kwargs):
        assert kwargs["password"] == "synthetic-interactive-password"
        return (
            {"id": uuid.UUID("11111111-1111-1111-1111-111111111111"), "username": "trial-admin"},
            "SYNTHETICENROLMENTSECRET",
            "otpauth://totp/STO:trial-admin?secret=SYNTHETICENROLMENTSECRET",
        )


class AuthCliTests(unittest.TestCase):
    @unittest.skipUnless(AUTH_EXTRA, "the interactive handler needs the optional api extra")
    def test_bootstrap_password_is_prompted_not_parsed_from_the_command_line(self):
        args = build_parser().parse_args(["auth", "bootstrap-admin", "trial-admin"])
        self.assertIsInstance(args, argparse.Namespace)
        self.assertFalse(hasattr(args, "password"))
        output = io.StringIO()
        with (
            patch(
                "sto.cli.auth.getpass.getpass",
                side_effect=["synthetic-interactive-password"] * 2,
            ),
            patch("sto.cli.auth._service", return_value=_BootstrapService()),
            redirect_stdout(output),
        ):
            self.assertEqual(args.handler(args), 0)
        shown = output.getvalue()
        self.assertIn("shown once", shown)
        self.assertIn("sto auth grant-project", shown)

    def test_bootstrap_parser_has_no_password_option(self):
        with redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                build_parser().parse_args(
                    [
                        "auth",
                        "bootstrap-admin",
                        "trial-admin",
                        "--password",
                        "must-not-enter-shell-history",
                    ]
                )


if __name__ == "__main__":
    unittest.main()
