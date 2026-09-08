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
from datetime import datetime, timedelta
from pathlib import Path

from sto.core.engine import (
    backward_pass,
    build_plan,
    float_analysis,
    forward_pass,
    roll_up,
)
from sto.core.engine.result import EXCLUDED, SCHEDULED, project_result
from sto.core.hashing import canonical_sha256
from sto.core.model.codec import encode_schedule
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

    def test_the_same_calculation_twice_is_refused_rather_than_duplicated(self):
        workspace, project_id = self._imported()
        workspace.calculate(project_id)
        with self.assertRaises(Exception):
            workspace.calculate(project_id)


if __name__ == "__main__":
    unittest.main()
