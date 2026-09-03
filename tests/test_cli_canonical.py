"""The ``sto`` command line over the canonical model."""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from sto.cli import main

FIXTURES = Path(__file__).resolve().parent / "fixtures"
SYNTHETIC = FIXTURES / "synthetic-basic.mspdi.xml"
CHAIN = FIXTURES / "synthetic-workspace-chain.mspdi.xml"


class CanonicaliseCommandTests(unittest.TestCase):
    def test_summary_reports_identity_hash_and_counts(self):
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            exit_code = main(["canonicalise", str(SYNTHETIC), "--quiet"])
        output = buffer.getvalue()
        self.assertEqual(exit_code, 0)
        self.assertIn("canonical_sha256", output)
        self.assertIn("activities", output)

    def test_document_and_identity_map_are_written(self):
        with tempfile.TemporaryDirectory() as directory:
            document = Path(directory) / "canonical.json"
            identity = Path(directory) / "identity.json"
            with redirect_stdout(io.StringIO()):
                main(
                    [
                        "canonicalise",
                        str(SYNTHETIC),
                        "--quiet",
                        "--output",
                        str(document),
                        "--identity-out",
                        str(identity),
                    ]
                )
            payload = json.loads(document.read_text())
            self.assertEqual(payload["schema_version"], "sto-canonical-1.0")
            self.assertIn("by_external", json.loads(identity.read_text()))


class ReconcileCommandTests(unittest.TestCase):
    def test_a_file_reconciled_against_itself_matches_everything(self):
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            main(["reconcile", str(SYNTHETIC), str(SYNTHETIC)])
        for line in buffer.getvalue().splitlines():
            if line.startswith("activity"):
                _, matched, new, rekeyed, missing, guid_changed = line.split()
                self.assertEqual(
                    (int(new), int(rekeyed), int(missing), int(guid_changed)), (0, 0, 0, 0)
                )
                self.assertGreater(int(matched), 0)
                break
        else:  # pragma: no cover - the table always has an activity row
            self.fail("no activity row in the reconciliation table")

    def test_a_different_schedule_reports_new_and_missing_rows(self):
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            main(["reconcile", str(SYNTHETIC), str(CHAIN)])
        table = buffer.getvalue()
        self.assertIn("activity", table)
        activity_row = next(
            line for line in table.splitlines() if line.startswith("activity")
        )
        _, _, new, _, missing, _ = activity_row.split()
        self.assertTrue(int(new) or int(missing))

    def test_report_is_written_as_json(self):
        with tempfile.TemporaryDirectory() as directory:
            report = Path(directory) / "report.json"
            with redirect_stdout(io.StringIO()):
                main(["reconcile", str(SYNTHETIC), str(SYNTHETIC), "--output", str(report)])
            payload = json.loads(report.read_text())
            self.assertIn("matched", payload)
            self.assertIn("entries", payload)


if __name__ == "__main__":
    unittest.main()


class OutputGuardTests(unittest.TestCase):
    """A mistyped --output must not destroy a schedule that has no other copy."""

    def test_output_may_not_overwrite_the_source(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "schedule.xml"
            source.write_bytes(SYNTHETIC.read_bytes())
            with self.assertRaises(SystemExit):
                main(["canonicalise", str(source), "--output", str(source)])
            self.assertEqual(source.read_bytes(), SYNTHETIC.read_bytes())

    def test_output_may_not_overwrite_the_source_through_a_symlink(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "schedule.xml"
            source.write_bytes(SYNTHETIC.read_bytes())
            alias = Path(directory) / "alias.xml"
            alias.symlink_to(source)
            with self.assertRaises(SystemExit):
                main(["canonicalise", str(source), "--output", str(alias)])
            self.assertEqual(source.read_bytes(), SYNTHETIC.read_bytes())

    def test_the_two_outputs_may_not_collide(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "both.json"
            with self.assertRaises(SystemExit):
                main(
                    [
                        "canonicalise",
                        str(SYNTHETIC),
                        "--output",
                        str(target),
                        "--identity-out",
                        str(target),
                    ]
                )


class ModuleEntryPointTests(unittest.TestCase):
    def test_python_m_sto_cli_runs(self):
        """The README documents this invocation, so it has to work in a
        source checkout, not only through the installed console script."""

        import subprocess
        import sys

        repo = Path(__file__).resolve().parent.parent
        result = subprocess.run(
            [sys.executable, "-m", "sto.cli", "canonicalise", str(SYNTHETIC), "--quiet"],
            cwd=repo,
            env={"PYTHONPATH": str(repo / "src"), "PATH": "/usr/bin:/bin"},
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("canonical_sha256", result.stdout)
