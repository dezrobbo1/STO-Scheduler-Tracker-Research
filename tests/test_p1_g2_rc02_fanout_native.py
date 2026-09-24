"""Tests for the bounded P1-G2 RC02 inactive fan-out native experiment."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

from scripts.evidence import p1_g2_rc02_fanout_native as fanout
from scripts.evidence import p1_g2_rc02_fanout_native_generate as generate

NS = {"p": "http://schemas.microsoft.com/project"}
ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/evidence/p1_g2_rc02_fanout_native.py"


def _write_fixture(path: Path) -> Path:
    path.write_bytes(generate.build_fixture())
    return path


def _calculated_fixture(path: Path, *, backward: str = "earliest", free_slack: int = 0) -> Path:
    """Synthetic calculated fixture for classifier tests; never native evidence."""
    _write_fixture(path)
    tree = ET.parse(path)
    root = tree.getroot()
    tasks = {
        task.findtext("p:Name", namespaces=NS): task
        for task in root.findall("p:Tasks/p:Task", NS)
    }
    start = datetime(2026, 10, 12, 8)

    def set_value(name: str, field: str, value: object) -> None:
        node = tasks[name].find(f"p:{field}", NS)
        assert node is not None
        node.text = str(value)

    def span(name: str, early: int, late: int, hours: int, free: int = 0) -> None:
        for field, offset in (
            ("Start", early), ("EarlyStart", early),
            ("Finish", early + hours), ("EarlyFinish", early + hours),
            ("LateStart", late), ("LateFinish", late + hours),
        ):
            set_value(name, field, (start + timedelta(hours=offset)).isoformat())
        set_value(name, "TotalSlack", (late - early) * 600)
        set_value(name, "FreeSlack", free * 600)

    span("RC02-FANOUT-FINISH-DRIVER", 0, 0, 336)

    # Active A.
    span("RC02-FO-A-A-PRED", 0, 168, 24, 0)
    span("RC02-FO-A-A-MID", 24, 192, 48, 0)
    span("RC02-FO-A-A-S1", 72, 240, 96, 168)
    span("RC02-FO-A-A-S2", 72, 312, 24, 240)

    # Inactive A.
    a_pred_lf = 240 if backward == "earliest" else 312
    span("RC02-FO-A-I-PRED", 0, a_pred_lf - 24, 24, 0)
    span("RC02-FO-A-I-MID", 24, 192, 48, 0)
    span("RC02-FO-A-I-S1", 24, 240, 96, 216)
    span("RC02-FO-A-I-S2", 24, 312, 24, 288)

    # Active B.
    span("RC02-FO-B-A-PRED", 0, 168, 24, 0)
    span("RC02-FO-B-A-MID", 24, 192, 48, 0)
    span("RC02-FO-B-A-OTHER", 0, 144, 96, 0)
    span("RC02-FO-B-A-S1", 72, 312, 24, 240)
    span("RC02-FO-B-A-S2", 96, 240, 96, 144)

    # Inactive B.
    b_pred_lf = 240 if backward == "earliest" else 312
    span("RC02-FO-B-I-PRED", 0, b_pred_lf - 24, 24, 0)
    span("RC02-FO-B-I-MID", 24, 192, 48, 0)
    span("RC02-FO-B-I-OTHER", 0, 144, 96, 0)
    span("RC02-FO-B-I-S1", 24, 312, 24, 288)
    span("RC02-FO-B-I-S2", 96, 240, 96, 144)

    # Active C.
    span("RC02-FO-C-A-PRED", 0, 216, 24, 0)
    span("RC02-FO-C-A-MID", 24, 240, 48, 24)
    span("RC02-FO-C-A-O1", 0, 216, 96, 0)
    span("RC02-FO-C-A-O2", 0, 168, 120, 0)
    span("RC02-FO-C-A-S1", 96, 312, 24, 216)
    span("RC02-FO-C-A-S2", 120, 288, 48, 168)

    # Inactive C, including the Free-Slack sentinel result under test.
    c_pred_lf = 288 if backward == "earliest" else 312
    span("RC02-FO-C-I-PRED", 0, c_pred_lf - 24, 24, 0)
    set_value("RC02-FO-C-I-PRED", "FreeSlack", free_slack)
    span("RC02-FO-C-I-MID", 24, 240, 48, 0)
    span("RC02-FO-C-I-O1", 0, 216, 96, 0)
    span("RC02-FO-C-I-O2", 0, 168, 120, 0)
    span("RC02-FO-C-I-S1", 96, 312, 24, 216)
    span("RC02-FO-C-I-S2", 120, 288, 48, 168)

    tree.write(path, encoding="utf-8", xml_declaration=True)
    return path


class Rc02FanoutNativeTests(unittest.TestCase):
    def test_generator_is_deterministic_and_pinned(self):
        first = generate.build_fixture()
        self.assertEqual(first, generate.build_fixture())
        self.assertEqual(len(first), fanout.INPUT_BYTES)
        self.assertEqual(hashlib.sha256(first).hexdigest(), fanout.INPUT_SHA256)
        _, rows = fanout.parse(first)
        self.assertEqual(set(rows), fanout.REQUIRED)
        self.assertEqual(
            {name for name, row in rows.items() if row["Active"] == "0"},
            fanout.INACTIVE,
        )
        self.assertEqual(rows["RC02-FO-B-I-S2"]["predecessor_uids"], ["16", "17"])
        self.assertEqual(rows["RC02-FO-C-I-S1"]["predecessor_uids"], ["27", "28"])
        self.assertEqual(rows["RC02-FO-C-I-PRED"]["FreeSlack"], "12345")

    def test_synthetic_earliest_successor_result_authorizes_only_diagnostic_rerun(self):
        with tempfile.TemporaryDirectory() as directory:
            path = _calculated_fixture(Path(directory) / "earliest.xml")
            record = fanout.analyze(path.read_bytes(), owner_confirmed_opened_input=True)
        result = record["classification"]
        self.assertTrue(result["controls"]["valid"])
        self.assertEqual(
            result["components"],
            {
                "forward_semantic": "ZERO_DURATION_FANOUT_FORWARD_PASSTHROUGH_SUPPORTED",
                "backward_semantic": "EARLIEST_ACTIVE_SUCCESSOR_LATE_BOUNDARY_SUPPORTED",
                "free_slack_observation": "SENTINEL_CHANGED_MATCHES_INACTIVE_EDGE_GAP",
            },
        )
        self.assertEqual(result["verdict"], "FANOUT_EARLIEST_LATE_BOUNDARY_WITH_INACTIVE_EDGE_FREE_SLACK_OBSERVED")
        self.assertEqual(result["inactive_pairs"]["A"]["earliest_successor"], "S1")
        self.assertEqual(result["inactive_pairs"]["B"]["earliest_successor"], "S2")
        self.assertEqual(result["inactive_pairs"]["C"]["earliest_successor"], "S2")
        self.assertEqual(
            result["paired_late_delta_units"],
            {"A": 28800, "B": 28800, "C": 28800},
        )
        self.assertEqual(
            result["free_slack_sentinel"],
            {
                "seeded_value": 12345,
                "observed_value": 0,
                "sentinel_changed": True,
                "inactive_edge_gap": 0,
                "direct_successor_gaps": {"S1": 43200, "S2": 57600},
                "direct_successor_min_gap": 43200,
                "matches_inactive_edge_gap": True,
                "matches_direct_successor_min_gap": False,
            },
        )
        self.assertTrue(result["decision"]["boiler_counterfactual_rerun_authorized"])
        self.assertFalse(result["decision"]["production_scheduler_change_authorized"])
        self.assertFalse(result["decision"]["p1_g2_closed"])

    def test_owner_confirmation_is_required_for_authorization(self):
        with tempfile.TemporaryDirectory() as directory:
            path = _calculated_fixture(Path(directory) / "earliest.xml")
            record = fanout.analyze(path.read_bytes(), owner_confirmed_opened_input=False)
        self.assertFalse(record["input_lineage"]["owner_confirmed_opened_pinned_input"])
        self.assertFalse(record["input_lineage"]["machine_proven_from_return_alone"])
        self.assertFalse(record["classification"]["decision"]["boiler_counterfactual_rerun_authorized"])

    def test_latest_successor_observation_does_not_false_pass(self):
        with tempfile.TemporaryDirectory() as directory:
            path = _calculated_fixture(Path(directory) / "latest.xml", backward="latest")
            _, rows = fanout.read(path)
            result = fanout.classify(rows)
        self.assertTrue(result["controls"]["valid"])
        self.assertEqual(result["components"]["backward_semantic"], "LATEST_ACTIVE_SUCCESSOR_LATE_BOUNDARY_SUPPORTED")
        self.assertEqual(result["verdict"], "FANOUT_NATIVE_RULE_NOT_ESTABLISHED")
        self.assertFalse(result["decision"]["boiler_counterfactual_rerun_authorized"])

    def test_unchanged_free_slack_sentinel_does_not_false_pass(self):
        with tempfile.TemporaryDirectory() as directory:
            path = _calculated_fixture(Path(directory) / "retained.xml", free_slack=12345)
            _, rows = fanout.read(path)
            result = fanout.classify(rows)
        self.assertEqual(result["components"]["free_slack_observation"], "SENTINEL_RETAINED_NOT_ESTABLISHED")
        self.assertFalse(result["decision"]["boiler_counterfactual_rerun_authorized"])


    def test_collapsed_inactive_late_boundaries_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = _calculated_fixture(Path(directory) / "collapsed.xml")
            tree = ET.parse(path)
            tasks = {
                task.findtext("p:Name", namespaces=NS): task
                for task in tree.getroot().findall("p:Tasks/p:Task", NS)
            }
            for field, value in (
                ("LateStart", "2026-10-22T08:00:00"),
                ("LateFinish", "2026-10-23T08:00:00"),
            ):
                node = tasks["RC02-FO-B-I-S1"].find(f"p:{field}", NS)
                assert node is not None
                node.text = value
            tree.write(path, encoding="utf-8", xml_declaration=True)
            _, rows = fanout.read(path)
            result = fanout.classify(rows)
        self.assertFalse(result["controls"]["valid"])
        self.assertEqual(result["verdict"], "FANOUT_NATIVE_RULE_NOT_ESTABLISHED")
        self.assertFalse(result["decision"]["boiler_counterfactual_rerun_authorized"])

    def test_unrecalculated_input_does_not_establish_rule(self):
        record = fanout.analyze(generate.build_fixture(), owner_confirmed_opened_input=True)
        self.assertFalse(record["classification"]["controls"]["valid"])
        self.assertEqual(record["classification"]["verdict"], "FANOUT_NATIVE_RULE_NOT_ESTABLISHED")
        self.assertFalse(record["classification"]["decision"]["boiler_counterfactual_rerun_authorized"])

    def test_topology_and_fixed_inputs_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = _calculated_fixture(Path(directory) / "changed.xml")
            tree = ET.parse(path)
            task = next(
                row for row in tree.getroot().findall("p:Tasks/p:Task", NS)
                if row.findtext("p:Name", namespaces=NS) == "RC02-FO-B-I-S2"
            )
            link = task.findall("p:PredecessorLink", NS)[0]
            lag = link.find("p:LinkLag", NS)
            assert lag is not None
            lag.text = "10"
            tree.write(path, encoding="utf-8", xml_declaration=True)
            with self.assertRaisesRegex(SystemExit, "fan-out topology"):
                fanout.read(path)

    def test_cli_refuses_output_aliases_without_changing_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = _calculated_fixture(root / "source.xml")
            before = source.read_bytes()
            symlink = root / "alias.xml"
            symlink.symlink_to(source)
            hardlink = root / "hard.xml"
            os.link(source, hardlink)
            for output in (source, symlink, hardlink):
                result = subprocess.run(
                    [sys.executable, str(SCRIPT), str(source), "--confirm-opened-input", "--output", str(output)],
                    capture_output=True,
                    text=True,
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("output must be separate", result.stderr)
                self.assertEqual(source.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
