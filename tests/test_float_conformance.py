"""The corpus's float cases, run through the backward pass and the float itself.

SEM-FLT-047 and SEM-FLT-048 are the two cases in the semantic corpus that a
forward pass alone cannot answer, and they are this slice's pass criterion: the
first is total float on a shorter independent path, the second is the case where
free float and total float genuinely differ. Both declare start, finish, total
float and free float for every activity, so the assertion is the whole row and
not a chosen field.

They are the float cases; the forward and status cases have modules of their
own, and ``tests/test_conformance_determinism.py`` holds the three modules
together to exactly the corpus's own executable subset, so no count of cases
is written here to drift.

Both cases are declared on a continuous calendar, so they cannot tell a
working-time float from an elapsed one. That question is settled in
``tests/test_backward_pass_boiler.py`` against the real schedules, which have
weekends; here the corpus checks the network semantics it was written for.
"""

from __future__ import annotations

import unittest

from conformance_fixture import _build_network, _load

from sto import conformance
from sto.core.engine import backward_pass, float_analysis, forward_pass

#: The corpus cases a backward pass is needed for, by corpus id.
FLOAT_CASES = ("sem-flt-047", "sem-flt-048")


class FloatCaseTests(unittest.TestCase):
    """One method per case, so a failure names the semantics that broke."""

    def _run(self, case_id: str) -> None:
        case = _load(case_id)
        expected = case["expected"]
        self.assertEqual(
            expected["reference_status"], "declared", f"{case_id} carries no oracle"
        )
        network, uid_by_id = _build_network(case_id, case)

        forward = forward_pass(network)
        backward = backward_pass(network, forward)
        floats = float_analysis(network, forward, backward)

        early, slack = forward.by_uid(), floats.by_uid()
        got = {
            local_id: {
                "start": early[uid].early_start,
                "finish": early[uid].early_finish,
                "total_float": slack[uid].total_float,
                "free_float": slack[uid].free_float,
            }
            for local_id, uid in uid_by_id.items()
        }
        self.assertEqual(got, expected["activity_times"], f"{case_id}: {case['title']}")
        self.assertEqual(
            forward.project_finish, expected["project_finish"], f"{case_id}: project finish"
        )

    def test_sem_flt_047_parallel_paths_total_float(self):
        self._run("sem-flt-047")

    def test_sem_flt_048_free_float_differs_from_total_float(self):
        self._run("sem-flt-048")


class FloatSemanticsTests(unittest.TestCase):
    """What the two cases are *for*, asserted as the properties they demonstrate."""

    def test_the_shorter_path_carries_the_slack_and_the_longer_one_is_critical(self):
        case = _load("sem-flt-047")
        network, uid_by_id = _build_network("sem-flt-047", case)
        forward = forward_pass(network)
        floats = float_analysis(network, forward, backward_pass(network, forward))
        self.assertEqual(
            set(floats.critical_activities()),
            {uid_by_id["A"], uid_by_id["B"]},
            "the long path is the critical one",
        )
        self.assertEqual(floats.negative_float_activities(), ())

    def test_an_activity_can_have_total_float_with_no_free_float(self):
        """SEM-FLT-048's whole point: C may slip only by delaying E with it."""

        case = _load("sem-flt-048")
        network, uid_by_id = _build_network("sem-flt-048", case)
        forward = forward_pass(network)
        floats = float_analysis(network, forward, backward_pass(network, forward))
        c = floats.by_uid()[uid_by_id["C"]]
        self.assertEqual(c.total_float, 2)
        self.assertEqual(c.free_float, 0)


class CoverageTests(unittest.TestCase):
    """The corpus is only a bound on the engine's claims if it actually ran."""

    def test_every_float_case_has_a_method(self):
        methods = [name for name in dir(FloatCaseTests) if name.startswith("test_sem_")]
        missing = [
            case_id
            for case_id in FLOAT_CASES
            if not any(name.startswith(f"test_{case_id.replace('-', '_')}") for name in methods)
        ]
        self.assertEqual(missing, [], "corpus float cases with no test method")

    def test_every_float_case_the_corpus_declares_is_covered(self):
        """The corpus, not this module, decides which cases are float cases."""

        declared = sorted(
            case_id
            for case_id in conformance.case_ids()
            if _load(case_id)["category"] == "float"
        )
        self.assertEqual(declared, sorted(FLOAT_CASES))


if __name__ == "__main__":
    unittest.main()
