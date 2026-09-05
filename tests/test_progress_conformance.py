"""The corpus's status and progress cases, run through the forward pass itself.

These are the last of the corpus's executable cases. With them the engine runs
every case the corpus declares an answer for and does not hold back for
levelling -- the count the roadmap carries in its ``conformance`` block and the
number ``P1-G1`` names.

Each case is run under **its own declared progress policy**, because that is
what two of them are for: SEM-STA-043 and SEM-STA-044 are the same schedule,
the same actuals and the same status time under retained logic and progress
override, and they differ by two units of project finish. A harness that ran
both under one policy would pass one and fail the other, so the policy comes
from the case rather than from a default.

``remaining_start`` is asserted the way the corpus writes it: present for the
activities the corpus says are in progress and absent for the rest. That makes
the state itself part of the comparison -- an engine that thought a complete
activity was still running would produce an extra key and fail here, rather
than quietly agreeing about two dates.

SEM-STA-045 is the case with no declared answer. It is asserted to be
**refused**, which is the only claim we are entitled to make about it: the
corpus marks it ``native_validation_only``, so a number from us would be an
invented oracle rather than a result.
"""

from __future__ import annotations

import unittest

from conformance_fixture import _build_network, _load, _progress_policy, _uid

from sto.core.engine import ProgressError, ProgressState, forward_pass

#: Every status case the corpus declares an answer for.
STATUS_CASES = (
    "sem-sta-039",
    "sem-sta-040",
    "sem-sta-041",
    "sem-sta-042",
    "sem-sta-043",
    "sem-sta-044",
    "sem-sta-046",
)

#: The one status case only a native run can answer.
NATIVE_ONLY_CASE = "sem-sta-045"


def _run_case(case_id: str):
    """The case, its expectation, and the pass's answer keyed by the corpus's ids."""

    case = _load(case_id)
    network, uid_by_id = _build_network(case_id, case)
    result = forward_pass(network, progress_policy=_progress_policy(case))
    times = result.by_uid()

    got = {}
    for local_id, uid in uid_by_id.items():
        row = times[uid]
        answer = {"start": row.early_start, "finish": row.early_finish}
        if row.state is ProgressState.IN_PROGRESS:
            answer["remaining_start"] = row.remaining_start
        got[local_id] = answer
    return case, result, got, uid_by_id


class StatusCaseTests(unittest.TestCase):
    """One method per case, so a failure names the semantics that broke."""

    def _run(self, case_id: str) -> None:
        case, result, got, _ = _run_case(case_id)
        expected = case["expected"]
        self.assertEqual(
            expected["reference_status"], "declared", f"{case_id} carries no oracle"
        )
        # The corpus writes each activity's keys in its own order; compare the
        # mappings, which is what the dates mean, not the order they arrived in.
        self.assertEqual(
            {k: dict(v) for k, v in got.items()},
            {k: dict(v) for k, v in expected["activity_times"].items()},
            f"{case_id}: {case['title']}",
        )
        self.assertEqual(
            result.project_finish,
            expected["project_finish"],
            f"{case_id}: project finish",
        )

    def test_sem_sta_039_completed_actuals_are_immutable(self):
        self._run("sem-sta-039")

    def test_sem_sta_040_in_progress_remaining_work(self):
        self._run("sem-sta-040")

    def test_sem_sta_041_late_actual_start_drives_successor(self):
        self._run("sem-sta-041")

    def test_sem_sta_042_actual_finish_drives_downstream_lag(self):
        self._run("sem-sta-042")

    def test_sem_sta_043_out_of_sequence_retained_logic(self):
        self._run("sem-sta-043")

    def test_sem_sta_044_out_of_sequence_progress_override(self):
        self._run("sem-sta-044")

    def test_sem_sta_046_emergent_activity_after_status(self):
        self._run("sem-sta-046")


class ProgressStateTests(unittest.TestCase):
    """The states the pass assigned, checked against what each case is about."""

    def test_a_completed_activity_reports_no_remaining_start(self):
        _, result, got, uid_by_id = _run_case("sem-sta-039")
        row = result.by_uid()[uid_by_id["A"]]
        self.assertIs(row.state, ProgressState.COMPLETE)
        self.assertIsNone(row.remaining_start)
        self.assertNotIn("remaining_start", got["A"])

    def test_an_in_progress_activity_keeps_its_actual_start(self):
        case, result, _, uid_by_id = _run_case("sem-sta-040")
        declared = case["schedule"]["activities"][0]["actual_start"]
        row = result.by_uid()[uid_by_id["A"]]
        self.assertIs(row.state, ProgressState.IN_PROGRESS)
        self.assertEqual(row.early_start, declared)
        self.assertGreater(row.remaining_start, row.early_start)

    def test_an_untouched_activity_is_not_started(self):
        _, result, _, uid_by_id = _run_case("sem-sta-046")
        row = result.by_uid()[uid_by_id["A"]]
        self.assertIs(row.state, ProgressState.NOT_STARTED)
        self.assertIsNone(row.remaining_start)


class RetainedLogicVersusOverrideTests(unittest.TestCase):
    """The two cases that are the same schedule under two policies.

    Asserted against each other rather than only against their own expectations,
    because the pair is the actual claim: the policy has to *change* the answer,
    and by exactly the amount the corpus declares.
    """

    def test_the_two_policies_disagree_about_the_project_finish(self):
        _, retained, _, _ = _run_case("sem-sta-043")
        _, override, _, _ = _run_case("sem-sta-044")
        self.assertEqual(retained.project_finish, 10)
        self.assertEqual(override.project_finish, 8)

    def test_only_retained_logic_reports_a_driving_relationship(self):
        _, retained, _, _ = _run_case("sem-sta-043")
        _, override, _, _ = _run_case("sem-sta-044")
        self.assertEqual(len(retained.driving_relationships()), 1)
        self.assertEqual(override.driving_relationships(), ())

    def test_both_preserve_the_out_of_sequence_actual_start(self):
        for case_id in ("sem-sta-043", "sem-sta-044"):
            with self.subTest(case_id):
                _, result, _, uid_by_id = _run_case(case_id)
                self.assertEqual(result.by_uid()[uid_by_id["B"]].early_start, 4)


class DrivingRelationshipTests(unittest.TestCase):
    """Every relationship the corpus names as driving is one the pass named.

    Containment, not equality: the corpus's ``driving_relationships`` is a
    curated subset -- the finding the forward-pass slice recorded -- so the
    assertion is that we did not miss one, never that we found no others.
    """

    def test_every_declared_driver_is_reported(self):
        for case_id in STATUS_CASES:
            with self.subTest(case_id):
                case, result, _, uid_by_id = _run_case(case_id)
                declared = {
                    _uid(case_id, row) for row in case["expected"]["driving_relationships"]
                }
                self.assertLessEqual(declared, set(result.driving_relationships()))


class NativeOnlyCaseTests(unittest.TestCase):
    """The actual-dates policy is refused, not answered."""

    def test_the_case_still_carries_no_oracle(self):
        case = _load(NATIVE_ONLY_CASE)
        self.assertEqual(case["expected"]["reference_status"], "native_validation_only")
        self.assertIsNone(case["expected"]["project_finish"])

    def test_the_pass_refuses_it_by_code(self):
        case = _load(NATIVE_ONLY_CASE)
        network, _ = _build_network(NATIVE_ONLY_CASE, case)
        with self.assertRaises(ProgressError) as raised:
            forward_pass(network, progress_policy=_progress_policy(case))
        self.assertEqual(raised.exception.code, "PROGRESS_POLICY_NOT_EVIDENCED")

    def test_the_same_schedule_is_answerable_under_the_policies_that_are(self):
        # The refusal is about the policy, not about the schedule: SEM-STA-045
        # is SEM-STA-043's network, and it schedules under retained logic.
        case = _load(NATIVE_ONLY_CASE)
        network, uid_by_id = _build_network(NATIVE_ONLY_CASE, case)
        result = forward_pass(network)
        self.assertEqual(result.by_uid()[uid_by_id["B"]].early_start, 4)


if __name__ == "__main__":
    unittest.main()
