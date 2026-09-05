"""Every executable corpus case runs, and three processes get the same bytes.

This is ``P1-G1`` asked directly. The gate has two halves and they fail in
different ways, so they are asked separately.

**Every executable case is actually run by a test.** The corpus classifies its
own cases -- a case with no declared forecast is native-only, one with a
resource order arrives with levelling, and the rest are the engine's to pass --
and the three modules that run them name the ids they cover. If those two sets
ever drift, a case has been added to the corpus and quietly not run, or a list
here names a case the corpus no longer has. Either is a hole in the bound the
engine's claims rest on, so it is a failure rather than a smaller number nobody
notices.

**Three processes agree byte for byte.** Determinism inside one process is not
the claim: a schedule's answer must not depend on dictionary iteration order,
on the address a UUID happens to land at, or on anything else that varies
between interpreters. So the digest is computed in three subprocesses with
three different hash seeds, and the three have to be identical. The pass
fingerprints are already canonical hashes, which is what makes the comparison a
single string rather than a diff of every date.
"""

from __future__ import annotations

import os
import subprocess
import sys
import unittest
from pathlib import Path

from test_conformance_determinism_worker import digest_of_every_executable_case
from test_float_conformance import FLOAT_CASES
from test_forward_pass_conformance import FORWARD_CASES
from test_progress_conformance import STATUS_CASES

from sto import conformance

REPO_ROOT = Path(__file__).resolve().parent.parent
WORKER = Path(__file__).resolve().parent / "test_conformance_determinism_worker.py"

#: The hash seeds the three processes run under. Fixed rather than random so a
#: failure is reproducible; different from each other so the run is a test.
SEEDS = ("0", "1", "2718281828")


class CoverageTests(unittest.TestCase):
    """The cases the suite runs are exactly the cases the corpus says it must."""

    def test_every_executable_case_is_covered_by_a_test_module(self):
        covered = set(FORWARD_CASES) | set(FLOAT_CASES) | set(STATUS_CASES)
        executable = set(conformance.executable_case_ids())
        self.assertEqual(
            sorted(covered),
            sorted(executable),
            "the corpus's executable subset and the cases the suite runs disagree",
        )

    def test_the_covered_count_is_the_one_the_roadmap_carries(self):
        from sto.roadmap import load as load_roadmap

        roadmap = load_roadmap()
        covered = set(FORWARD_CASES) | set(FLOAT_CASES) | set(STATUS_CASES)
        self.assertIsNotNone(roadmap.conformance)
        self.assertEqual(
            len(covered), roadmap.conformance["executable_by_the_cpm_engine"]
        )

    def test_no_module_claims_a_case_another_one_also_claims(self):
        lists = (FORWARD_CASES, FLOAT_CASES, STATUS_CASES)
        flat = [case_id for names in lists for case_id in names]
        self.assertEqual(len(flat), len(set(flat)))


class ProcessDeterminismTests(unittest.TestCase):
    """Three interpreters, three hash seeds, one digest."""

    def _digest_in_a_subprocess(self, seed: str) -> str:
        environment = dict(os.environ)
        environment["PYTHONHASHSEED"] = seed
        environment["PYTHONPATH"] = os.pathsep.join(
            [str(REPO_ROOT / "src"), str(WORKER.parent)]
        )
        completed = subprocess.run(
            [sys.executable, str(WORKER)],
            capture_output=True,
            text=True,
            env=environment,
            cwd=str(REPO_ROOT),
            check=False,
        )
        self.assertEqual(
            completed.returncode, 0, f"seed {seed} failed:\n{completed.stderr}"
        )
        return completed.stdout.strip()

    def test_the_digest_is_the_same_in_three_processes(self):
        digests = [self._digest_in_a_subprocess(seed) for seed in SEEDS]
        self.assertEqual(len(set(digests)), 1, f"three processes disagreed: {digests}")
        self.assertEqual(len(digests[0]), 64)

    def test_and_the_same_as_the_one_computed_here(self):
        # The subprocesses are not running some other code path: this process
        # computes the same digest from the same function.
        digests = {self._digest_in_a_subprocess(seed) for seed in SEEDS}
        self.assertEqual(digests, {digest_of_every_executable_case()})


if __name__ == "__main__":
    unittest.main()
