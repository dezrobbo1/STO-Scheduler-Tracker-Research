"""Final narrow regressions for the PR #22 canonical/identity merge gate."""

from __future__ import annotations

import io
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from sto.cli import main
from sto.core.model.enums import EntityKind, SourceSystem
from sto.core.model.ids import IdentityMap
from sto.legacy import import_mspdi
from sto.legacy.validation import validate_canonical_schedule

FIXTURES = Path(__file__).resolve().parent / "fixtures"
SYNTHETIC = FIXTURES / "synthetic-basic.mspdi.xml"
CHAIN = FIXTURES / "synthetic-workspace-chain.mspdi.xml"


class RetiredExternalUidTests(unittest.TestCase):
    def test_reused_retired_uid_mints_a_new_canonical_identity(self):
        identity = IdentityMap("schedule", SourceSystem.MICROSOFT_PROJECT)
        first_guid = "11111111-1111-1111-1111-111111111111"
        second_guid = "22222222-2222-2222-2222-222222222222"

        original, _ = identity.resolve(
            EntityKind.ACTIVITY, "1", guid=first_guid
        )
        moved, _ = identity.resolve(
            EntityKind.ACTIVITY, "2", guid=first_guid
        )
        reused, _ = identity.resolve(
            EntityKind.ACTIVITY, "1", guid=second_guid
        )

        self.assertEqual(original, moved)
        self.assertNotEqual(original, reused)

        restored = IdentityMap.from_dict(identity.to_dict())
        again, entry = restored.resolve(
            EntityKind.ACTIVITY, "1", guid=second_guid
        )
        self.assertEqual(reused, again)
        self.assertEqual(str(entry.outcome), "matched")


class LegacyImportFailClosedTests(unittest.TestCase):
    def test_unknown_constraint_code_is_rejected_before_migration(self):
        document = import_mspdi(str(SYNTHETIC))
        self.assertTrue(document["activities"])
        document["activities"][0]["constraint_type_source"] = 99

        report = validate_canonical_schedule(document)

        self.assertFalse(report.valid)
        self.assertTrue(
            any("unsupported constraint_type_source 99" in error for error in report.errors),
            report.errors,
        )

    def test_assignment_to_summary_task_is_rejected_before_migration(self):
        document = import_mspdi(str(SYNTHETIC))
        self.assertTrue(document["assignments"])
        self.assertTrue(document["wbs_nodes"])
        summary_ref = document["wbs_nodes"][0]["id"]
        document["assignments"][0]["task_ref"] = summary_ref

        report = validate_canonical_schedule(document)

        self.assertFalse(report.valid)
        self.assertTrue(
            any("targets summary task" in error for error in report.errors),
            report.errors,
        )


class CanonicaliseIdentityInputTests(unittest.TestCase):
    def _identity_file(self, directory: str) -> Path:
        identity = Path(directory) / "identity.json"
        with redirect_stdout(io.StringIO()):
            main(
                [
                    "canonicalise",
                    str(SYNTHETIC),
                    "--quiet",
                    "--identity-out",
                    str(identity),
                ]
            )
        return identity

    def test_identity_input_from_another_project_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            identity = self._identity_file(directory)
            with self.assertRaises(SystemExit) as raised:
                with redirect_stdout(io.StringIO()):
                    main(
                        [
                            "canonicalise",
                            str(CHAIN),
                            "--identity-in",
                            str(identity),
                            "--quiet",
                        ]
                    )
            self.assertIn("identity map does not belong", str(raised.exception))

    def test_project_identity_mismatch_requires_explicit_override(self):
        with tempfile.TemporaryDirectory() as directory:
            identity = self._identity_file(directory)
            stderr = io.StringIO()
            with redirect_stdout(io.StringIO()), redirect_stderr(stderr):
                exit_code = main(
                    [
                        "canonicalise",
                        str(CHAIN),
                        "--identity-in",
                        str(identity),
                        "--allow-project-identity-mismatch",
                        "--quiet",
                    ]
                )
            self.assertEqual(exit_code, 0)
            self.assertIn("overriding a project-identity mismatch", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
