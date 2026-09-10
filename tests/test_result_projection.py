"""A calculation, stored and read back (slice PL3).

ADR-006 deferred these columns until the engine had produced values for them
to hold. It has, so the question here is whether a stored calculation is
answerable later: does it say what it was computed from, under which rules and
over which window, and does what comes back out of the database match what
went in?

The database tests need PostgreSQL and the api extra; ``STO_REQUIRE_DB=1``
turns their absence into a failure rather than a skip, which is what the api
CI job sets.
"""

from __future__ import annotations

import os
import secrets
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4
from threading import Event, Thread

from calculation_fixture import _activity, _document, _relationship

from sto.core.engine import (
    backward_pass,
    build_plan,
    float_analysis,
    forward_pass,
    roll_up,
)
from sto.core.engine.result import (
    EXCLUDED,
    RELEASED,
    SCHEDULED,
    fingerprint_result,
    project_result,
)
from sto.core.hashing import canonical_sha256
from sto.core.model.codec import encode_schedule
from sto.core.model.entities import Constraint
from sto.core.model.enums import ConstraintType
from sto.core.model.migrate.sto_v011 import migrate
from sto.legacy import import_mspdi

REQUIRE_DB = os.environ.get("STO_REQUIRE_DB") == "1"
ADMIN_URL = os.environ.get("STO_TEST_ADMIN_URL", "postgresql://postgres@127.0.0.1:5433/postgres")
REPO_ROOT = Path(__file__).resolve().parent.parent
MIGRATIONS = REPO_ROOT / "infra" / "migrations"
FIXTURE = REPO_ROOT / "tests" / "fixtures" / "synthetic-workspace-chain.mspdi.xml"

try:
    import psycopg
except ImportError as error:  # the bare suite: no extra installed
    if REQUIRE_DB:
        raise RuntimeError(f"STO_REQUIRE_DB=1 but psycopg is not installed ({error.name})") from error
    psycopg = None  # type: ignore[assignment]


def _reachable() -> bool:
    if psycopg is None:
        return False
    try:
        with psycopg.connect(ADMIN_URL, connect_timeout=3):
            return True
    except psycopg.OperationalError as error:
        if REQUIRE_DB:
            raise RuntimeError(f"STO_REQUIRE_DB=1 but {ADMIN_URL} is unreachable: {error}") from error
        return False


AVAILABLE = _reachable()


def _projected(path: Path, *, before=timedelta(days=90), after=timedelta(days=365)):
    schedule, _, _ = migrate(import_mspdi(str(path)))
    start = schedule.project.start or datetime(2026, 1, 5)
    horizon = (start - before, start + after)
    plan = build_plan(schedule, horizon)
    forward = forward_pass(
        plan.network, snap_milestones=plan.snap_milestones, progress_policy=plan.progress_policy
    )
    backward = backward_pass(plan.network, forward, snap_milestones=plan.snap_milestones)
    floats = float_analysis(
        plan.network, forward, backward, threshold=plan.critical_float_threshold
    )
    rollup = roll_up(
        plan.wbs_children,
        {uid: (row.early_start, row.early_finish) for uid, row in forward.by_uid().items()},
    )
    return schedule, project_result(
        plan,
        forward,
        backward,
        floats,
        rollup,
        canonical_hash=canonical_sha256(encode_schedule(schedule)),
        horizon=horizon,
    )


def repo_module():
    from sto.persistence import repositories

    return repositories


def _projected_document(document, *, before=timedelta(days=90), after=timedelta(days=365)):
    """The same road as :func:`_projected`, from a built document rather than a file."""

    schedule, _, _ = migrate(document)
    return _projected_schedule(schedule, before=before, after=after)


def _projected_schedule(schedule, *, before=timedelta(days=90), after=timedelta(days=365)):
    start = schedule.project.start or datetime(2026, 1, 5)
    horizon = (start - before, start + after)
    plan = build_plan(schedule, horizon)
    forward = forward_pass(
        plan.network, snap_milestones=plan.snap_milestones, progress_policy=plan.progress_policy
    )
    backward = backward_pass(plan.network, forward, snap_milestones=plan.snap_milestones)
    floats = float_analysis(
        plan.network, forward, backward, threshold=plan.critical_float_threshold
    )
    rollup = roll_up(
        plan.wbs_children,
        {uid: (row.early_start, row.early_finish) for uid, row in forward.by_uid().items()},
    )
    return plan, project_result(
        plan,
        forward,
        backward,
        floats,
        rollup,
        canonical_hash=canonical_sha256(encode_schedule(schedule)),
        horizon=horizon,
    )


def _task(uid, hour=9):
    return _activity(
        uid,
        start=f"2026-01-05T{hour:02d}:00:00",
        finish=f"2026-01-05T{hour + 1:02d}:00:00",
        duration_seconds=3600,
    )


class WhatElseDecidedTheseDatesTests(unittest.TestCase):
    """A stored answer names every disposition behind it, not only the rows.

    Each case here is one the review of this slice found: something the plan
    decided, that moved the dates, and that the projection dropped on the way
    to the database -- so the stored calculation looked fully evidenced when it
    was not.
    """

    def test_an_edge_kept_under_a_labelled_rule_is_recorded(self):
        """An inherited working lag runs on the project calendar by a rule the
        estate cannot distinguish from elapsed time (ADR-010). The dates rest
        on that label, so the label is part of the result."""

        document = _document([_task(1), _task(2)], relationships=[_relationship(1, 1, 2, lag=600)])
        plan, result = _projected_document(document)
        labelled = [row for row in plan.assumed if row.kind == "relationship"]
        self.assertTrue(labelled, "the fixture no longer produces a relationship assumption")
        self.assertEqual(
            [(row.disposition, row.code) for row in result.relationships],
            [(SCHEDULED, row.code) for row in labelled],
        )

    def test_a_dropped_edge_is_recorded_too(self):
        """An edge whose predecessor was not scheduled is not in the network,
        and its absence is why the successor sits where it does."""

        inactive, extensions = _task(1)
        inactive["active"] = False
        document = _document(
            [(inactive, extensions), _task(2)], relationships=[_relationship(1, 1, 2)]
        )
        _, result = _projected_document(document)
        self.assertIn(
            (EXCLUDED, "RELATIONSHIP_ENDPOINT_NOT_SCHEDULED"),
            [(row.disposition, row.code) for row in result.relationships],
        )

    def test_dropping_a_label_changes_the_fingerprint(self):
        document = _document([_task(1), _task(2)], relationships=[_relationship(1, 1, 2, lag=600)])
        _, full = _projected_document(document)
        stripped = replace(full, relationships=())
        self.assertNotEqual(fingerprint_result(full), fingerprint_result(stripped))

    def test_a_discarded_status_date_is_not_an_absent_one(self):
        """Two runs with the same dates and different inputs must not hash alike."""

        document = _document([_task(1), _task(2)])
        _, without = _projected_document(document)
        stale = _document([_task(1), _task(2)])
        stale["project"]["status_date"] = "2025-01-01T08:00:00"
        plan, discarded = _projected_document(stale)

        self.assertTrue(plan.status_time_outside_window)
        self.assertIsNone(plan.network.status_time)
        self.assertFalse(without.provenance.status_time_outside_window)
        self.assertTrue(discarded.provenance.status_time_outside_window)
        self.assertIsNone(discarded.provenance.status_time)
        self.assertNotEqual(without.fingerprint, discarded.fingerprint)

    def test_the_progress_rules_are_named_like_every_other_stage(self):
        _, result = _projected(FIXTURE)
        self.assertTrue(result.provenance.progress_profile.startswith("sto-progress-"))
        self.assertIn("progress_profile", result.provenance.to_dict())

    def test_a_secondary_constraint_answers_the_row_once(self):
        """The row is scheduled; only its second constraint is not applied.

        Recorded as an exclusion it made one activity both scheduled and
        excluded, which is not a partition, and which a result keyed on the
        activity cannot store twice.
        """

        schedule, _, _ = migrate(_document([_task(1), _task(2)]))
        first = schedule.activities[0]
        constrained = replace(
            first,
            secondary_constraint=Constraint(
                type=ConstraintType.FNLT, date=datetime(2026, 1, 9, 16)
            ),
        )
        schedule = replace(schedule, activities=(constrained,) + schedule.activities[1:])
        plan, result = _projected_schedule(schedule)

        rows = [row for row in result.activities if row.uid == first.uid]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].disposition, SCHEDULED)
        self.assertIn("ACTIVITY_SECONDARY_CONSTRAINT_NOT_APPLIED", rows[0].assumptions)
        self.assertEqual(
            [row.code for row in plan.excluded if row.uid == first.uid],
            [],
            "a scheduled row must not also be excluded",
        )


    def test_a_late_span_says_what_bounded_it(self):
        """Four dates, and until now the cause of only two of them.

        In a chain the late span is bounded by a successor while the early one
        is bounded by a predecessor, so copying the forward pass's driver onto
        both left half the stored row unexplained.
        """

        document = _document([_task(1), _task(2)], relationships=[_relationship(1, 1, 2)])
        _, result = _projected_document(document)
        rows = [row for row in result.activities if row.disposition == SCHEDULED]
        self.assertTrue(rows)
        for row in rows:
            with self.subTest(str(row.uid)):
                self.assertIsNotNone(row.late_placed_by)
        driven = [row for row in rows if row.late_driving_relationship_uid is not None]
        self.assertTrue(driven, "no row reports a late driver; this would pass vacuously")
        self.assertNotEqual(
            [(row.driving_relationship_uid, row.late_driving_relationship_uid) for row in driven],
            [(row.late_driving_relationship_uid, row.late_driving_relationship_uid)
             for row in driven],
            "the late driver is a copy of the early one",
        )

    def test_a_constraint_that_overrode_its_logic_is_carried(self):
        """A hard constraint wins against a predecessor, and says what it broke."""

        first, first_ext = _task(1)
        second, second_ext = _task(2)
        second["constraint_type_source"] = 2  # must start on
        second["constraint_date_source"] = "2026-01-05T08:00:00"
        document = _document(
            [(first, first_ext), (second, second_ext)],
            relationships=[_relationship(1, 1, 2)],
        )
        schedule, _, _ = migrate(document)
        plan, result = _projected_schedule(schedule)
        forward = forward_pass(
            plan.network,
            snap_milestones=plan.snap_milestones,
            progress_policy=plan.progress_policy,
        )
        self.assertTrue(
            forward.constraint_violations, "the fixture no longer overrides its logic"
        )
        overridden = {
            row.uid for row in result.activities if row.constraint_override is not None
        }
        self.assertEqual(
            overridden, {row.activity_uid for row in forward.constraint_violations}
        )

    def test_a_start_nothing_bounds_is_labelled(self):
        """The project-start fallback is a rule with no file evidence.

        The forward pass records a row only when that fallback *decided* where
        it went, and on every real schedule here it decides nothing -- so a
        test built from a file would assert two empty sets and prove nothing.
        The pass's own report is set directly instead, which is the thing the
        projection was dropping.
        """

        document = _document([_task(1), _task(2)])
        schedule, _, _ = migrate(document)
        start = schedule.project.start
        horizon = (start - timedelta(days=90), start + timedelta(days=365))
        plan = build_plan(schedule, horizon)
        forward = forward_pass(
            plan.network,
            snap_milestones=plan.snap_milestones,
            progress_policy=plan.progress_policy,
        )
        self.assertEqual(forward.unbounded_starts, (), "the fixture now triggers it for real")
        backward = backward_pass(plan.network, forward, snap_milestones=plan.snap_milestones)
        floats = float_analysis(
            plan.network, forward, backward, threshold=plan.critical_float_threshold
        )
        rollup = roll_up(
            plan.wbs_children,
            {uid: (row.early_start, row.early_finish) for uid, row in forward.by_uid().items()},
        )

        def project(pass_):
            return project_result(
                plan,
                pass_,
                backward,
                floats,
                rollup,
                canonical_hash=canonical_sha256(encode_schedule(schedule)),
                horizon=horizon,
            )

        named = plan.network.activities[0].uid
        reported = replace(forward, unbounded_starts=(named,))
        labelled = {
            row.uid
            for row in project(reported).activities
            if "ACTIVITY_START_NOT_BOUNDED" in row.assumptions
        }
        self.assertEqual(labelled, {named})
        # And it is part of what the result hashes to, so a stored calculation
        # that rests on the fallback cannot pass for one that does not.
        self.assertNotEqual(project(reported).fingerprint, project(forward).fingerprint)

    def test_an_edge_the_passes_released_is_recorded(self):
        """The plan kept it; progress meant the passes did not walk it.

        Neither an exclusion nor an ordinary scheduled edge: it took no part in
        the late dates or the float, and a result that recorded only the plan's
        dispositions showed a retained edge taking part in dates it did not.
        """

        first, first_ext = _task(1)
        first["actual_start_source"] = "2026-01-05T09:00:00"
        first["actual_finish_source"] = "2026-01-05T10:00:00"
        first["percent_complete_source"] = 100
        second, second_ext = _task(2, hour=11)
        second["actual_start_source"] = "2026-01-05T11:00:00"
        second["actual_finish_source"] = "2026-01-05T12:00:00"
        second["percent_complete_source"] = 100
        document = _document(
            [(first, first_ext), (second, second_ext)],
            relationships=[_relationship(1, 1, 2, lag=600)],
        )
        document["project"]["status_date"] = "2026-01-06T08:00:00"
        schedule, _, _ = migrate(document)
        plan, result = _projected_schedule(schedule)
        backward = backward_pass(
            plan.network,
            forward_pass(
                plan.network,
                snap_milestones=plan.snap_milestones,
                progress_policy=plan.progress_policy,
            ),
            snap_milestones=plan.snap_milestones,
        )
        self.assertTrue(
            backward.overridden_relationships, "the fixture no longer releases an edge"
        )
        released = {
            edge.uid for edge in result.relationships if edge.disposition == RELEASED
        }
        self.assertEqual(released, set(backward.overridden_relationships))
        self.assertFalse(
            [
                edge
                for edge in result.relationships
                if edge.uid in released and edge.disposition == SCHEDULED
            ],
            "a released edge must not also be presented as an applied assumption",
        )

    def test_both_float_components_reach_the_row(self):
        """Total float is the smaller of two readings; the other is kept."""

        _, result = _projected(FIXTURE)
        placed = [row for row in result.activities if row.disposition == SCHEDULED]
        self.assertTrue(placed)
        for row in placed:
            with self.subTest(str(row.uid)):
                self.assertIsNotNone(row.start_float)
                self.assertIsNotNone(row.finish_float)
                self.assertEqual(row.total_float, min(row.start_float, row.finish_float))

    def test_a_component_change_moves_the_fingerprint(self):
        """The half a stored minimum could not notice."""

        _, result = _projected(FIXTURE)
        rows = list(result.activities)
        index = next(
            i for i, row in enumerate(rows) if row.disposition == SCHEDULED
        )
        # Raise only the larger component: the minimum, and so total float,
        # is unchanged.
        row = rows[index]
        larger = "start_float" if row.start_float > row.finish_float else "finish_float"
        rows[index] = replace(row, **{larger: max(row.start_float, row.finish_float) + 60})
        self.assertNotEqual(
            fingerprint_result(result),
            fingerprint_result(replace(result, activities=tuple(rows))),
        )

    def test_the_calendar_policy_is_part_of_what_produced_the_answer(self):
        """A caller's choice that moves the dates, and was not recorded."""

        document = _document([_task(1), _task(2)])
        schedule, _, _ = migrate(document)
        start = schedule.project.start
        horizon = (start - timedelta(days=90), start + timedelta(days=365))

        def project(apply_resource_calendars):
            plan = build_plan(
                schedule, horizon, resource_calendars_apply=apply_resource_calendars
            )
            forward = forward_pass(
                plan.network,
                snap_milestones=plan.snap_milestones,
                progress_policy=plan.progress_policy,
            )
            backward = backward_pass(plan.network, forward, snap_milestones=plan.snap_milestones)
            floats = float_analysis(
                plan.network, forward, backward, threshold=plan.critical_float_threshold
            )
            rollup = roll_up(
                plan.wbs_children,
                {
                    uid: (row.early_start, row.early_finish)
                    for uid, row in forward.by_uid().items()
                },
            )
            return project_result(
                plan,
                forward,
                backward,
                floats,
                rollup,
                canonical_hash=canonical_sha256(encode_schedule(schedule)),
                horizon=horizon,
            )

        applied = project(True)
        ignored = project(False)
        self.assertTrue(applied.provenance.resource_calendars_apply)
        self.assertFalse(ignored.provenance.resource_calendars_apply)
        # This fixture has no assignments, so the two rule sets give identical
        # dates -- which is exactly the case a stored result could not tell
        # apart before, and the fingerprint now can.
        self.assertNotEqual(applied.fingerprint, ignored.fingerprint)

    def test_an_exclusion_carries_what_its_code_cannot_say(self):
        """The predecessor named, not just the fact of a missing one."""

        first, first_ext = _task(1)
        first["duration"] = {"raw": "P1M", "seconds": None, "parse_status": "unsupported"}
        document = _document(
            [(first, first_ext), _task(2)], relationships=[_relationship(1, 1, 2)]
        )
        _, result = _projected_document(document)
        cascaded = [
            row
            for row in result.activities
            if row.exclusion_code == "ACTIVITY_PREDECESSOR_NOT_SCHEDULED"
        ]
        self.assertTrue(cascaded, "the fixture no longer cascades an exclusion")
        for row in cascaded:
            with self.subTest(str(row.uid)):
                self.assertTrue(row.exclusion_detail, "the code alone cannot name the predecessor")

class TheProjectionAnswersForEveryRowTests(unittest.TestCase):
    """No database needed: the assembly itself."""

    def test_every_activity_appears_exactly_once(self):
        schedule, result = _projected(FIXTURE)
        self.assertEqual(
            sorted(str(row.uid) for row in result.activities),
            sorted(str(activity.uid) for activity in schedule.activities),
        )

    def test_a_scheduled_row_has_dates_and_an_excluded_one_has_a_reason(self):
        _, result = _projected(FIXTURE)
        for row in result.activities:
            with self.subTest(str(row.uid)):
                if row.disposition == SCHEDULED:
                    self.assertIsNotNone(row.early_start)
                    self.assertIsNotNone(row.late_finish)
                    self.assertIsNotNone(row.total_float)
                    self.assertIsNone(row.exclusion_code)
                else:
                    self.assertEqual(row.disposition, EXCLUDED)
                    self.assertIsNone(row.early_start)
                    self.assertIsNotNone(row.exclusion_code)

    def test_the_result_names_what_produced_it(self):
        schedule, result = _projected(FIXTURE)
        provenance = result.provenance
        self.assertEqual(provenance.canonical_hash, canonical_sha256(encode_schedule(schedule)))
        self.assertEqual(provenance.result_profile, "sto-result-v1")
        self.assertTrue(provenance.forward_profile.startswith("sto-forward-pass-"))
        self.assertLess(provenance.horizon_start, provenance.horizon_finish)

    def test_two_runs_of_one_schedule_hash_alike(self):
        _, first = _projected(FIXTURE)
        _, second = _projected(FIXTURE)
        self.assertEqual(first.fingerprint, second.fingerprint)

    def test_a_wider_window_is_a_different_calculation_and_says_so(self):
        """The horizon is the caller's choice, so it is part of the identity."""

        _, narrow = _projected(FIXTURE, before=timedelta(days=30))
        _, wide = _projected(FIXTURE, before=timedelta(days=90))
        self.assertNotEqual(narrow.fingerprint, wide.fingerprint)
        self.assertNotEqual(
            narrow.provenance.horizon_start, wide.provenance.horizon_start
        )


@unittest.skipUnless(psycopg is not None, "the persistence extra is not installed")
class RefreshCacheTests(unittest.TestCase):
    def test_a_point_in_time_refresh_does_not_replace_a_newer_resident_head(self):
        """A slow calculation read must not undo an import's cache update."""

        from sto.scheduling.working_schedule import WorkingSchedule, Workspace

        project_id = uuid4()
        older = WorkingSchedule(project_id, uuid4(), 1, "a" * 64, object(), object())
        newer = WorkingSchedule(project_id, uuid4(), 2, "b" * 64, object(), object())

        class Connection:
            def __enter__(self):
                return object()

            def __exit__(self, *args):
                return False

        workspace = Workspace(connect=Connection)
        workspace._resident[project_id] = newer
        with (
            patch("sto.scheduling.working_schedule.repo.get_project", return_value={}),
            patch(
                "sto.scheduling.working_schedule.repo.head_version",
                return_value={"id": older.version_id},
            ),
            patch("sto.scheduling.working_schedule._verify", return_value=older),
        ):
            refreshed = workspace.load(project_id, refresh=True)

        self.assertIs(refreshed, older)
        self.assertIs(workspace._resident[project_id], newer)

    def test_a_failed_old_refresh_does_not_evict_or_accuse_a_newer_resident_head(self):
        """A corrupt snapshot cannot overwrite a concurrent import's cache state."""

        from sto.scheduling.working_schedule import (
            IntegrityError,
            WorkingSchedule,
            Workspace,
        )

        project_id = uuid4()
        older = WorkingSchedule(project_id, uuid4(), 1, "a" * 64, object(), object())
        newer = WorkingSchedule(project_id, uuid4(), 2, "b" * 64, object(), object())

        class Connection:
            def __enter__(self):
                return object()

            def __exit__(self, *args):
                return False

        workspace = Workspace(connect=Connection)

        def fail_after_newer_head_was_published(*_args):
            workspace._resident[project_id] = newer
            raise IntegrityError("old head is corrupt")

        with (
            patch("sto.scheduling.working_schedule.repo.get_project", return_value={}),
            patch(
                "sto.scheduling.working_schedule.repo.head_version",
                return_value={"id": older.version_id},
            ),
            patch(
                "sto.scheduling.working_schedule._verify",
                side_effect=fail_after_newer_head_was_published,
            ),
            self.assertRaises(IntegrityError),
        ):
            workspace.load(project_id, refresh=True)

        self.assertIs(workspace._resident[project_id], newer)
        self.assertNotIn(project_id, workspace.integrity_failures)

    def test_import_publication_waiting_after_the_second_head_read_wins_atomically(self):
        """The head check and quarantine publication are one cache operation."""

        from sto.scheduling.working_schedule import (
            IntegrityError,
            WorkingSchedule,
            Workspace,
        )

        project_id = uuid4()
        older = WorkingSchedule(project_id, uuid4(), 1, "a" * 64, object(), object())
        newer = WorkingSchedule(project_id, uuid4(), 2, "b" * 64, object(), object())
        second_read = Event()
        publication_waiting = Event()

        class Connection:
            def __enter__(self):
                return object()

            def __exit__(self, *args):
                return False

        workspace = Workspace(connect=Connection)

        def head_version(_conn, *, with_document, **_kwargs):
            if not with_document:
                second_read.set()
                self.assertTrue(publication_waiting.wait(2))
            return {"id": older.version_id}

        def publish_import():
            self.assertTrue(second_read.wait(2))
            publication_waiting.set()
            with workspace._state_lock:
                workspace._resident[project_id] = newer
                workspace.integrity_failures.pop(project_id, None)

        publisher = Thread(target=publish_import)
        publisher.start()
        try:
            with (
                patch("sto.scheduling.working_schedule.repo.get_project", return_value={}),
                patch(
                    "sto.scheduling.working_schedule.repo.head_version",
                    side_effect=head_version,
                ),
                patch(
                    "sto.scheduling.working_schedule._verify",
                    side_effect=IntegrityError("old head is corrupt"),
                ),
                self.assertRaises(IntegrityError),
            ):
                workspace.load(project_id, refresh=True)
        finally:
            publisher.join(2)

        self.assertFalse(publisher.is_alive())
        self.assertIs(workspace._resident[project_id], newer)
        self.assertNotIn(project_id, workspace.integrity_failures)


@unittest.skipUnless(
    AVAILABLE,
    "PostgreSQL or the api extra not available; set STO_REQUIRE_DB=1 to make this a failure",
)
class AStoredCalculationComesBackTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from sto.persistence.db import connect

        cls.dbname = f"sto_result_{secrets.token_hex(4)}"
        with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
            admin.execute(f'CREATE DATABASE "{cls.dbname}"')
        cls.url = ADMIN_URL.rsplit("/", 1)[0] + "/" + cls.dbname
        with psycopg.connect(cls.url) as conn:
            for path in sorted(MIGRATIONS.glob("V*.sql")):
                conn.execute(path.read_text(encoding="utf-8"))
            conn.commit()
        cls.tmp = tempfile.TemporaryDirectory()
        cls.connect = staticmethod(lambda url=cls.url: connect(url))

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()
        with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
            admin.execute(f'DROP DATABASE "{cls.dbname}" WITH (FORCE)')

    def _workspace(self):
        from sto.scheduling.working_schedule import Workspace

        return Workspace(connect=self.connect, source_dir=Path(self.tmp.name))

    def _imported(self):
        workspace = self._workspace()
        from sto.persistence import repositories as repo

        with self.connect() as conn:
            project = repo.create_project(conn, name="projection")
            conn.commit()
        workspace.import_file(
            project["id"], filename=FIXTURE.name, data=FIXTURE.read_bytes()
        )
        return workspace, project["id"]

    def test_a_calculation_is_stored_and_read_back_unchanged(self):
        from sto.persistence import repositories as repo

        workspace, project_id = self._imported()
        stored = workspace.calculate(project_id)
        _, expected = _projected(FIXTURE)

        self.assertEqual(stored.fingerprint, expected.fingerprint)
        with self.connect() as conn:
            header = repo.get_latest_calculation(conn, version_id=stored.version_id)
            rows = repo.get_activity_results(conn, calculation_id=stored.calculation_id)
            summaries = repo.get_summary_results(conn, calculation_id=stored.calculation_id)

        self.assertEqual(header["result_fingerprint"], expected.fingerprint)
        self.assertEqual(header["canonical_hash"], stored.canonical_hash)
        self.assertEqual(header["profiles"]["result"], "sto-result-v1")
        self.assertEqual(len(rows), len(expected.activities))
        self.assertEqual(
            len(summaries), len(expected.summaries) + len(expected.empty_summaries)
        )

        by_uid = expected.by_uid()
        for row in rows:
            with self.subTest(str(row["activity_uid"])):
                source = by_uid[row["activity_uid"]]
                self.assertEqual(row["disposition"], source.disposition)
                self.assertEqual(row["early_start"], source.early_start)
                self.assertEqual(row["late_finish"], source.late_finish)
                self.assertEqual(row["total_float_seconds"], source.total_float)
                self.assertEqual(row["critical"], source.critical)
                self.assertEqual(row["exclusion_code"], source.exclusion_code)

    def test_recalculating_the_same_head_stores_a_second_run_not_an_edit(self):
        """A calculation is immutable, like the version it was computed from."""

        from sto.persistence import repositories as repo

        workspace, project_id = self._imported()
        first = workspace.calculate(project_id)
        second = workspace.calculate(project_id, before=timedelta(days=30))
        self.assertNotEqual(first.calculation_id, second.calculation_id)
        self.assertNotEqual(first.fingerprint, second.fingerprint)
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT count(*) AS n FROM schedule_calculations WHERE version_id = %s",
                (first.version_id,),
            ).fetchone()
        self.assertEqual(rows["n"], 2)

    def test_the_same_calculation_twice_is_the_same_row_not_a_second_one(self):
        """Asking again is an ordinary thing to do, not an error.

        A calculation is deterministic: the same document over the same window
        under the same rules is the same answer, and the table holds it once.
        The second ask used to collide with the uniqueness constraint, which
        reached a caller as a server fault for clicking a button twice.
        """

        workspace, project_id = self._imported()
        first = workspace.calculate(project_id)
        second = workspace.calculate(project_id)

        self.assertFalse(first.already_stored)
        self.assertTrue(second.already_stored)
        self.assertEqual(second.calculation_id, first.calculation_id)
        self.assertEqual(second.fingerprint, first.fingerprint)
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT count(*) AS n FROM schedule_calculations WHERE version_id = %s",
                (first.version_id,),
            ).fetchone()
        self.assertEqual(rows["n"], 1)

    def test_a_duplicate_insert_yields_to_the_row_that_is_there(self):
        """Two callers can reach the insert; one of them has to lose politely.

        The uniqueness constraint is still what enforces one row per answer.
        What changed is that losing to it is not an exception any more: the
        winner is the row this caller would have written, so the insert
        reports that it wrote nothing and the caller looks it up.
        """

        from sto.persistence import repositories as repo

        workspace, project_id = self._imported()
        stored = workspace.calculate(project_id)
        _, result = _projected(FIXTURE)
        with self.connect() as conn:
            self.assertIsNone(
                repo.insert_calculation(
                    conn,
                    project_id=project_id,
                    version_id=stored.version_id,
                    result=result,
                )
            )
            found = repo.find_calculation(
                conn, version_id=stored.version_id, fingerprint=result.fingerprint
            )
            rows = conn.execute(
                "SELECT count(*) AS n FROM schedule_calculations WHERE version_id = %s",
                (stored.version_id,),
            ).fetchone()
        self.assertEqual(found["id"], stored.calculation_id)
        self.assertEqual(rows["n"], 1)

    def test_reusing_a_calculation_checks_the_rows_it_is_reusing(self):
        """Reuse is service, so it goes through the fingerprint check."""

        from sto.scheduling.working_schedule import IntegrityError

        workspace, project_id = self._imported()
        stored = workspace.calculate(project_id)
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE activity_results
                SET early_finish = early_finish + interval '1 day'
                WHERE calculation_id = %s AND disposition = 'scheduled'
                """,
                (stored.calculation_id,),
            )
            conn.commit()
        with self.assertRaises(IntegrityError):
            workspace.calculate(project_id)


    def test_a_stored_calculation_is_checked_against_its_own_rows(self):
        """The header's fingerprint attests to rows in two other tables.

        A version is protected by re-deriving its hash on every load. A
        calculation cannot borrow that, so reading one back reassembles it and
        recomputes the fingerprint. Without this, a row edited after the insert
        is served as an answer while the header still vouches for the original.
        """

        from sto.scheduling.working_schedule import IntegrityError

        workspace, project_id = self._imported()
        stored = workspace.calculate(project_id)

        read = workspace.read_calculation(project_id)
        self.assertIsNotNone(read)
        self.assertEqual(read.calculation_id, stored.calculation_id)
        self.assertEqual(read.result.fingerprint, stored.fingerprint)

        with self.connect() as conn:
            conn.execute(
                """
                UPDATE activity_results SET early_finish = early_finish + interval '1 day'
                WHERE calculation_id = %s AND disposition = 'scheduled'
                AND activity_uid = (
                    SELECT activity_uid FROM activity_results
                    WHERE calculation_id = %s AND disposition = 'scheduled'
                    ORDER BY activity_uid LIMIT 1
                )
                """,
                (stored.calculation_id, stored.calculation_id),
            )
            conn.commit()

        with self.assertRaises(IntegrityError):
            workspace.read_calculation(project_id)

    def test_an_edited_summary_row_is_caught_as_well(self):
        from sto.scheduling.working_schedule import IntegrityError

        workspace, project_id = self._imported()
        stored = workspace.calculate(project_id)
        with self.connect() as conn:
            changed = conn.execute(
                """
                UPDATE summary_results SET placed = placed + 1
                WHERE calculation_id = %s AND span_start IS NOT NULL
                """,
                (stored.calculation_id,),
            ).rowcount
            conn.commit()
        self.assertGreater(changed, 0, "the fixture no longer produces summary rows")
        with self.assertRaises(IntegrityError):
            workspace.read_calculation(project_id)

    def test_calculating_reads_the_document_back_out_of_the_database(self):
        """Import leaves its own copy resident; the calculation must not use it.

        Otherwise a document altered between the insert and the run is
        computed over without the hash check this class exists for ever
        touching the bytes the row actually holds.
        """

        from sto.scheduling.working_schedule import IntegrityError

        workspace, project_id = self._imported()
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE schedule_versions
                SET document = jsonb_set(document, '{project,name}', '"renamed after the insert"')
                WHERE id = (SELECT version_id FROM schedule_heads
                            WHERE project_id = %s AND kind = 'baseline')
                """,
                (project_id,),
            )
            conn.commit()
        with self.assertRaises(IntegrityError):
            workspace.calculate(project_id)

    def test_a_calculation_is_refused_when_import_moves_the_head_mid_run(self):
        """The computed version cannot be reported as the new head's result."""

        from sto.core.engine import forward_pass as engine_forward_pass
        from sto.persistence import repositories as repo
        from sto.scheduling.working_schedule import StaleSchedule

        workspace, project_id = self._imported()
        first = workspace.load(project_id)
        second_import = workspace.import_file(
            project_id,
            filename="second.xml",
            data=FIXTURE.read_bytes().replace(
                b"<Name>Workspace chain</Name>",
                b"<Name>Workspace chain two</Name>",
                1,
            ),
        )
        with self.connect() as conn:
            repo.set_head(
                conn,
                project_id=project_id,
                kind="baseline",
                version_id=first.version_id,
            )
            conn.commit()

        moved = False

        def move_head_then_calculate(*args, **kwargs):
            nonlocal moved
            if not moved:
                with self.connect() as conn:
                    repo.set_head(
                        conn,
                        project_id=project_id,
                        kind="baseline",
                        version_id=second_import.version_id,
                    )
                    conn.commit()
                moved = True
            return engine_forward_pass(*args, **kwargs)

        with patch(
            "sto.scheduling.working_schedule.forward_pass",
            side_effect=move_head_then_calculate,
        ):
            with self.assertRaises(StaleSchedule):
                workspace.calculate(project_id)

        with self.connect() as conn:
            self.assertIsNone(
                repo.get_latest_calculation(conn, version_id=first.version_id)
            )

    def test_an_excluded_row_can_not_carry_a_remaining_start(self):
        """An excluded row has no dates at all, and the database says so."""

        workspace, project_id = self._imported()
        stored = workspace.calculate(project_id)
        with self.connect() as conn, self.assertRaises(psycopg.errors.CheckViolation):
            conn.execute(
                """
                INSERT INTO activity_results
                  (calculation_id, activity_uid, disposition, remaining_start, exclusion_code)
                VALUES (%s, gen_random_uuid(), 'excluded', %s, 'ACTIVITY_INACTIVE')
                """,
                (stored.calculation_id, datetime(2026, 1, 5, 8)),
            )

    def test_remaining_start_belongs_to_the_in_progress_rows(self):
        workspace, project_id = self._imported()
        stored = workspace.calculate(project_id)
        with self.connect() as conn, self.assertRaises(psycopg.errors.CheckViolation):
            conn.execute(
                """
                INSERT INTO activity_results
                  (calculation_id, activity_uid, disposition, early_start, early_finish,
                   late_start, late_finish, remaining_start, total_float_seconds,
                   free_float_seconds, critical, progress_state)
                VALUES (%s, gen_random_uuid(), 'scheduled', %s, %s, %s, %s, %s, 0, 0,
                        true, 'not_started')
                """,
                (
                    stored.calculation_id,
                    datetime(2026, 1, 5, 8),
                    datetime(2026, 1, 5, 16),
                    datetime(2026, 1, 5, 8),
                    datetime(2026, 1, 5, 16),
                    datetime(2026, 1, 5, 9),
                ),
            )

    def test_a_run_whose_status_date_was_discarded_says_so_in_the_row(self):
        workspace, project_id = self._imported()
        stored = workspace.calculate(project_id)
        with self.connect() as conn:
            header = repo_module().get_calculation(conn, calculation_id=stored.calculation_id)
        self.assertIn("status_time_outside_window", header)
        self.assertIn("progress", header["profiles"])
        self.assertIsInstance(header["relationship_dispositions"], list)


    def test_a_calculation_is_read_on_behalf_of_its_own_project(self):
        """Addressed by identifier, but read for a project."""

        # Imported here, not at module scope: this module runs in the bare
        # suite too, and reaching the workspace pulls in psycopg.
        from sto.persistence import repositories as repo
        from sto.scheduling.working_schedule import UnknownProject

        workspace, project_id = self._imported()
        stored = workspace.calculate(project_id)
        with self.connect() as conn:
            other = repo.create_project(conn, name="somebody else")
            conn.commit()
        with self.assertRaises(UnknownProject):
            workspace.read_calculation(other["id"], calculation_id=stored.calculation_id)

    def test_a_head_that_fails_verification_is_evicted_not_kept(self):
        """A failed refresh must not leave the old copy answering."""

        from sto.scheduling.working_schedule import IntegrityError

        workspace, project_id = self._imported()
        self.assertIsNotNone(workspace.load(project_id))
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE schedule_versions
                SET document = jsonb_set(document, '{project,name}', '"tampered"')
                WHERE id = (SELECT version_id FROM schedule_heads
                            WHERE project_id = %s AND kind = 'baseline')
                """,
                (project_id,),
            )
            conn.commit()
        with self.assertRaises(IntegrityError):
            workspace.calculate(project_id)
        # The ordinary load afterwards must not serve the copy from before.
        with self.assertRaises(IntegrityError):
            workspace.load(project_id)
        self.assertIn(project_id, workspace.integrity_failures)

    def test_a_calculation_whose_version_was_repointed_is_refused(self):
        """The fingerprint says nothing about the document it was computed from."""

        from sto.scheduling.working_schedule import IntegrityError

        workspace, project_id = self._imported()
        stored = workspace.calculate(project_id)
        self.assertIsNotNone(workspace.read_calculation(project_id))
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE schedule_versions
                SET document = jsonb_set(document, '{project,name}', '"altered under it"')
                WHERE id = %s
                """,
                (stored.version_id,),
            )
            conn.commit()
        with self.assertRaises(IntegrityError):
            workspace.read_calculation(project_id)

    def test_identical_reimport_cannot_take_an_existing_calculation(self):
        workspace, project_id = self._imported()
        stored = workspace.calculate(project_id)
        workspace.import_file(project_id, filename="again.xml", data=FIXTURE.read_bytes())
        second = workspace.load(project_id, refresh=True)
        self.assertNotEqual(second.version_id, stored.version_id)
        with self.connect() as conn:
            hashes = conn.execute(
                "SELECT canonical_hash FROM schedule_versions WHERE id IN (%s, %s)",
                (stored.version_id, second.version_id),
            ).fetchall()
        self.assertEqual(hashes[0]["canonical_hash"], hashes[1]["canonical_hash"])
        with self.assertRaises(psycopg.errors.CheckViolation):
            with self.connect() as conn:
                conn.execute("UPDATE schedule_calculations SET version_id = %s WHERE id = %s",
                             (second.version_id, stored.calculation_id))
                conn.commit()
        reread = workspace.read_calculation(project_id, calculation_id=stored.calculation_id)
        self.assertEqual(reread.version_id, stored.version_id)

    def test_a_calculation_that_names_the_wrong_hash_is_refused(self):
        from sto.scheduling.working_schedule import IntegrityError

        workspace, project_id = self._imported()
        stored = workspace.calculate(project_id)
        with self.connect() as conn:
            conn.execute(
                "UPDATE schedule_calculations SET canonical_hash = %s WHERE id = %s",
                ("f" * 64, stored.calculation_id),
            )
            conn.commit()
        with self.assertRaises(IntegrityError):
            workspace.read_calculation(project_id)

    def test_the_page_reads_the_calculation_s_own_document(self):
        """Not the project's current head, which can move underneath it.

        A concurrent import is enough: the calculation is verified against
        version B while the names and imported dates come from version A,
        which is a false comparison rather than a stale one.
        """

        workspace, project_id = self._imported()
        stored = workspace.calculate(project_id)
        first_version = stored.version_id

        # A second import moves the head; the calculation still names the first.
        workspace.import_file(
            project_id, filename="again.xml", data=FIXTURE.read_bytes().replace(
                b"<Name>Workspace chain</Name>", b"<Name>Renamed after the run</Name>", 1
            )
        )
        head = workspace.load(project_id, refresh=True)
        self.assertNotEqual(head.version_id, first_version, "the fixture no longer re-imports")

        read = workspace.read_calculation(project_id, calculation_id=stored.calculation_id)
        self.assertEqual(read.version_id, first_version)
        self.assertIsNotNone(read.schedule)
        self.assertEqual(
            canonical_sha256(encode_schedule(read.schedule)),
            read.result.provenance.canonical_hash,
            "the document served with the calculation is the one it names",
        )

    def test_agreement_is_unknown_when_the_file_gave_only_one_date(self):
        workspace, project_id = self._imported()
        workspace.calculate(project_id)
        payload = workspace.latest_calculation(project_id)
        for row in payload["activities"]:
            with self.subTest(str(row["activity_uid"])):
                if row["source_start"] is None or row["source_finish"] is None:
                    self.assertIsNone(
                        row["agrees_with_source"],
                        "a verdict about a value the file never gave",
                    )

if __name__ == "__main__":
    unittest.main()
