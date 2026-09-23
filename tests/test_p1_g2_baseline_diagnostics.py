from __future__ import annotations

from collections import Counter
import hashlib
import importlib.util
import json
import marshal
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from uuid import uuid4

from scripts.evidence.p1_g2_baseline_diagnostics import (
    BASELINE_IDENTITY,
    COMPOUND_FLOAT,
    ELAPSED_FLOAT,
    INACTIVE_BOUNDARY,
    MULTI_RESOURCE,
    REPOSITORY_BASE,
    Calculation,
    DiagnosticError,
    _evidence_tool_identity,
    _free_float_candidates,
    _load,
    _movement_finish_limits,
    _read_evidence_tool_identity,
    build_record,
    canonical_json,
    main,
    read_verified_fixture,
    verify_production_basis,
    verify_fixture,
)
from sto.core.calendar.arithmetic import CompiledIntervals
from sto.core.engine import backward_pass, float_analysis, forward_pass
from sto.core.engine.progress import ProgressState
from sto.core.model.enums import ConstraintType, RelationshipType
from tests.test_pass_contract import activity, link, network, uid


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "docs/evidence/p1-g2-baseline-root-causes-2026-09-22.json"
HUMAN_EVIDENCE = ROOT / "docs/evidence/p1-g2-baseline-root-causes-2026-09-22.md"
BASELINE = Path(
    os.environ.get(
        "STO_BOILER_BEFORE",
        "/home/dez/sto-fixtures/boiler-before-no-progress.xml",
    )
)
REPEAT = Path(
    os.environ.get(
        "STO_BOILER_CONTROLLED_NATIVE_REPEAT",
        "/home/dez/sto-fixtures/P1-CONTROLLED-NATIVE-PROGRESS-UID227-RETURNED.xml",
    )
)
PRESENT = BASELINE.is_file() and REPEAT.is_file()

if os.environ.get("STO_REQUIRE_CONTROLLED_NATIVE_REPEAT") == "1" and not PRESENT:
    raise RuntimeError(
        "STO_REQUIRE_CONTROLLED_NATIVE_REPEAT=1 but the exact P1-G2 pair is absent"
    )


class RecordedP1G2BaselineDiagnosticsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.serialized = EVIDENCE.read_text(encoding="utf-8")
        cls.record = json.loads(cls.serialized)

    def test_authoritative_matrix_is_preserved(self) -> None:
        matrix = self.record["baseline_matrix"]
        self.assertEqual(matrix["mismatch_field_slots"], 422)
        self.assertEqual(matrix["affected_leaf_identities"], 105)
        self.assertEqual(
            matrix["by_field"],
            {
                "start": 62,
                "finish": 67,
                "early_start": 62,
                "early_finish": 67,
                "late_start": 42,
                "late_finish": 33,
                "total_float": 71,
                "free_float": 16,
                "critical": 2,
            },
        )
        transition = self.record["controlled_repeat"]
        self.assertEqual(transition["classifications"]["ENGINE_NATIVE_AGREEMENT"], 43)
        self.assertEqual(transition["unexpected_transition_differences"], 0)
        self.assertFalse(transition["p1_g3_affected"])

    def test_every_slot_is_unique_and_root_cause_groups_reconcile(self) -> None:
        slots = self.record["mismatches"]
        identities = {(row["leaf_id"], row["field"]) for row in slots}
        self.assertEqual(len(slots), 422)
        self.assertEqual(len(identities), 422)
        groups = self.record["root_cause_groups"]
        self.assertEqual(sum(row["field_slot_count"] for row in groups), 422)
        for row in groups:
            self.assertEqual(
                sum(row["field_distribution"].values()), row["field_slot_count"]
            )
        self.assertEqual(
            {row["group_id"]: row["field_slot_count"] for row in groups},
            {
                MULTI_RESOURCE: 160,
                INACTIVE_BOUNDARY: 258,
                ELAPSED_FLOAT: 3,
                COMPOUND_FLOAT: 1,
            },
        )
        self.assertEqual(
            self.record["status_totals"],
            {"PROVEN": 3, "STRONG_CANDIDATE": 419, "UNKNOWN": 0},
        )
        confidence = {row["group_id"]: row["status"] for row in groups}
        self.assertEqual(confidence[MULTI_RESOURCE], "STRONG_CANDIDATE")
        self.assertEqual(confidence[INACTIVE_BOUNDARY], "STRONG_CANDIDATE")
        self.assertEqual(confidence[ELAPSED_FLOAT], "PROVEN")
        self.assertEqual(confidence[COMPOUND_FLOAT], "STRONG_CANDIDATE")
        for row in groups:
            self.assertEqual(row["causal_confidence"], row["status"])
            self.assertTrue(row["mechanical_grouping_basis"])
            self.assertEqual(
                row["replacement_semantics_status"], "NOT_ESTABLISHED"
            )
        self.assertEqual(
            dict(Counter(row["causal_confidence"] for row in slots)),
            {"STRONG_CANDIDATE": 419, "PROVEN": 3},
        )
        confidence_rank = {"UNKNOWN": 0, "STRONG_CANDIDATE": 1, "PROVEN": 2}
        self.assertLessEqual(
            confidence_rank[confidence[COMPOUND_FLOAT]],
            min(
                confidence_rank[confidence[MULTI_RESOURCE]],
                confidence_rank[confidence[INACTIVE_BOUNDARY]],
            ),
        )
        components = self.record["baseline_matrix"]["graph_components"]
        self.assertEqual(sum(row["leaf_count"] for row in components), 105)
        self.assertEqual(sum(row["field_slot_count"] for row in components), 422)

    def test_root_and_propagated_leaf_counts_are_explicit(self) -> None:
        groups = {row["group_id"]: row for row in self.record["root_cause_groups"]}
        self.assertEqual(
            (
                groups[MULTI_RESOURCE]["root_leaf_count"],
                groups[MULTI_RESOURCE]["propagated_leaf_count"],
            ),
            (10, 30),
        )
        self.assertEqual(
            (
                groups[INACTIVE_BOUNDARY]["root_leaf_count"],
                groups[INACTIVE_BOUNDARY]["propagated_leaf_count"],
            ),
            (5, 61),
        )
        self.assertEqual(
            (
                groups[ELAPSED_FLOAT]["root_leaf_count"],
                groups[ELAPSED_FLOAT]["propagated_leaf_count"],
            ),
            (2, 0),
        )

    def test_inventory_is_sanitized_and_contains_required_context(self) -> None:
        self.assertNotIn('"task_name"', self.serialized)
        self.assertNotIn('"activity_name"', self.serialized)
        self.assertNotIn('"notes"', self.serialized)
        self.assertNotIn('"source_uid"', self.serialized)
        self.assertNotIn('"source_uids"', self.serialized)
        self.assertNotIn('"source_value"', self.serialized)
        self.assertNotIn('"sto_value"', self.serialized)
        self.assertNotRegex(self.serialized, r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}")
        self.assertEqual(len(self.record["activities"]), 105)
        for leaf_id, activity in self.record["activities"].items():
            self.assertRegex(leaf_id, r"^L\d{4}$")
            self.assertIn("calendar_class", activity)
            self.assertIn("assignment_count", activity)
            self.assertIn("assumption_codes", activity)
            for key in ("planned_duration_class", "remaining_duration_class"):
                self.assertRegex(
                    activity[key],
                    r"^(?:absent|(?:negative|zero|positive)_(?:working|elapsed))$",
                )
            self.assertIn("incoming_lag_classes", activity)
            self.assertNotIn("planned_duration_seconds", activity)
            self.assertNotIn("incoming_lag_seconds", activity)
        for row in self.record["mismatches"]:
            self.assertRegex(row["leaf_id"], r"^L\d{4}$")
            self.assertIn(row["field"], self.record["baseline_matrix"]["by_field"])
            self.assertTrue(row["dependency_paths"])
            self.assertTrue(
                all(
                    leaf_id.startswith("L")
                    for path in row["dependency_paths"]
                    for leaf_id in path
                )
            )
            self.assertRegex(row["component_id"], r"^G2-C\d{2}$")
        for component in self.record["baseline_matrix"]["graph_components"]:
            self.assertTrue(
                all(leaf_id.startswith("L") for leaf_id in component["leaf_ids"])
            )
        for group in self.record["root_cause_groups"]:
            self.assertTrue(
                all(leaf_id.startswith("L") for leaf_id in group["root_leaf_ids"])
            )

    def test_no_production_fix_is_claimed_without_the_missing_oracle(self) -> None:
        next_action = self.record["next_action"]
        self.assertEqual(next_action["decision"], "NO_PRODUCTION_FIX_JUSTIFIED_YET")
        self.assertEqual(next_action["diagnostic_group"], INACTIVE_BOUNDARY)
        self.assertEqual(next_action["causal_confidence"], "STRONG_CANDIDATE")
        self.assertIsNone(next_action["expected_net_mismatch_reduction"])
        self.assertTrue(
            all(
                not row["production_correction_justified"]
                for row in self.record["root_cause_groups"]
            )
        )

    def test_gate_state_does_not_change(self) -> None:
        self.assertEqual(
            self.record["gate"],
            {
                "P1-G1": "PASS",
                "P1-G2": "OPEN",
                "P1-G3": "PASS",
                "P1-G4": "PASS",
                "P1-G5": "PASS",
                "P1": "4/5 IN PROGRESS",
                "P2": "NOT STARTED",
            },
        )

    def test_historical_record_and_its_original_lineage_remain_immutable(self) -> None:
        self.assertEqual(self.record["schema"], "sto-p1-g2-baseline-root-causes-v3")
        lineage = self.record["lineage"]
        production = lineage["production_basis"]
        self.assertEqual(production["declared_commit"], REPOSITORY_BASE)
        self.assertTrue(production["verified_against_worktree"])
        self.assertRegex(production["path_tree_sha256"], r"^[0-9a-f]{64}$")
        self.assertIn("src/sto/core", production["paths"])
        self.assertIn("src/sto/legacy", production["paths"])
        tool = lineage["evidence_tool"]
        self.assertRegex(tool["sha256"], r"^[0-9a-f]{64}$")
        self.assertEqual(tool["path"], "scripts/evidence/p1_g2_baseline_diagnostics.py")
        # This is the immutable pre-correction record, not a claim that the
        # current producer has already rerun the unavailable native pair.
        self.assertEqual(
            hashlib.sha256(EVIDENCE.read_bytes()).hexdigest(),
            "2408fc99f282e9c600d3821b3c926f7deafa8c05044c7fec9a5f08b2b656bf63",
        )
        contract = self.record["classification_contract"]
        self.assertIn("mechanical", contract["diagnostic_group"])
        self.assertIn("STRONG_CANDIDATE", contract["causal_confidence"])
        self.assertIn("pseudonyms", contract["sanitization"])

    def test_human_register_matches_corrected_confidence_totals(self) -> None:
        documented = HUMAN_EVIDENCE.read_text(encoding="utf-8")
        for group_id, status, slots in (
            (MULTI_RESOURCE, "STRONG_CANDIDATE", 160),
            (INACTIVE_BOUNDARY, "STRONG_CANDIDATE", 258),
            (ELAPSED_FLOAT, "PROVEN", 3),
            (COMPOUND_FLOAT, "STRONG_CANDIDATE", 1),
        ):
            self.assertRegex(
                documented,
                rf"\| `{group_id}` \| {status} \|[^\n]+\| {slots} \|",
            )
        self.assertIn("3 `PROVEN` slots, 419", documented)
        self.assertIn("zero `UNKNOWN` slots", documented)
        self.assertNotIn("422 PROVEN-origin slots", documented)


class P1G2DiagnosticToolTests(unittest.TestCase):
    def test_fixture_guard_rejects_a_lookalike(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "not-the-baseline.xml"
            path.write_bytes(b"<Project />")
            with self.assertRaises(DiagnosticError):
                verify_fixture(path, BASELINE_IDENTITY, "BOILER baseline")

    def test_parser_consumes_the_bytes_that_passed_fixture_verification(self) -> None:
        original = (ROOT / "tests/fixtures/synthetic-basic.mspdi.xml").read_bytes()
        expected = (len(original), hashlib.sha256(original).hexdigest())
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fixture.xml"
            path.write_bytes(original)
            verified = read_verified_fixture(path, expected, "synthetic")
            path.write_bytes(b"<not-the-verified-project />")

            schedule = _load(verified.payload)

        self.assertTrue(schedule.activities)
        self.assertEqual(verified.identity["sha256"], expected[1])

    def test_tool_lineage_refuses_a_change_after_startup(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "diagnostic.py"
            path.write_bytes(b"print('startup')\n")
            startup_identity = _read_evidence_tool_identity(path)

            self.assertEqual(
                _evidence_tool_identity(
                    startup_identity=startup_identity,
                    path=path,
                ),
                startup_identity,
            )

            path.write_bytes(b"print('replacement')\n")
            with self.assertRaisesRegex(DiagnosticError, "changed after process startup"):
                _evidence_tool_identity(
                    startup_identity=startup_identity,
                    path=path,
                )

    def _assert_output_alias_is_refused(self, alias: str) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            baseline = root / "baseline.xml"
            repeat = root / "repeat.xml"
            baseline.write_bytes(b"baseline source")
            repeat.write_bytes(b"repeat source")
            if alias == "baseline":
                output = baseline
            elif alias == "repeat":
                output = repeat
            elif alias == "baseline-symlink":
                output = root / "baseline-link.xml"
                output.symlink_to(baseline)
            elif alias == "repeat-hardlink":
                output = root / "repeat-hardlink.xml"
                try:
                    os.link(repeat, output)
                except OSError as error:  # pragma: no cover - platform dependent
                    self.skipTest(f"hard links unavailable: {error}")
            else:  # pragma: no cover - test helper contract
                raise AssertionError(alias)
            baseline_before = baseline.read_bytes()
            repeat_before = repeat.read_bytes()
            with patch(
                "scripts.evidence.p1_g2_baseline_diagnostics.build_record"
            ) as mocked_build:
                with self.assertRaisesRegex(DiagnosticError, "aliases.*fixture"):
                    main([str(baseline), str(repeat), "--output", str(output)])
            mocked_build.assert_not_called()
            self.assertEqual(baseline.read_bytes(), baseline_before)
            self.assertEqual(repeat.read_bytes(), repeat_before)

    def test_output_cannot_replace_the_baseline(self) -> None:
        self._assert_output_alias_is_refused("baseline")

    def test_output_cannot_replace_the_repeat(self) -> None:
        self._assert_output_alias_is_refused("repeat")

    def test_output_cannot_follow_a_symlink_to_the_baseline(self) -> None:
        self._assert_output_alias_is_refused("baseline-symlink")

    def test_output_cannot_use_a_hard_link_to_the_repeat(self) -> None:
        self._assert_output_alias_is_refused("repeat-hardlink")

    def test_distinct_output_is_written(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            baseline = root / "baseline.xml"
            repeat = root / "repeat.xml"
            output = root / "record.json"
            baseline.write_bytes(b"baseline source")
            repeat.write_bytes(b"repeat source")
            with patch(
                "scripts.evidence.p1_g2_baseline_diagnostics.build_record",
                return_value={"safe": True},
            ):
                self.assertEqual(
                    main([str(baseline), str(repeat), "--output", str(output)]), 0
                )
            self.assertEqual(
                json.loads(output.read_text(encoding="utf-8")), {"safe": True}
            )
            self.assertEqual(baseline.read_bytes(), b"baseline source")
            self.assertEqual(repeat.read_bytes(), b"repeat source")

    def test_output_alias_swap_during_calculation_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            baseline = root / "baseline.xml"
            repeat = root / "repeat.xml"
            output = root / "record.json"
            baseline.write_bytes(b"baseline source")
            repeat.write_bytes(b"repeat source")

            def swap_output_to_baseline(*_args: object) -> dict[str, bool]:
                output.symlink_to(baseline)
                return {"safe": True}

            with patch(
                "scripts.evidence.p1_g2_baseline_diagnostics.build_record",
                side_effect=swap_output_to_baseline,
            ):
                with self.assertRaisesRegex(DiagnosticError, "aliases.*fixture"):
                    main([str(baseline), str(repeat), "--output", str(output)])

            self.assertEqual(baseline.read_bytes(), b"baseline source")
            self.assertEqual(repeat.read_bytes(), b"repeat source")

    def test_atomic_publication_does_not_follow_a_postcheck_symlink_swap(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            baseline = root / "baseline.xml"
            repeat = root / "repeat.xml"
            output = root / "record.json"
            baseline.write_bytes(b"baseline source")
            repeat.write_bytes(b"repeat source")

            from scripts.evidence import p1_g2_baseline_diagnostics as diagnostic

            real_refusal = diagnostic.refuse_output_alias
            checks = 0

            def swap_after_final_check(
                checked_output: Path,
                fixtures: dict[str, Path],
            ) -> None:
                nonlocal checks
                real_refusal(checked_output, fixtures)
                checks += 1
                if checks == 2:
                    checked_output.symlink_to(baseline)

            with patch.object(
                diagnostic,
                "build_record",
                return_value={"safe": True},
            ), patch.object(
                diagnostic,
                "refuse_output_alias",
                side_effect=swap_after_final_check,
            ):
                self.assertEqual(
                    diagnostic.main(
                        [str(baseline), str(repeat), "--output", str(output)]
                    ),
                    0,
                )

            self.assertFalse(output.is_symlink())
            self.assertEqual(
                json.loads(output.read_text(encoding="utf-8")), {"safe": True}
            )
            self.assertEqual(baseline.read_bytes(), b"baseline source")
            self.assertEqual(repeat.read_bytes(), b"repeat source")

    def test_checkout_source_precedes_a_shadowed_pythonpath(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            shadow = Path(directory)
            package = shadow / "sto"
            package.mkdir()
            (package / "__init__.py").write_text(
                "raise RuntimeError('shadow sto imported')\n",
                encoding="utf-8",
            )
            environment = os.environ.copy()
            environment["PYTHONPATH"] = os.pathsep.join(
                (str(shadow), str(ROOT / "src"))
            )
            completed = subprocess.run(
                (
                    sys.executable,
                    "-c",
                    "import scripts.evidence.p1_g2_baseline_diagnostics; "
                    "import sto; print(sto.__file__)",
                ),
                cwd=ROOT,
                env=environment,
                check=False,
                capture_output=True,
                text=True,
            )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(
            Path(completed.stdout.strip()).resolve(),
            (ROOT / "src/sto/__init__.py").resolve(),
        )

    def _assert_poisoned_bytecode_is_ignored(self, *, external_prefix: bool) -> None:
        source = ROOT / "tests/controlled_native_progress_evidence.py"
        source_text = source.read_text(encoding="utf-8")
        future = "from __future__ import annotations\n"
        self.assertIn(future, source_text)
        poisoned_source = source_text.replace(
            future,
            future
            + "import os\n"
            + "os.environ['STO_P1_G2_PYCACHE_POISON'] = 'executed'\n",
            1,
        )

        with tempfile.TemporaryDirectory() as directory:
            environment = os.environ.copy()
            if external_prefix:
                environment["PYTHONPYCACHEPREFIX"] = str(Path(directory) / "external-cache")
            else:
                environment.pop("PYTHONPYCACHEPREFIX", None)
            cache_probe = subprocess.run(
                (
                    sys.executable,
                    "-c",
                    "import importlib.util, sys; "
                    "print(importlib.util.cache_from_source(sys.argv[1]))",
                    str(source),
                ),
                cwd=ROOT,
                env=environment,
                check=True,
                capture_output=True,
                text=True,
            )
            cache_path = Path(cache_probe.stdout.strip())
            previous = cache_path.read_bytes() if cache_path.exists() else None
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            metadata = source.stat()
            header = (
                importlib.util.MAGIC_NUMBER
                + struct.pack(
                    "<III",
                    0,
                    int(metadata.st_mtime) & 0xFFFFFFFF,
                    metadata.st_size & 0xFFFFFFFF,
                )
            )
            code = compile(poisoned_source, str(source), "exec")
            cache_path.write_bytes(header + marshal.dumps(code))

            child_environment = environment.copy()
            child_environment.pop("STO_P1_G2_PYCACHE_POISON", None)
            try:
                completed = subprocess.run(
                    (
                        sys.executable,
                        "-c",
                        "import os; "
                        "import scripts.evidence.p1_g2_baseline_diagnostics; "
                        "print(os.environ.get('STO_P1_G2_PYCACHE_POISON', 'clean'))",
                    ),
                    cwd=ROOT,
                    env=child_environment,
                    check=False,
                    capture_output=True,
                    text=True,
                )
            finally:
                if previous is None:
                    cache_path.unlink(missing_ok=True)
                else:
                    cache_path.write_bytes(previous)

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stdout.strip(), "clean")

    def test_ignored_checkout_pycache_cannot_supply_evidence_code(self) -> None:
        self._assert_poisoned_bytecode_is_ignored(external_prefix=False)

    def test_external_pythonpycacheprefix_cannot_supply_evidence_code(self) -> None:
        self._assert_poisoned_bytecode_is_ignored(external_prefix=True)

    def test_declared_production_basis_matches_this_worktree(self) -> None:
        lineage = verify_production_basis()
        self.assertEqual(lineage["declared_commit"], REPOSITORY_BASE)
        self.assertTrue(lineage["verified_against_worktree"])

    def test_lineage_rejects_a_relevant_change_but_not_evidence_edits(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            production = root / "src/sto/core/example.py"
            evidence = root / "docs/evidence/note.md"
            production.parent.mkdir(parents=True)
            evidence.parent.mkdir(parents=True)
            production.write_text("VALUE = 1\n", encoding="utf-8")
            evidence.write_text("initial\n", encoding="utf-8")

            def git(*arguments: str) -> str:
                completed = subprocess.run(
                    ("git", *arguments),
                    cwd=root,
                    check=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
                return completed.stdout.strip()

            git("init", "-q")
            git("config", "user.name", "STO evidence test")
            git("config", "user.email", "sto-evidence@example.invalid")
            git("add", ".")
            git("commit", "-qm", "basis")
            basis = git("rev-parse", "HEAD")
            paths = ("src/sto/core",)
            expected = verify_production_basis(
                repository_root=root,
                declared_commit=basis,
                production_paths=paths,
                expected_path_tree_sha256=None,
            )["path_tree_sha256"]

            shallow_lineage = verify_production_basis(
                repository_root=root,
                declared_commit="0" * 40,
                production_paths=paths,
                expected_path_tree_sha256=expected,
            )
            self.assertEqual(shallow_lineage["path_tree_sha256"], expected)

            production_path = str(production.relative_to(root))
            git("update-index", "--assume-unchanged", production_path)
            production.write_text("VALUE = 2\n", encoding="utf-8")
            with self.assertRaisesRegex(DiagnosticError, "worktree bytes"):
                verify_production_basis(
                    repository_root=root,
                    declared_commit=basis,
                    production_paths=paths,
                    expected_path_tree_sha256=expected,
                )
            git("update-index", "--no-assume-unchanged", production_path)
            production.write_text("VALUE = 1\n", encoding="utf-8")

            evidence.write_text("unrelated evidence edit\n", encoding="utf-8")
            self.assertTrue(
                verify_production_basis(
                    repository_root=root,
                    declared_commit=basis,
                    production_paths=paths,
                    expected_path_tree_sha256=expected,
                )["verified_against_worktree"]
            )
            production.write_text("VALUE = 2\n", encoding="utf-8")
            with self.assertRaisesRegex(DiagnosticError, "production basis"):
                verify_production_basis(
                    repository_root=root,
                    declared_commit=basis,
                    production_paths=paths,
                    expected_path_tree_sha256=expected,
                )

            git("add", production_path)
            git("commit", "-qm", "change production")
            with self.assertRaisesRegex(DiagnosticError, "production basis"):
                verify_production_basis(
                    repository_root=root,
                    declared_commit=basis,
                    production_paths=paths,
                    expected_path_tree_sha256=expected,
                )

    def _zero_span_limit(
        self,
        *,
        state: ProgressState,
        snap_milestones: bool,
        constraint_type: ConstraintType = ConstraintType.ASAP,
    ) -> int:
        activity_uid = uuid4()
        calendar = CompiledIntervals.of(((0, 5), (10, 15)))
        planned = SimpleNamespace(
            uid=activity_uid,
            remaining=0,
            calendar=calendar,
            constraint_type=constraint_type,
        )
        network = SimpleNamespace(
            horizon=20,
            activity_by_uid=lambda: {activity_uid: planned},
        )
        forward = SimpleNamespace(
            by_uid=lambda: {activity_uid: SimpleNamespace(state=state)}
        )
        calculation = Calculation(
            plan=SimpleNamespace(
                network=network,
                snap_milestones=snap_milestones,
            ),
            forward=forward,
            backward=None,
            floats=None,
            result={},
        )
        return _movement_finish_limits(calculation)[activity_uid]

    def test_snapped_zero_span_uses_the_latest_working_start(self) -> None:
        self.assertEqual(
            self._zero_span_limit(
                state=ProgressState.NOT_STARTED,
                snap_milestones=True,
            ),
            14,
        )

    def test_unsnapped_zero_span_keeps_the_horizon(self) -> None:
        self.assertEqual(
            self._zero_span_limit(
                state=ProgressState.NOT_STARTED,
                snap_milestones=False,
            ),
            20,
        )

    def test_complete_zero_span_keeps_the_horizon(self) -> None:
        self.assertEqual(
            self._zero_span_limit(
                state=ProgressState.COMPLETE,
                snap_milestones=True,
            ),
            20,
        )

    def test_exactly_pinned_zero_span_keeps_the_horizon(self) -> None:
        for constraint_type in (ConstraintType.MSO, ConstraintType.MFO):
            with self.subTest(constraint_type=constraint_type):
                self.assertEqual(
                    self._zero_span_limit(
                        state=ProgressState.NOT_STARTED,
                        snap_milestones=True,
                        constraint_type=constraint_type,
                    ),
                    20,
                )

    def test_snapped_zero_replay_matches_production_free_float(self) -> None:
        scheduling = CompiledIntervals.of(((0, 5), (10, 15)))
        lag_calendar = CompiledIntervals.of(((0, 5),))
        successor_calendar = CompiledIntervals.of(((0, 20),))
        schedule = network(
            activity("P", 0, scheduling),
            activity("S", 0, successor_calendar),
            relationships=(
                link("R1", "P", "S", RelationshipType.SS, -5, lag_calendar),
            ),
            project_start=5,
            horizon=20,
        )
        forward = forward_pass(schedule, snap_milestones=True)
        backward = backward_pass(schedule, forward, snap_milestones=True)
        floats = float_analysis(schedule, forward, backward)
        calculation = Calculation(
            plan=SimpleNamespace(network=schedule, snap_milestones=True),
            forward=forward,
            backward=backward,
            floats=floats,
            result={},
        )
        candidates = _free_float_candidates(
            uid("P"),
            forward.by_uid(),
            calculation,
            _movement_finish_limits(calculation),
        )
        self.assertEqual(
            min(value for _, value in candidates),
            floats.by_uid()[uid("P")].free_float,
        )

    @unittest.skipUnless(PRESENT, "exact BOILER baseline/UID 227 pair unavailable")
    def test_exact_pair_reproduces_diagnosis_with_current_execution_lineage(self) -> None:
        regenerated = build_record(BASELINE, REPEAT)
        recorded = json.loads(EVIDENCE.read_text(encoding="utf-8"))
        current_lineage = regenerated.pop("lineage")
        recorded_lineage = recorded.pop("lineage")
        # Only producer identity changes. Every field slot, causal confidence,
        # dependency path, input identity and gate remains an exact comparison.
        self.assertEqual(regenerated, recorded)
        self.assertEqual(current_lineage["production_basis"],
                         recorded_lineage["production_basis"])
        for key in ("evidence_tool", "execution"):
            identity = current_lineage[key]
            payload = (ROOT / identity["path"]).read_bytes()
            self.assertEqual(identity["bytes"], len(payload))
            self.assertEqual(identity["sha256"], hashlib.sha256(payload).hexdigest())
        self.assertEqual(current_lineage["execution"]["profile"],
                         "sto-p1-g2-verified-source-v1")


if __name__ == "__main__":
    unittest.main()
