"""The validator against the real schedules (slice S6).

``test_validator`` proves the checker catches a corrupted result, and
``ThePassesAgreeAcrossTheCorpusTests`` runs it over the packaged conformance
cases. Neither runs it over a real file, and the acceptance condition for this
slice -- and the claim in its history entry -- are both about the real files.
A claim nothing executes can stay true-looking while it stops being true, so
this executes it.

What it asks is a consistency question, not an oracle one: given the result
these passes produced, do the relations it claims actually hold? A schedule can
be internally perfect and still disagree with Microsoft Project, which is what
the file-oracle comparisons in the other modules are for.

Each file is planned and validated exactly as a caller would: the plan's own
threshold and progress policy, and the horizon the other real-file modules use.

The real schedules live outside the repository; ``STO_REQUIRE_BOILER=1`` turns
their absence into a failure instead of a skip, which is what a gate run sets.
"""

from __future__ import annotations

import os
import unittest
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

from tests.real_fixture_guard import verify_available

from sto.core.engine import (
    backward_pass,
    build_plan,
    float_analysis,
    forward_pass,
)
from sto.core.engine.validate import validate_result
from sto.core.model.migrate.sto_v011 import migrate
from sto.legacy import import_mspdi

FIXTURES = {
    "boiler_before": Path(
        os.environ.get("STO_BOILER_BEFORE", "/home/dez/sto-fixtures/boiler-before-no-progress.xml")
    ),
    "kiln": Path(os.environ.get("STO_KILN", "/home/dez/sto-fixtures/kiln-wg047k-source.xml")),
    "calciner": Path(
        os.environ.get("STO_CALCINER", "/home/dez/sto-fixtures/calciner-wg050-source.xml")
    ),
    "day5": Path(
        os.environ.get(
            "STO_BOILER_DAY5", "/home/dez/sto-fixtures/BOILER-WG110-day5-candidate.mspdi.xml"
        )
    ),
}
#: The files Microsoft Project itself recalculated after progress was entered,
#: the only progress here that Project resolved rather than tooling. They are
#: separately guarded because they are separately obtainable.
NATIVE = {
    "after_native": Path(
        os.environ.get(
            "STO_BOILER_AFTER_NATIVE",
            "/home/dez/sto-fixtures/boiler-after-native-progress.xml",
        )
    ),
    "roundtrip_saved": Path(
        os.environ.get(
            "STO_BOILER_ROUNDTRIP_SAVED",
            "/home/dez/sto-fixtures/boiler-roundtrip-project-saved-task43.xml",
        )
    ),
}
verify_available(FIXTURES)
verify_available(NATIVE)
if os.environ.get("STO_REQUIRE_NATIVE") == "1":
    absent = sorted(name for name, path in NATIVE.items() if not path.is_file())
    if absent:
        raise RuntimeError(
            f"STO_REQUIRE_NATIVE=1 but these native fixtures are not here: {absent}"
        )
if os.environ.get("STO_REQUIRE_DAY5") == "1" and not FIXTURES["day5"].is_file():
    raise RuntimeError(
        "STO_REQUIRE_DAY5=1 but the day-5 fixture is not here: "
        f"{FIXTURES['day5']}"
    )
if os.environ.get("STO_REQUIRE_BOILER") == "1":
    absent = sorted(
        name for name, path in FIXTURES.items()
        if name != "day5" and not path.is_file()
    )
    if absent:
        raise RuntimeError(f"STO_REQUIRE_BOILER=1 but these are not here: {absent}")


def _available(fixtures):
    available = {name: path for name, path in fixtures.items() if path.is_file()}
    if not available:
        raise unittest.SkipTest("no fixture in this evidence cohort is available")
    return available


def _validated(path: Path):
    schedule, _, _ = migrate(import_mspdi(str(path)))
    start = schedule.project.start or datetime(2026, 8, 1)
    plan = build_plan(schedule, (start - timedelta(days=90), start + timedelta(days=365)))
    forward = forward_pass(
        plan.network,
        snap_milestones=plan.snap_milestones,
        progress_policy=plan.progress_policy,
    )
    backward = backward_pass(plan.network, forward, snap_milestones=plan.snap_milestones)
    floats = float_analysis(
        plan.network, forward, backward, threshold=plan.critical_float_threshold
    )
    return validate_result(plan.network, forward, backward, floats)


class TheRealFilesValidateTests(unittest.TestCase):
    def test_every_real_schedule_reports_nothing(self):
        for name, path in _available(FIXTURES).items():
            with self.subTest(name):
                violations = _validated(path)
                self.assertEqual(
                    violations,
                    (),
                    f"{name}: {dict(Counter(row.code for row in violations))}",
                )

    def test_the_natively_recalculated_files_too(self):
        """The files whose progress Project resolved rather than tooling.

        Progress is where a result has the most ways to be internally
        inconsistent -- released edges, a status floor, spans pinned to
        actuals -- so the files carrying real progress are the ones this is
        worth asking of.
        """

        for name, path in _available(NATIVE).items():
            with self.subTest(name):
                violations = _validated(path)
                self.assertEqual(
                    violations,
                    (),
                    f"{name}: {dict(Counter(row.code for row in violations))}",
                )


if __name__ == "__main__":
    unittest.main()
