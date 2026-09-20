from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests.real_fixture_guard import verify_available


class RealFixtureIdentityGuardTests(unittest.TestCase):
    def test_missing_is_optional_but_a_different_existing_file_is_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            missing = Path(directory) / "missing.xml"
            verify_available({"boiler_before": missing})

            wrong = Path(directory) / "configured.xml"
            wrong.write_bytes(b"not the recorded schedule")
            with self.assertRaisesRegex(RuntimeError, "does not match its evidence identity"):
                verify_available({"boiler_before": wrong})

    def test_wrong_native_fixture_identity_is_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            wrong = Path(directory) / "after-native.xml"
            wrong.write_bytes(b"not the recorded native schedule")
            with self.assertRaisesRegex(RuntimeError, "does not match its evidence identity"):
                verify_available({"after_native": wrong})

    def test_required_native_mode_fails_when_a_fixture_is_missing(self):
        with tempfile.TemporaryDirectory() as directory:
            missing = Path(directory) / "missing.xml"
            environment = os.environ.copy()
            environment.update(
                {
                    "PYTHONPATH": "src",
                    "STO_REQUIRE_NATIVE": "1",
                    "STO_BOILER_BEFORE": str(missing),
                    "STO_BOILER_AFTER_NATIVE": str(missing),
                    "STO_BOILER_ROUNDTRIP_SAVED": str(missing),
                }
            )
            result = subprocess.run(
                [sys.executable, "-m", "unittest", "tests.test_progress_boiler"],
                cwd=Path(__file__).resolve().parents[1],
                env=environment,
                capture_output=True,
                text=True,
                check=False,
            )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("STO_REQUIRE_NATIVE=1", result.stderr)

    def test_required_day_five_mode_fails_when_the_fixture_is_missing(self):
        with tempfile.TemporaryDirectory() as directory:
            missing = Path(directory) / "missing.xml"
            environment = os.environ.copy()
            environment.update(
                {
                    "PYTHONPATH": "src",
                    "STO_REQUIRE_DAY5": "1",
                    "STO_BOILER_DAY5": str(missing),
                }
            )
            result = subprocess.run(
                [sys.executable, "-m", "unittest", "tests.test_progress_boiler"],
                cwd=Path(__file__).resolve().parents[1],
                env=environment,
                capture_output=True,
                text=True,
                check=False,
            )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("STO_REQUIRE_DAY5=1", result.stderr)
