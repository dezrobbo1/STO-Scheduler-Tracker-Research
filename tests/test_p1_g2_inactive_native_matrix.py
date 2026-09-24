"""Tests for the bounded P1-G2 RC02 inactive native matrix tooling."""
from __future__ import annotations

from datetime import datetime, timedelta
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
import unittest
from copy import deepcopy
import xml.etree.ElementTree as ET

from scripts.evidence import p1_g2_inactive_native_matrix as matrix
from scripts.evidence import p1_g2_inactive_native_matrix_generate as generate

NS = {"p": "http://schemas.microsoft.com/project"}


def _write_fixture(path: Path) -> Path:
    path.write_bytes(generate.build_fixture())
    return path


def _mutated_fixture(verdict: str, target: Path) -> Path:
    """Calculated synthetic test data; never presented as a native return."""
    _write_fixture(target)
    tree = ET.parse(target)
    root = tree.getroot()
    tasks = {
        task.findtext("p:Name", namespaces=NS): task
        for task in root.findall("p:Tasks/p:Task", NS)
    }
    start = datetime(2026, 10, 5, 8)

    def set_value(name: str, field: str, value: object) -> None:
        node = tasks[name].find(f"p:{field}", NS)
        assert node is not None
        node.text = str(value)

    def span(name: str, early: int, late: int, hours: int, free: int) -> None:
        for field, offset in (
            ("Start", early), ("EarlyStart", early),
            ("Finish", early + hours), ("EarlyFinish", early + hours),
            ("LateStart", late), ("LateFinish", late + hours),
        ):
            set_value(name, field, (start + timedelta(hours=offset)).isoformat())
        set_value(name, "TotalSlack", (late - early) * 600)
        set_value(name, "FreeSlack", free * 600)

    if verdict not in {"mixed", "splice", "drop"}:
        raise AssertionError(verdict)
    span("RC02-FINISH-DRIVER", 0, 0, 240, 0)
    for pair, roles in matrix.PAIR_HOURS.items():
        pred, mid, succ = roles["PRED"], roles["MID"], roles["SUCC"]
        other = roles.get("OTHER", 0)
        control_succ = max(pred + mid, other)
        for twin in ("A", "I"):
            prefix = f"RC02-{pair}-{twin}-"
            if twin == "A":
                succ_start, pred_late_finish = control_succ, 240 - succ - mid
                pred_free = 0
            elif verdict == "drop":
                succ_start, pred_late_finish = other, 240
                pred_free = 240 - pred
            else:
                succ_start, pred_late_finish = max(pred, other), 240 - succ
                pred_free = succ_start - pred if verdict == "splice" else 0
            span(prefix + "PRED", 0, pred_late_finish - pred, pred, pred_free)
            span(prefix + "MID", pred, 240 - succ - mid, mid, max(control_succ - pred - mid, 0))
            span(prefix + "SUCC", succ_start, 240 - succ, succ, 240 - succ_start - succ)
            if "OTHER" in roles:
                span(prefix + "OTHER", 0, 240 - succ - other, other, succ_start - other)
    tree.write(target, encoding="utf-8", xml_declaration=True)
    return target


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/evidence/p1_g2_inactive_native_matrix.py"
EVIDENCE = ROOT / "docs/evidence/p1-g2-rc02-inactive-native-result-2026-09-24.json"


def _cli(source: Path, *args: object) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), str(source), *(str(arg) for arg in args)],
        capture_output=True, check=False,
    )


class Rc02NativeMatrixTests(unittest.TestCase):
    def test_generator_is_deterministic_and_matrix_is_paired(self):
        first = generate.build_fixture()
        self.assertEqual(first, generate.build_fixture())
        self.assertEqual(len(first), 48322)
        self.assertEqual(hashlib.sha256(first).hexdigest(),
                         "ca4cbe0495180a232c4498998a4de94ab0d2863f4bd2f01cecd08cdf68b38024")
        with tempfile.TemporaryDirectory() as directory:
            fixture = _write_fixture(Path(directory) / "matrix.xml")
            project, rows = matrix.read(fixture)
        self.assertEqual(project["name"], "P1-G2-RC02-Inactive-Native-Matrix.xml")
        self.assertEqual(set(rows), matrix.REQUIRED)
        self.assertEqual(
            {name for name, row in rows.items() if row["Active"] == "0"},
            matrix.INACTIVE,
        )
        self.assertEqual(rows["RC02-A-I-MID"]["predecessor_uids"], ["5"])
        self.assertEqual(rows["RC02-B-I-SUCC"]["predecessor_uids"], ["13", "14"])
        self.assertEqual(rows["RC02-C-I-SUCC"]["predecessor_uids"], ["21", "22"])
        self.assertEqual(
            rows["RC02-C-I-SUCC"]["predecessor_links"],
            [
                {"predecessor_uid": "21", "type": "1", "link_lag": "0"},
                {"predecessor_uid": "22", "type": "1", "link_lag": "0"},
            ],
        )

    def test_reader_rejects_changed_task_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            path = _write_fixture(Path(directory) / "identity.xml")
            tree = ET.parse(path)
            root = tree.getroot()
            task = next(
                row for row in root.findall("p:Tasks/p:Task", NS)
                if row.findtext("p:Name", namespaces=NS) == "RC02-A-I-MID"
            )
            uid = task.find("p:UID", NS)
            assert uid is not None
            uid.text = "600"
            tree.write(path, encoding="utf-8", xml_declaration=True)
            with self.assertRaisesRegex(SystemExit, "task identity"):
                matrix.read(path)

    def test_reader_rejects_changed_zero_lag_fs_topology(self):
        for mutation in ("predecessor", "type", "lag", "removed"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as directory:
                path = _write_fixture(Path(directory) / f"{mutation}.xml")
                tree = ET.parse(path)
                root = tree.getroot()
                task = next(
                    row for row in root.findall("p:Tasks/p:Task", NS)
                    if row.findtext("p:Name", namespaces=NS) == "RC02-B-I-SUCC"
                )
                links = task.findall("p:PredecessorLink", NS)
                assert links
                if mutation == "removed":
                    task.remove(links[0])
                else:
                    field = {
                        "predecessor": "PredecessorUID",
                        "type": "Type",
                        "lag": "LinkLag",
                    }[mutation]
                    node = links[0].find(f"p:{field}", NS)
                    assert node is not None
                    node.text = {"predecessor": "999", "type": "2", "lag": "10"}[mutation]
                tree.write(path, encoding="utf-8", xml_declaration=True)
                with self.assertRaisesRegex(SystemExit, "zero-lag FS matrix relationships"):
                    matrix.read(path)

    def test_classifier_distinguishes_three_supported_shapes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for fixture_verdict, expected in (
                ("splice", "ZERO_DURATION_DATE_PASSTHROUGH_WITH_FREE_SLACK_MATCHING_ACTIVE_SUCCESSOR_GAP"),
                ("mixed", "ZERO_DURATION_DATE_PASSTHROUGH_WITH_FREE_SLACK_MATCHING_INACTIVE_EDGE_GAP"),
                ("drop", "DROP_BOTH_ENDPOINT_EDGES_SUPPORTED"),
            ):
                with self.subTest(fixture_verdict=fixture_verdict):
                    path = _mutated_fixture(fixture_verdict, root / f"{fixture_verdict}.xml")
                    _, rows = matrix.read(path)
                    self.assertEqual(matrix.classify(rows)["verdict"], expected)

    def test_mixed_native_shape_separates_dates_from_free_slack(self):
        with tempfile.TemporaryDirectory() as directory:
            path = _mutated_fixture("mixed", Path(directory) / "mixed.xml")
            _, rows = matrix.read(path)
            result = matrix.classify(rows)
        self.assertEqual(
            result["components"],
            {
                "date_semantic": "ZERO_DURATION_FS_PASSTHROUGH_SUPPORTED",
                "free_slack_observation": "MATCHES_INACTIVE_EDGE_GAP",
            },
        )
        self.assertEqual(
            result["pair_c_slack_units"],
            {
                "observed_free_slack": 0,
                "total_slack": 115200,
                "direct_active_successor_gap": 43200,
                "original_inactive_edge_gap": 0,
            },
        )
        self.assertEqual(
            result["validated_topology"]["RC02-C-I-SUCC"],
            {
                "uid": "23",
                "predecessor_links": [
                    {"predecessor_uid": "21", "type": "1", "link_lag": "0"},
                    {"predecessor_uid": "22", "type": "1", "link_lag": "0"},
                ],
            },
        )

    def test_inconsistent_observations_do_not_establish_a_rule(self):
        with tempfile.TemporaryDirectory() as directory:
            path = _mutated_fixture("splice", Path(directory) / "inconsistent.xml")
            tree = ET.parse(path)
            root = tree.getroot()
            tasks = {
                task.findtext("p:Name", namespaces=NS): task
                for task in root.findall("p:Tasks/p:Task", NS)
            }
            other_finish = tasks["RC02-B-I-OTHER"].findtext("p:Finish", namespaces=NS)
            node = tasks["RC02-B-I-SUCC"].find("p:Start", NS)
            assert node is not None and other_finish is not None
            node.text = other_finish
            early = tasks["RC02-B-I-SUCC"].find("p:EarlyStart", NS)
            assert early is not None
            early.text = other_finish
            tree.write(path, encoding="utf-8", xml_declaration=True)
            _, rows = matrix.read(path)
            self.assertEqual(
                matrix.classify(rows)["verdict"],
                "NO_SINGLE_TESTED_RULE_ESTABLISHED",
            )

    def test_all_active_controls_and_paired_effects_are_retained(self):
        with tempfile.TemporaryDirectory() as directory:
            path = _mutated_fixture("mixed", Path(directory) / "mixed.xml")
            _, rows = matrix.read(path)
            result = matrix.classify(rows)
        self.assertTrue(result["controls"]["valid"])
        self.assertTrue(all(result["paired_effects"].values()))
        self.assertEqual(set(result["observations"]), matrix.REQUIRED)
        # Every active twin must be capable of falsifying the conclusion.
        for pair in "ABC":
            mutated = deepcopy(rows)
            name = f"RC02-{pair}-A-PRED"
            mutated[name]["LateFinish"] = mutated[f"RC02-{pair}-A-SUCC"]["LateStart"]
            result = matrix.classify(mutated)
            self.assertFalse(result["controls"]["valid"])
            self.assertEqual(result["verdict"], "NO_SINGLE_TESTED_RULE_ESTABLISHED")
            self.assertEqual(set(result["components"].values()), {"NOT_ESTABLISHED"})

    def test_controls_that_also_bypass_middle_duration_cannot_prove_inactivity(self):
        with tempfile.TemporaryDirectory() as directory:
            path = _mutated_fixture("mixed", Path(directory) / "mixed.xml")
            _, rows = matrix.read(path)
        # Preserve durations, identity and topology but make the active twins
        # have the same calculated coordinates as their inactive counterparts.
        for pair, roles in matrix.PAIR_HOURS.items():
            for role in roles:
                for field in matrix.DATE_FIELDS:
                    rows[f"RC02-{pair}-A-{role}"][field] = rows[f"RC02-{pair}-I-{role}"][field]
        self.assertEqual(matrix.classify(rows)["verdict"], "NO_SINGLE_TESTED_RULE_ESTABLISHED")

    def test_absent_empty_malformed_and_timezone_dates_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = _mutated_fixture("mixed", Path(directory) / "mixed.xml")
            _, rows = matrix.read(path)
            for name in sorted(matrix.REQUIRED):
                for field in matrix.DATE_FIELDS:
                    for invalid in (None, "", "not-a-date", "2026-10-05", "2026-10-05T08:00:00+08:00"):
                        with self.subTest(name=name, field=field, invalid=invalid):
                            mutated = deepcopy(rows)
                            mutated[name][field] = invalid
                            with self.assertRaisesRegex(SystemExit, "missing or invalid date"):
                                matrix.classify(mutated)
            # Exercise the actual reader/CLI, not just the in-memory helper.
            tree = ET.parse(path)
            for task in tree.getroot().findall("p:Tasks/p:Task", NS):
                name = task.findtext("p:Name", namespaces=NS)
                if name and "-A-" in name:
                    for field in matrix.DATE_FIELDS:
                        task.remove(task.find(f"p:{field}", NS))
            tree.write(path, encoding="utf-8", xml_declaration=True)
            before = path.read_bytes()
            output = Path(directory) / "must-not-exist.json"
            run = _cli(path, "--output", output)
            self.assertNotEqual(run.returncode, 0)
            self.assertIn(b"missing or invalid date", run.stderr)
            self.assertFalse(output.exists())
            self.assertEqual(path.read_bytes(), before)

    def test_unrecalculated_generated_input_does_not_establish_a_rule(self):
        result = matrix.analyze(generate.build_fixture())["classification"]
        self.assertFalse(result["controls"]["valid"])
        self.assertEqual(result["verdict"], "NO_SINGLE_TESTED_RULE_ESTABLISHED")

    def test_nulls_never_compare_equal(self):
        rows = {"left": {"Start": None}, "right": {"Start": None}}
        self.assertFalse(matrix.eq(rows, ("left", "Start"), ("right", "Start")))

    def test_missing_slack_and_changed_pair_inputs_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = _mutated_fixture("mixed", Path(directory) / "mixed.xml")
            _, rows = matrix.read(path)
        for field, value in (("FreeSlack", None), ("TotalSlack", "bad"), ("Active", None),
                             ("Duration", "PT0H0M0S"), ("Manual", "1"), ("ConstraintType", "2")):
            with self.subTest(field=field):
                mutated = deepcopy(rows)
                mutated["RC02-C-A-MID"][field] = value
                with self.assertRaises(SystemExit):
                    matrix.classify(mutated)

    def test_drop_requires_all_backward_endpoints_at_project_finish(self):
        with tempfile.TemporaryDirectory() as directory:
            path = _mutated_fixture("drop", Path(directory) / "drop.xml")
            _, rows = matrix.read(path)
        self.assertEqual(matrix.classify(rows)["verdict"], "DROP_BOTH_ENDPOINT_EDGES_SUPPORTED")
        # Both a wholly retained backward boundary and any mixed boundary fail.
        for retained_pairs in (("A", "B", "C"), ("A",), ("B",), ("C",)):
            with self.subTest(retained=retained_pairs):
                mutated = deepcopy(rows)
                for pair in retained_pairs:
                    pred = mutated[f"RC02-{pair}-I-PRED"]
                    finish = datetime.fromisoformat(mutated[f"RC02-{pair}-I-SUCC"]["LateStart"])
                    pred["LateFinish"] = finish.isoformat()
                    pred["LateStart"] = (finish - timedelta(hours=matrix.PAIR_HOURS[pair]["PRED"])).isoformat()
                result = matrix.classify(mutated)
                self.assertTrue(result["controls"]["valid"])
                self.assertFalse(result["predicates"]["all_pairs_late_drop_to_project_finish"])
                self.assertEqual(result["verdict"], "NO_SINGLE_TESTED_RULE_ESTABLISHED")

    def test_cli_refuses_input_output_aliases_without_changing_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = _mutated_fixture("mixed", root / "source.xml")
            before = hashlib.sha256(source.read_bytes()).hexdigest()
            symlink = root / "symbolic.xml"
            symlink.symlink_to(source)
            hardlink = root / "hard.xml"
            os.link(source, hardlink)
            (root / "nested").mkdir()
            for output in (source, root / "nested" / ".." / "source.xml", symlink, hardlink):
                with self.subTest(output=str(output)):
                    result = _cli(source, "--output", output)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn(b"output must be separate", result.stderr)
                    self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), before)
            self.assertEqual(sorted(p.name for p in root.iterdir()),
                             ["hard.xml", "nested", "source.xml", "symbolic.xml"])

    def test_cli_emits_deterministic_exact_record_and_checks_without_writing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = _mutated_fixture("mixed", root / "source.xml")
            before = source.read_bytes()
            output = root / "result.json"
            expected = matrix.serialize(matrix.analyze(before)).encode("utf-8")
            stdout = _cli(source)
            self.assertEqual(stdout.returncode, 0, stdout.stderr)
            self.assertEqual(stdout.stdout, expected)
            # Existing non-source output is replaced atomically and repeatably.
            output.write_text("old candidate")
            for _ in range(2):
                run = _cli(source, "--output", output)
                self.assertEqual(run.returncode, 0, run.stderr)
                self.assertEqual(output.read_bytes(), expected)
            self.assertEqual(source.read_bytes(), before)
            record = json.loads(expected)
            self.assertEqual(record["schema"], matrix.SCHEMA)
            self.assertEqual(record["native_return"],
                             {"bytes": len(before), "sha256": hashlib.sha256(before).hexdigest()})
            self.assertEqual(_cli(source, "--check", output).returncode, 0)
            output.write_text("{}")
            self.assertNotEqual(_cli(source, "--check", output).returncode, 0)
            self.assertEqual(output.read_text(), "{}")
            self.assertEqual(source.read_bytes(), before)

    def test_committed_record_replays_all_controls_and_classification(self):
        record = json.loads(EVIDENCE.read_bytes())
        self.assertEqual(record["schema"], matrix.SCHEMA)
        self.assertEqual(EVIDENCE.read_bytes(), matrix.serialize(record).encode("utf-8"))
        self.assertEqual(record["classification"], matrix.classify(record["classification"]["observations"]))
        self.assertTrue(record["classification"]["controls"]["valid"])
        self.assertTrue(all(record["classification"]["paired_effects"].values()))
        self.assertEqual(record["classification"]["verdict"],
                         "ZERO_DURATION_DATE_PASSTHROUGH_WITH_FREE_SLACK_MATCHING_INACTIVE_EDGE_GAP")
        self.assertEqual(record["native_return"], {
            "bytes": 139672,
            "sha256": "c245ef00b9ae71a9f901bb3775158c21dd87b88115e5e028656d176abda2d549",
        })
        self.assertEqual(record["project"]["build_number"], "16.0.20228.20188")

    def test_external_native_return_reproduces_committed_record(self):
        value = os.environ.get("STO_RC02_NATIVE_RETURN")
        if not value:
            if os.environ.get("STO_REQUIRE_RC02_NATIVE") == "1":
                self.fail("STO_RC02_NATIVE_RETURN is required")
            self.skipTest("external RC02 native return not supplied")
        source = Path(value)
        before = source.read_bytes()
        record = matrix.analyze(before)
        self.assertEqual(matrix.serialize(record).encode("utf-8"), EVIDENCE.read_bytes())
        result = _cli(source, "--check", EVIDENCE)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(source.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
