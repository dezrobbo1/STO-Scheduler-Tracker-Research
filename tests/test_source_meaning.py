"""What the file said, from the XML through to the passes (slice C1).

The conformance corpus builds a :class:`Network` directly, so it proves the
passes behave on a network that was constructed correctly and can say nothing
about the road from XML to that network. Every defect here lived on that road:
the comprehensive review of 2026-09-07 reproduced five ways an unsupported
source state became an ordinary, apparently valid calculation — a broken
calendar reference became inheritance, an elapsed duration became working
time, a duration the parser could not read became zero work, manual and
from-finish settings were ignored, and two rows sharing one GUID collapsed
onto one canonical identity.

So each test here goes the whole way: an MSPDI document, ``import_mspdi``,
``migrate``, ``build_plan``, and where it matters the passes. The rule every
one of them holds to is that nothing is refused at import — a real file must
keep importing — and nothing is silently defaulted either: the row comes out
as a coded exclusion, a labelled assumption, or a plan-level refusal.
"""

from __future__ import annotations

import tempfile
import unittest
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from xml.etree import ElementTree as ET

from calculation_fixture import _activity, _calendar, _document, _relationship

from sto.core.engine import PlanError, build_plan, forward_pass
from sto.core.model.enums import ScheduleDirection
from sto.core.model.migrate.sto_v011 import migrate
from sto.legacy import MSPDI_NAMESPACE, import_mspdi

NS = {"p": MSPDI_NAMESPACE}

#: The smallest MSPDI that compiles to a calendar and schedules two tasks. The
#: committed synthetic fixture defines two weekdays and is an importer fixture,
#: not a schedulable one, and the road under test here ends at the passes.
_WEEKDAYS = "".join(
    f"<WeekDay><DayType>{day}</DayType><DayWorking>1</DayWorking><WorkingTimes>"
    "<WorkingTime><FromTime>08:00:00</FromTime><ToTime>16:00:00</ToTime></WorkingTime>"
    "</WorkingTimes></WeekDay>"
    for day in range(1, 8)
)
_TASK = (
    "<Task><UID>{uid}</UID><ID>{uid}</ID><Name>Task {uid}</Name><Active>1</Active>"
    "<Manual>0</Manual><Type>0</Type><IsNull>0</IsNull><WBS>{uid}</WBS>"
    "<OutlineNumber>{uid}</OutlineNumber><OutlineLevel>1</OutlineLevel><Priority>500</Priority>"
    "<Start>2026-01-05T08:00:00</Start><Finish>2026-01-05T09:00:00</Finish>"
    "<Duration>PT1H0M0S</Duration><DurationFormat>5</DurationFormat><Work>PT1H0M0S</Work>"
    "<Estimated>0</Estimated><Milestone>0</Milestone><Summary>0</Summary>"
    "<RemainingDuration>PT1H0M0S</RemainingDuration><ConstraintType>0</ConstraintType>"
    "{extra}</Task>"
)
_PROJECT = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<Project xmlns="http://schemas.microsoft.com/project">'
    "<Name>Source meaning</Name><ScheduleFromStart>1</ScheduleFromStart>"
    "<StartDate>2026-01-05T08:00:00</StartDate><FinishDate>2026-01-09T16:00:00</FinishDate>"
    "<CalendarUID>1</CalendarUID>"
    "<Calendars><Calendar><UID>1</UID><Name>Standard</Name><IsBaseCalendar>1</IsBaseCalendar>"
    "<IsBaselineCalendar>0</IsBaselineCalendar><BaseCalendarUID>-1</BaseCalendarUID>"
    f"<WeekDays>{_WEEKDAYS}</WeekDays></Calendar></Calendars>"
    "<Tasks>{tasks}</Tasks><Resources/><Assignments/></Project>"
)


@contextmanager
def _imported(extra_on_first=""):
    """One real MSPDI document, written to disk and read by the real importer."""

    tasks = _TASK.format(uid=1, extra=extra_on_first) + _TASK.format(uid=2, extra="")
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "source-meaning.mspdi.xml"
        path.write_text(_PROJECT.format(tasks=tasks), encoding="utf-8")
        yield import_mspdi(str(path))

HORIZON = (datetime(2026, 1, 5) - timedelta(days=7), datetime(2026, 1, 5) + timedelta(days=60))


def _task(number, hour=9, **fields):
    return _activity(
        number,
        start=f"2026-01-05T{hour:02d}:00:00",
        finish=f"2026-01-05T{hour + 1:02d}:00:00",
        duration_seconds=3600,
        **fields,
    )


def _assignment_row(number, task, resource):
    hour = {"raw": "PT1H", "seconds": 3600, "parse_status": "parsed"}
    return {
        "id": f"assignment:{number}",
        "source_order": number,
        "task_ref": f"task:{task}",
        "resource_ref": f"resource:{resource}",
        "units_source": 1,
        "work_source": hour,
        "actual_work_source": {"raw": "PT0S", "seconds": 0, "parse_status": "parsed"},
        "remaining_work_source": hour,
        "percent_work_complete_source": 0,
        "work_contour_source": 0,
        "extension_refs": [],
    }


def _plan(document):
    schedule, _, report = migrate(document)
    return schedule, build_plan(schedule, HORIZON), report


class AnUnresolvedCalendarIsNotInheritanceTests(unittest.TestCase):
    """F01. A broken reference and no reference are different facts."""

    def test_a_calendar_the_file_does_not_carry_excludes_its_row(self):
        schedule, plan, _ = _plan(_document([_task(1), _task(2, calendar_ref="calendar:99")]))
        broken = next(a for a in schedule.activities if a.code == "2")
        self.assertIsNotNone(broken.calendar_uid, "the reference was dropped, not preserved")
        self.assertEqual(plan.excluded_by_code(), {"ACTIVITY_CALENDAR_UNRESOLVED": 1})
        self.assertEqual(plan.excluded[0].uid, broken.uid)
        self.assertEqual([row.uid for row in plan.network.activities], [schedule.activities[0].uid])

    def test_a_resource_keeps_its_broken_reference_too(self):
        schedule, _, _ = _plan(
            _document(
                [_task(1)],
                resources=[
                    {
                        "id": "resource:1",
                        "source_order": 1,
                        "external_references": [],
                        "name": "Sensitive resource",
                        "calendar_ref": "calendar:99",
                    }
                ],
            )
        )
        self.assertEqual(
            schedule.resources[0].source_fields.get("calendar_ref_unresolved"),
            "calendar:99",
        )

    def test_an_omitted_schedule_direction_is_not_backward_scheduling(self):
        """Absence is not a choice, and refusing it would refuse a real file."""

        document = _document([_task(1)])
        document["project"]["schedule_from_start"] = None
        schedule, _, _ = migrate(document)
        self.assertIs(schedule.project.schedule_direction, ScheduleDirection.FROM_START)
        self.assertEqual(len(build_plan(schedule, HORIZON).network.activities), 1)

    def test_the_broken_reference_itself_is_kept_beside_the_minted_id(self):
        # The minted id is one-way. An exclusion naming only a UUID cannot be
        # acted on without reopening the source file.
        schedule, plan, _ = _plan(_document([_task(1, calendar_ref="calendar:99")]))
        self.assertEqual(
            schedule.activities[0].source_fields.get("calendar_ref_unresolved"),
            "calendar:99",
        )
        self.assertEqual(plan.excluded_by_code(), {"ACTIVITY_CALENDAR_UNRESOLVED": 1})

    def test_a_row_naming_no_calendar_still_inherits_the_project_default(self):
        schedule, plan, _ = _plan(_document([_task(1)]))
        self.assertIsNone(schedule.activities[0].calendar_uid)
        self.assertEqual(plan.excluded, ())
        self.assertEqual(len(plan.network.activities), 1)

    def test_a_real_file_warns_and_the_row_is_excluded_not_inherited(self):
        """The whole road, on real MSPDI: XML, importer, migration, plan."""

        with _imported("<CalendarUID>999</CalendarUID>") as document:
            self.assertTrue(document["import_validation"]["valid"])
            warnings = document["import_validation"]["warnings"]
            self.assertTrue(
                any("unresolved calendar" in str(item) for item in warnings), warnings
            )
            schedule, _, _ = migrate(document)
            broken = next(a for a in schedule.activities if a.code == "1")
            self.assertIsNotNone(broken.calendar_uid)
            plan = build_plan(schedule, HORIZON)
            self.assertEqual(plan.excluded_by_code().get("ACTIVITY_CALENDAR_UNRESOLVED"), 1)
            self.assertEqual(plan.excluded[0].uid, broken.uid)
            self.assertEqual(len(plan.network.activities), 1)


class ElapsedDurationIsNotWorkingTimeTests(unittest.TestCase):
    """F02. ``DurationFormat`` says which clock a span runs on."""

    def _row(self, format_code):
        schedule, _, _ = migrate(_document([_task(1, duration_format=format_code)]))
        return schedule.activities[0].planned_duration

    def test_the_format_code_carries_the_unit_and_the_elapsed_flag(self):
        working = self._row("5")
        self.assertEqual((working.unit, working.elapsed, working.source_format_code), ("h", False, 5))
        elapsed = self._row("8")
        self.assertEqual((elapsed.unit, elapsed.elapsed, elapsed.source_format_code), ("ed", True, 8))
        estimated = self._row("40")
        self.assertEqual((estimated.unit, estimated.elapsed), ("ed?", True))

    def test_an_elapsed_span_runs_on_the_clock_and_says_so(self):
        # Eight hours on a 08:00-16:00 calendar with an hour of lunch would
        # finish at 17:00 as working time. Elapsed, it finishes at 16:00 the
        # same day, because elapsed time counts every hour.
        schedule, plan, _ = _plan(
            _document(
                [
                    _activity(
                        1,
                        start="2026-01-05T08:00:00",
                        finish="2026-01-05T16:00:00",
                        duration_seconds=8 * 3600,
                        duration_format="6",
                    )
                ],
                calendars=[_calendar(1, [("08:00:00", "12:00:00"), ("13:00:00", "17:00:00")])],
            )
        )
        row = forward_pass(plan.network).by_uid()[schedule.activities[0].uid]
        self.assertEqual(
            (plan.to_datetime(row.early_start), plan.to_datetime(row.early_finish)),
            (datetime(2026, 1, 5, 8, 0), datetime(2026, 1, 5, 16, 0)),
        )

    def test_it_is_scheduled_under_a_label_rather_than_claimed(self):
        _, plan, _ = _plan(_document([_task(1, duration_format="8")]))
        self.assertEqual(plan.assumed_by_code(), {"ACTIVITY_DURATION_ELAPSED": 1})
        self.assertEqual(len(plan.network.activities), 1)


class UnknownWorkIsNotZeroWorkTests(unittest.TestCase):
    """F03. Three states, because the engine needs three."""

    def _row(self, raw):
        row, extensions = _task(1)
        row["duration"] = {"raw": raw, "seconds": None, "parse_status": "unsupported"}
        return _plan(_document([(row, extensions)]))

    def test_a_duration_the_parser_cannot_read_excludes_its_row(self):
        schedule, plan, _ = self._row("P1M")
        self.assertEqual(plan.excluded_by_code(), {"ACTIVITY_DURATION_UNSUPPORTED": 1})
        self.assertEqual(plan.excluded[0].detail, "P1M")
        self.assertEqual(plan.network.activities, ())

    def test_a_non_integral_duration_is_refused_rather_than_truncated(self):
        row, extensions = _task(1)
        row["duration"] = {"raw": "PT0.5S", "seconds": 0.5, "parse_status": "parsed"}
        _, plan, _ = _plan(_document([(row, extensions)]))
        self.assertEqual(plan.excluded_by_code(), {"ACTIVITY_DURATION_NON_INTEGRAL": 1})

    def test_an_explicit_zero_is_still_a_milestone_and_still_schedules(self):
        row, extensions = _activity(
            1,
            start="2026-01-05T08:00:00",
            finish="2026-01-05T08:00:00",
            duration_seconds=0,
            milestone=True,
        )
        _, plan, _ = _plan(_document([(row, extensions)]))
        self.assertEqual(plan.excluded, ())
        self.assertEqual(len(plan.network.activities), 1)

    def test_unknown_work_does_not_let_its_successor_advance(self):
        """Dropping the edge is not enough, and the first version of this test
        did not check the thing it claimed.

        Excluding only the predecessor leaves the successor with no predecessor
        at all, so the forward pass treats it as a root and floors it at the
        project start -- *earlier* than the file puts it, which is the false
        advancement the exclusion exists to prevent. The successor is excluded
        with it.
        """

        row, extensions = _task(1)
        row["duration"] = {"raw": "P1M", "seconds": None, "parse_status": "unsupported"}
        schedule, plan, _ = _plan(
            _document([(row, extensions), _task(2)], relationships=[_relationship(1, 1, 2)])
        )
        self.assertEqual(
            plan.excluded_by_code(),
            {
                "ACTIVITY_DURATION_UNSUPPORTED": 1,
                "ACTIVITY_PREDECESSOR_NOT_SCHEDULED": 1,
                "RELATIONSHIP_ENDPOINT_NOT_SCHEDULED": 1,
            },
        )
        self.assertEqual(plan.network.activities, ())
        cut = next(
            row for row in plan.excluded if row.code == "ACTIVITY_PREDECESSOR_NOT_SCHEDULED"
        )
        self.assertEqual(cut.uid, schedule.activities[1].uid)
        self.assertEqual(cut.detail, str(schedule.activities[0].uid))

    def test_the_cut_follows_the_whole_chain(self):
        row, extensions = _task(1)
        row["duration"] = {"raw": "P1M", "seconds": None, "parse_status": "unsupported"}
        _, plan, _ = _plan(
            _document(
                [(row, extensions), _task(2), _task(3, hour=11), _task(4, hour=12)],
                relationships=[_relationship(1, 1, 2), _relationship(2, 2, 3)],
            )
        )
        # Task 4 has no predecessor at all and is untouched; 2 and 3 go.
        self.assertEqual(plan.excluded_by_code()["ACTIVITY_PREDECESSOR_NOT_SCHEDULED"], 2)
        self.assertEqual(len(plan.network.activities), 1)

    def test_completed_work_survives_the_cut_and_stops_it(self):
        """A finished activity is where the file says it finished.

        Both passes pin a complete activity to its actual dates and neither
        reads its predecessors (ADR-009), so cutting one would throw away
        recorded progress -- and everything after it reads *its* actual finish,
        which is known, so the cut stops there rather than travelling on.
        """

        unreadable, unreadable_extensions = _task(1)
        unreadable["duration"] = {
            "raw": "P1M",
            "seconds": None,
            "parse_status": "unsupported",
        }
        done, done_extensions = _task(2, hour=10)
        done["actual_start_source"] = "2026-01-05T10:00:00"
        done["actual_finish_source"] = "2026-01-05T11:00:00"
        done["remaining_duration_source"] = {
            "raw": "PT0S",
            "seconds": 0,
            "parse_status": "parsed",
        }
        schedule, plan, _ = _plan(
            _document(
                [
                    (unreadable, unreadable_extensions),
                    (done, done_extensions),
                    _task(3, hour=12),
                ],
                relationships=[_relationship(1, 1, 2), _relationship(2, 2, 3)],
            )
        )
        completed = next(a for a in schedule.activities if a.code == "2")
        beyond = next(a for a in schedule.activities if a.code == "3")
        scheduled = {row.uid for row in plan.network.activities}
        self.assertIn(completed.uid, scheduled)
        self.assertIn(beyond.uid, scheduled)
        self.assertNotIn("ACTIVITY_PREDECESSOR_NOT_SCHEDULED", plan.excluded_by_code())

    def test_a_successor_of_an_inactive_task_is_still_scheduled(self):
        """The measured rule the cut must not swallow (ADR-010)."""

        _, plan, _ = _plan(
            _document(
                [_task(1, active=False), _task(2)], relationships=[_relationship(1, 1, 2)]
            )
        )
        self.assertEqual(len(plan.network.activities), 1)
        self.assertEqual(plan.assumed_by_code(), {"ACTIVITY_SUCCESSOR_OF_INACTIVE": 1})
        self.assertNotIn("ACTIVITY_PREDECESSOR_NOT_SCHEDULED", plan.excluded_by_code())

    def test_an_unknown_duration_format_is_not_assumed_to_be_working_time(self):
        schedule, plan, _ = _plan(_document([_task(1, duration_format="999")]))
        self.assertEqual(
            schedule.activities[0].source_fields.get("duration_format_unsupported_source"),
            "999",
        )
        self.assertEqual(plan.excluded_by_code(), {"ACTIVITY_DURATION_FORMAT_UNSUPPORTED": 1})

    def test_a_non_numeric_duration_format_is_treated_the_same_way(self):
        _, plan, _ = _plan(_document([_task(1, duration_format="hours")]))
        self.assertEqual(plan.excluded_by_code(), {"ACTIVITY_DURATION_FORMAT_UNSUPPORTED": 1})


class NoDurationVanishesQuietlyTests(unittest.TestCase):
    """The rest of F03: every duration field, not only the two the plan reads."""

    def test_work_and_actual_duration_keep_what_could_not_be_read(self):
        row, extensions = _task(1)
        row["work"] = {"raw": "P1M", "seconds": None, "parse_status": "unsupported"}
        row["actual_duration_source"] = {
            "raw": "P2M",
            "seconds": None,
            "parse_status": "unsupported",
        }
        schedule, plan, _ = _plan(_document([(row, extensions)]))
        fields = schedule.activities[0].source_fields
        self.assertEqual(fields.get("work_unsupported_source"), "P1M")
        self.assertEqual(fields.get("actual_duration_unsupported_source"), "P2M")
        # Neither is a scheduling input, so the row is still scheduled.
        self.assertEqual(len(plan.network.activities), 1)

    def test_assignment_work_is_not_recorded_as_a_measured_zero(self):
        assignment = _assignment_row(1, 1, 1)
        assignment["work_source"] = {
            "raw": "P1M",
            "seconds": None,
            "parse_status": "unsupported",
        }
        schedule, _, _ = _plan(
            _document(
                [_task(1)],
                resources=[
                    {
                        "id": "resource:1",
                        "source_order": 1,
                        "external_references": [],
                        "name": "Sensitive resource",
                        "calendar_ref": "calendar:1",
                    }
                ],
                assignments=[assignment],
            )
        )
        row = schedule.assignments[0]
        self.assertEqual(row.work.budgeted_seconds, 0)
        self.assertEqual(row.source_fields.get("work_unsupported_source"), "P1M")
        self.assertEqual(row.source_fields.get("work_unsupported_reason"), "DURATION_UNSUPPORTED")

    def test_a_baseline_keeps_what_could_not_be_read(self):
        # A baseline state has no activity to borrow a marker from: the live
        # duration can parse while the baseline's does not.
        document = _document([_task(1)])
        document["baselines"] = [
            {
                "id": "baseline:0:task:1",
                "source_order": 1,
                "number": 0,
                "owner_kind": "Task",
                "owner_ref": "task:1",
                "values": {
                    "start": "2026-01-05T09:00:00",
                    "finish": "2026-01-05T10:00:00",
                    "duration": {
                        "raw": "P1M",
                        "seconds": None,
                        "parse_status": "unsupported",
                    },
                    "work": {"raw": "PT1H", "seconds": 3600, "parse_status": "parsed"},
                },
            }
        ]
        schedule, _, _ = _plan(document)
        self.assertTrue(schedule.baselines, "the fixture produced no baseline")
        state = schedule.baselines[0].activity_states[0]
        self.assertIsNone(state.duration_seconds)
        self.assertEqual(state.source_fields.get("duration_unsupported_source"), "P1M")
        self.assertEqual(state.work_seconds, 3600)
        # The activity's own duration read perfectly, so it carries no marker.
        self.assertNotIn("duration_unsupported_source", schedule.activities[0].source_fields)

    def test_a_null_duration_format_is_display_and_still_schedules(self):
        # Microsoft's codes 21 and 53 name no unit, but ``<Duration>`` is an
        # ISO span regardless. KILN carries forty-five such rows as ordinary
        # work, so they are scheduled and the code is preserved on the
        # duration rather than dispositioned.
        schedule, plan, _ = _plan(_document([_task(1, duration_format="21")]))
        duration = schedule.activities[0].planned_duration
        self.assertEqual((duration.source_format_code, duration.unit), (21, None))
        self.assertFalse(duration.elapsed)
        self.assertEqual(plan.excluded, ())
        self.assertEqual(len(plan.network.activities), 1)


class UnsupportedSchedulingPolicyIsReportedTests(unittest.TestCase):
    """F04. Manual placement and backward scheduling are not automatic."""

    def test_a_manual_row_is_excluded_rather_than_scheduled_as_automatic(self):
        row, extensions = _task(1)
        row["manual"] = True
        schedule, plan, _ = _plan(_document([(row, extensions), _task(2)]))
        self.assertTrue(schedule.activities[0].manual)
        self.assertEqual(plan.excluded_by_code(), {"ACTIVITY_MANUALLY_SCHEDULED": 1})

    def test_a_project_scheduled_from_its_finish_is_refused_by_name(self):
        document = _document([_task(1)])
        document["project"]["schedule_from_start"] = False
        schedule, _, _ = migrate(document)
        with self.assertRaises(PlanError) as raised:
            build_plan(schedule, HORIZON)
        self.assertEqual(raised.exception.code, "PROJECT_SCHEDULED_FROM_FINISH")

    def test_a_null_placeholder_is_not_ordinary_work(self):
        row, extensions = _task(1)
        row["is_null_source"] = True
        _, plan, _ = _plan(_document([(row, extensions)]))
        self.assertEqual(plan.excluded_by_code(), {"ACTIVITY_NULL_PLACEHOLDER": 1})


class OneGuidIsOneRowOfOneSnapshotTests(unittest.TestCase):
    """F05. Two rows sharing a GUID keep two identities."""

    def _document_with_shared_guid(self):
        first, first_extensions = _task(1)
        second, second_extensions = _task(2, hour=11)
        shared = [{"type": "GUID", "value": "AAAAAAAA-1111-2222-3333-444444444444"}]
        first["external_references"] = [{"type": "UID", "value": "1"}, *shared]
        second["external_references"] = [{"type": "UID", "value": "2"}, *shared]
        return _document([(first, first_extensions), (second, second_extensions)])

    def test_the_second_row_keeps_its_own_identity_and_is_reported(self):
        schedule, plan, report = _plan(self._document_with_shared_guid())
        self.assertEqual(len({a.uid for a in schedule.activities}), 2)
        self.assertEqual(report.guid_duplicated_in_snapshot, 1)
        self.assertEqual(report.duplicate_guids[0].external_uid, "2")
        self.assertEqual(len(plan.network.activities), 2)

    def test_a_duplicated_guid_is_retired_from_reconciliation_for_good(self):
        """The half of the fix the first attempt missed.

        Clearing the GUID on the *second* row is not enough: the first row has
        already taught the map that GUID, so a later import that renumbers
        either of them is rekeyed onto whichever appeared first. The duplicate
        is found before any row resolves, and the GUID is quarantined on the
        identity map, which persists.
        """

        schedule, identity, report = migrate(self._document_with_shared_guid())
        shared = "aaaaaaaa-1111-2222-3333-444444444444"
        self.assertIn(("activity", shared), identity.ambiguous_guids)
        self.assertNotIn(("activity", shared), identity.by_guid)
        self.assertEqual(report.guid_duplicated_in_snapshot, 1)

        # The quarantine survives the round trip through storage.
        stored = type(identity).from_dict(identity.to_dict())
        self.assertIn(("activity", shared), stored.ambiguous_guids)

        # A later import renumbers the first row. Without the quarantine its
        # GUID would rekey it; with it, the row is simply new and the row that
        # kept its source UID keeps its identity.
        renumbered, renumbered_extensions = _task(9)
        renumbered["external_references"] = [
            {"type": "UID", "value": "9"},
            {"type": "GUID", "value": "AAAAAAAA-1111-2222-3333-444444444444"},
        ]
        later, _, later_report = migrate(
            _document([(renumbered, renumbered_extensions)]), identity=stored
        )
        self.assertEqual(later_report.rekeyed, 0)
        self.assertNotIn(later.activities[0].uid, {a.uid for a in schedule.activities})

    def test_a_reused_guid_across_snapshots_still_rekeys(self):
        """The fallback this does not break: a row whose source UID changed."""

        first, first_extensions = _task(1)
        first["external_references"] = [
            {"type": "UID", "value": "1"},
            {"type": "GUID", "value": "BBBBBBBB-1111-2222-3333-444444444444"},
        ]
        earlier, identity, _ = migrate(_document([(first, first_extensions)]))
        renumbered, renumbered_extensions = _task(7)
        renumbered["external_references"] = [
            {"type": "UID", "value": "7"},
            {"type": "GUID", "value": "BBBBBBBB-1111-2222-3333-444444444444"},
        ]
        later, _, report = migrate(
            _document([(renumbered, renumbered_extensions)]), identity=identity
        )
        self.assertEqual(earlier.activities[0].uid, later.activities[0].uid)
        self.assertEqual(report.rekeyed, 1)
        self.assertEqual(report.guid_duplicated_in_snapshot, 0)


if __name__ == "__main__":
    unittest.main()
