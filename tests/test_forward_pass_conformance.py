"""The semantic corpus, run through the forward pass itself.

Every case the corpus declares that a forward pass alone can answer: all twelve
relationship cases, the eight network cases, all ten calendar cases, the four
milestone cases and the four constraint cases. What is left out is left out for
a reason the slice can name -- the eight status cases need actuals and a status
date (S5), the two float cases need a backward pass (S4), and the two
determinism cases arrive with levelling (P6).

Turning a case into a network is ``tests/conformance_fixture.py``, which the
float cases in ``tests/test_float_conformance.py`` share, so the two passes are
held to the corpus through one mapping rather than two.

The corpus is the pinned copy in :mod:`sto.conformance`; every case is
hash-checked as it is read, so a drifted case fails rather than passing against
a different oracle. :mod:`tests.test_conformance_corpus` guards the pins.

Dates and the project finish are the corpus's own pass criterion and are
asserted per case. Which relationship *drove* each activity is checked
separately, over every case at once, so a disagreement about a tie-break is
never mistaken for a wrong date.
"""

from __future__ import annotations

import unittest

from conformance_fixture import _build_network, _load, _uid

from sto import conformance
from sto.core.engine import forward_pass

#: Every case a forward pass alone can answer, by corpus id.
FORWARD_CASES = (
    [f"sem-rel-{n:03d}" for n in range(1, 13)]
    + [f"sem-net-{n:03d}" for n in range(13, 21)]
    + [f"sem-cal-{n:03d}" for n in range(21, 31)]
    + [f"sem-mil-{n:03d}" for n in range(31, 35)]
    + [f"sem-con-{n:03d}" for n in range(35, 39)]
)


class ForwardCaseTests(unittest.TestCase):
    """One method per case, so a failure names the semantics that broke."""

    def _run(self, case_id: str) -> None:
        case = _load(case_id)
        expected = case["expected"]
        self.assertEqual(
            expected["reference_status"], "declared", f"{case_id} carries no oracle"
        )
        network, uid_by_id = _build_network(case_id, case)
        result = forward_pass(network)
        times = result.by_uid()

        got = {
            local_id: {
                "start": times[uid].early_start,
                "finish": times[uid].early_finish,
            }
            for local_id, uid in uid_by_id.items()
        }
        self.assertEqual(got, expected["activity_times"], f"{case_id}: {case['title']}")
        self.assertEqual(
            result.project_finish, expected["project_finish"], f"{case_id}: project finish"
        )

    # --- relationships: the four types, and lag in both directions ----------------

    def test_sem_rel_001_fs_zero_lag(self):
        self._run("sem-rel-001")

    def test_sem_rel_002_ss_zero_lag(self):
        self._run("sem-rel-002")

    def test_sem_rel_003_ff_zero_lag(self):
        self._run("sem-rel-003")

    def test_sem_rel_004_sf_zero_lag(self):
        self._run("sem-rel-004")

    def test_sem_rel_005_fs_positive_lag(self):
        self._run("sem-rel-005")

    def test_sem_rel_006_ss_positive_lag(self):
        self._run("sem-rel-006")

    def test_sem_rel_007_ff_positive_lag(self):
        self._run("sem-rel-007")

    def test_sem_rel_008_sf_positive_lag(self):
        self._run("sem-rel-008")

    def test_sem_rel_009_fs_negative_lag(self):
        self._run("sem-rel-009")

    def test_sem_rel_010_ss_negative_lag(self):
        self._run("sem-rel-010")

    def test_sem_rel_011_ff_negative_lag(self):
        self._run("sem-rel-011")

    def test_sem_rel_012_sf_negative_lag(self):
        self._run("sem-rel-012")

    # --- networks: convergence, divergence and which edge drives ------------------

    def test_sem_net_013_two_fs_predecessors(self):
        self._run("sem-net-013")

    def test_sem_net_014_mixed_fs_and_ss_bounds(self):
        self._run("sem-net-014")

    def test_sem_net_015_one_predecessor_two_successors(self):
        self._run("sem-net-015")

    def test_sem_net_016_three_activity_chain(self):
        self._run("sem-net-016")

    def test_sem_net_017_diamond_network(self):
        self._run("sem-net-017")

    def test_sem_net_018_convergence_with_lag(self):
        self._run("sem-net-018")

    def test_sem_net_019_redundant_non_driving_predecessor(self):
        self._run("sem-net-019")

    def test_sem_net_020_mixed_relationship_driving(self):
        self._run("sem-net-020")

    # --- calendars, now through the engine rather than the arithmetic alone -------

    def test_sem_cal_021_duration_spans_lunch(self):
        self._run("sem-cal-021")

    def test_sem_cal_022_duration_spans_overnight(self):
        self._run("sem-cal-022")

    def test_sem_cal_023_duration_spans_weekend(self):
        self._run("sem-cal-023")

    def test_sem_cal_024_fs_lag_on_successor_calendar(self):
        self._run("sem-cal-024")

    def test_sem_cal_025_successor_snaps_to_next_working_interval(self):
        self._run("sem-cal-025")

    def test_sem_cal_026_activity_calendars_produce_different_finishes(self):
        self._run("sem-cal-026")

    def test_sem_cal_027_resource_calendar_delays_work(self):
        self._run("sem-cal-027")

    def test_sem_cal_028_holiday_exception(self):
        self._run("sem-cal-028")

    def test_sem_cal_029_ss_lag_across_lunch(self):
        self._run("sem-cal-029")

    def test_sem_cal_030_negative_fs_lag_across_lunch(self):
        self._run("sem-cal-030")

    # --- milestones: a coordinate, not a span -------------------------------------

    def test_sem_mil_031_start_milestone_at_project_start(self):
        self._run("sem-mil-031")

    def test_sem_mil_032_finish_milestone_after_task(self):
        self._run("sem-mil-032")

    def test_sem_mil_033_milestone_predecessor(self):
        self._run("sem-mil-033")

    def test_sem_mil_034_ff_relationship_into_milestone(self):
        self._run("sem-mil-034")

    # --- constraints that can move an early date ----------------------------------

    def test_sem_con_035_start_no_earlier_than(self):
        self._run("sem-con-035")

    def test_sem_con_036_finish_no_earlier_than(self):
        self._run("sem-con-036")

    def test_sem_con_037_constraint_dominates_logic(self):
        self._run("sem-con-037")

    def test_sem_con_038_redundant_constraint(self):
        self._run("sem-con-038")


class CoverageTests(unittest.TestCase):
    """The corpus is only a bound on the engine's claims if it actually ran."""

    def test_every_forward_case_has_a_method(self):
        methods = [name for name in dir(ForwardCaseTests) if name.startswith("test_sem_")]
        missing = [
            case_id
            for case_id in FORWARD_CASES
            if not any(name.startswith(f"test_{case_id.replace('-', '_')}") for name in methods)
        ]
        self.assertEqual(missing, [], "corpus cases with no test method")

    def test_every_forward_case_file_is_present(self):
        missing = [c for c in FORWARD_CASES if c not in conformance.case_ids()]
        self.assertEqual(missing, [], "declared forward cases absent from the corpus")


class DrivingRelationshipTests(unittest.TestCase):
    """Which edge placed each activity, checked apart from whether the dates are right.

    The corpus's ``driving_relationships`` is a **curated subset**, not the whole
    set: its own validator asks only that each relationship it lists genuinely
    governs. SEM-NET-015 declares just ``R2`` because the case is about C
    controlling the project finish, though ``R1`` is equally the only thing
    placing B; SEM-NET-017 declares just ``R3`` because the case is about B
    driving D. So the assertion is containment, which is what the corpus
    specifies -- an equality assertion here would be asserting a property the
    corpus never claimed.

    A disagreement is about attribution among equal bounds rather than about the
    schedule, which is why it is kept out of the date assertions.
    """

    def test_every_declared_driver_is_one_the_pass_reports(self):
        disagreed: list[str] = []
        for case_id in FORWARD_CASES:
            case = _load(case_id)
            declared = case["expected"].get("driving_relationships")
            if not declared:
                continue
            network, _ = _build_network(case_id, case)
            result = forward_pass(network)
            local_by_uid = {
                _uid(case_id, row["id"]): row["id"]
                for row in case["schedule"]["relationships"]
            }
            reported = {local_by_uid[uid] for uid in result.driving_relationships()}
            missed = sorted(set(declared) - reported)
            if missed:
                disagreed.append(
                    f"{case_id}: declared {sorted(declared)} but {missed} did not govern"
                )
        self.assertEqual(disagreed, [], "\n".join(disagreed))


if __name__ == "__main__":
    unittest.main()
