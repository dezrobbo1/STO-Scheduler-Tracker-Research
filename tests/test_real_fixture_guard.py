from __future__ import annotations

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
