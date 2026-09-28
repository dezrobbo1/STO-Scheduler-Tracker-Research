"""V3 preregistration tests. Synthetic saves are NEVER native evidence."""
from __future__ import annotations

from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

from scripts.evidence import p1_g2_rc01_networked_v3 as native
from scripts.evidence import p1_g2_rc01_networked_v3_generate as matrix
from scripts.evidence import p1_g2_rc01_networked_v3_oracle as oracle

ROOT = Path(__file__).resolve().parents[1]
NS = {"p": matrix.URI}


def find(root: ET.Element, container: str, uid: int) -> ET.Element:
    return next(item for item in root.findall(f"p:{container}/*", NS)
                if item.findtext("p:UID", namespaces=NS) == str(uid))


def set_field(element: ET.Element, field: str, value: str) -> None:
    target = element.find(f"p:{field}", NS)
    assert target is not None
    target.text = value


def encoded(root: ET.Element) -> bytes:
    return ET.tostring(root, encoding="utf-8", xml_declaration=True) + b"\n"


def synthetic_oracle_save(*, padded: bool = False, duration_model: str = "PROJECT") -> bytes:
    """Test double only: never publish as native observation."""
    root = ET.fromstring(matrix.build_fixture())
    predicted = oracle.padded_reference() if padded else oracle.reference()
    tasks, _, assignments = matrix.graph()
    set_field(root, "BuildNumber", "16.0.99999.99999")
    set_field(root, "FinishDate", predicted["_project_finish"].isoformat())
    for name, spec in tasks.items():
        row = find(root, "Tasks", spec["uid"])
        expected = predicted[name]
        for field, key in (("Start", "early_start"), ("Finish", "early_finish"),
                           ("EarlyStart", "early_start"), ("EarlyFinish", "early_finish"),
                           ("LateStart", "late_start"), ("LateFinish", "late_finish")):
            set_field(row, field, expected[key].isoformat())
        minutes = (oracle.signed_project_minutes(expected["early_start"], expected["early_finish"])
                   if duration_model == "PROJECT" else
                   int((expected["early_finish"] - expected["early_start"]).total_seconds() // 60))
        for field in ("Duration", "RemainingDuration"):
            set_field(row, field, f"PT{minutes // 60}H{minutes % 60}M0S")
        for field, key in (("TotalSlack", "total_slack_minutes"),
                           ("FreeSlack", "free_slack_minutes")):
            set_field(row, field, str(expected[key] * 10))
        set_field(row, "Critical", "1" if expected["critical"] else "0")
    for uid, assignment in assignments.items():
        row = find(root, "Assignments", uid)
        start, finish = predicted[assignment["task"]]["assignments"][uid]
        set_field(row, "Start", start.isoformat())
        set_field(row, "Finish", finish.isoformat())
    return encoded(root)


class NetworkedV3Tests(unittest.TestCase):
    def test_exact_fixture_and_cli_generator(self):
        payload = matrix.build_fixture()
        self.assertEqual((ROOT / matrix.FIXTURE).read_bytes(), payload)
        self.assertEqual(len(payload), matrix.INPUT_BYTES)
        self.assertEqual(hashlib.sha256(payload).hexdigest(), matrix.INPUT_SHA256)
        self.assertEqual(payload, matrix.build_fixture())
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "generated.xml"
            proc = subprocess.run([sys.executable,
                                   str(ROOT / "scripts/evidence/p1_g2_rc01_networked_v3_generate.py"),
                                   str(target)], cwd=ROOT, capture_output=True, text=True)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual(target.read_bytes(), payload)

    def test_all_ten_root_shapes_mapped_from_exact_merged_audit(self):
        mapping = matrix.root_mapping(ROOT / matrix.AUDIT)
        self.assertEqual({k: row["class"] for k, row in mapping.items()}, {
            "L0070": "A", "L0075": "A", "L0080": "B", "L0083": "A", "L0084": "C",
            "L0114": "C", "L0127": "D", "L0148": "C", "L0157": "E", "L0190": "F"})
        self.assertEqual(mapping["L0084"]["native_case"], "C-CALENDAR-IDENTITY-TWIN")
        self.assertEqual([k for k, row in mapping.items() if row["adjacent_case"]],
                         ["L0080", "L0084"])
        self.assertEqual(matrix.AUDIT_SHA256,
                         hashlib.sha256((ROOT / matrix.AUDIT).read_bytes()).hexdigest())

    def test_current_canonical_import_preserves_experiment_inputs(self):
        from sto.core.model.migrate.sto_v011 import migrate
        from sto.legacy import import_mspdi
        schedule = migrate(import_mspdi(ROOT / matrix.FIXTURE))[0]
        self.assertEqual((len(schedule.activities), len(schedule.assignments),
                          len(schedule.resources), len(schedule.calendars)), (35, 46, 46, 4))
        self.assertEqual({a.duration_type.value for a in schedule.activities}, {"fixed_units"})
        self.assertTrue(all(row.start is not None and row.finish is not None and
                            row.units.budgeted_permille in (1000, 2000) and
                            row.work.budgeted_seconds > 0 for row in schedule.assignments))
        self.assertTrue(all(resource.calendar_uid in {cal.uid for cal in schedule.calendars}
                            for resource in schedule.resources))

    def test_allocation_arithmetic_network_order_identity_and_fanout(self):
        tasks, edges, assignments = matrix.graph()
        self.assertEqual(len(matrix.CASES), 10)
        for name in matrix.CASES:
            if name == "ADJACENT-RC01":
                continue
            rows = [a for a in assignments.values() if a["task"] == name]
            self.assertEqual(len(rows), 2)
            effective = matrix.SHAPES[tasks[name]["kind"]][1]
            self.assertEqual({a["work"] / a["units"] for a in rows}, {effective})
            self.assertEqual({a["calendar"] for a in rows},
                             {2, 4} if name == "C-CALENDAR-IDENTITY-TWIN" else {2, 3})
            self.assertEqual(tasks[name]["predecessors"], (f"{name}-PRE",))
        self.assertEqual(tasks["GAP-PRE"]["duration"], 8)
        self.assertEqual([a["role"] for a in assignments.values() if a["task"] == "A"],
                         ["24H", "10H"])
        self.assertEqual([a["role"] for a in assignments.values() if a["task"] == "A-ORDER-TWIN"],
                         ["10H", "24H"])
        self.assertEqual(tasks["ADJACENT-B"]["predecessors"], ("ADJACENT-C",))
        self.assertEqual({e["successor"] for e in edges if e["predecessor"] == "D"},
                         {"D-POST", "D-POST-LONG"})
        self.assertTrue(all(e["type"] == 1 and e["lag"] == 0 for e in edges))

    def test_independent_forward_backward_float_predictions(self):
        result = oracle.reference()
        canonical = json.dumps(result, sort_keys=True, separators=(",", ":"),
                               default=lambda value: value.isoformat() if isinstance(value, datetime)
                               else str(value)).encode()
        self.assertEqual(hashlib.sha256(canonical).hexdigest(),
                         "e4c9182660a825f68c9ec79f1ec8a02738c92c628329567e0cbc1cc4c843c1dc")
        self.assertEqual(result["_project_finish"], datetime(2026, 10, 15, 8))
        self.assertEqual((result["A"]["early_start"], result["A"]["early_finish"]),
                         (datetime(2026, 10, 12, 9), datetime(2026, 10, 12, 11)))
        self.assertEqual(result["A"]["effective_hours"], {21: 2, 22: 2})
        self.assertEqual(result["B"]["early_finish"], datetime(2026, 10, 12, 13))
        self.assertEqual(result["F"]["early_finish"], datetime(2026, 10, 12, 15))
        self.assertEqual(result["D"]["free_slack_minutes"], 630)
        self.assertEqual((result["GAP"]["early_start"], result["GAP"]["early_finish"]),
                         (datetime(2026, 10, 12, 16), datetime(2026, 10, 13, 8)))
        self.assertEqual(oracle.signed_project_minutes(datetime(2026, 10, 12, 16),
                                                       datetime(2026, 10, 13, 8)), 30)
        self.assertEqual(result["D"]["late_finish"],
                         result["D-POST-LONG"]["late_start"])
        self.assertGreater(result["D-POST"]["late_start"], result["D-POST-LONG"]["late_start"])
        self.assertEqual(result["ADJACENT-B"]["early_start"],
                         result["ADJACENT-C"]["early_finish"])
        self.assertEqual(result["ADJACENT-C"]["late_finish"],
                         result["ADJACENT-B"]["late_start"])
        self.assertEqual(result["FINISH-DRIVER"]["total_slack_minutes"], 0)
        self.assertTrue(result["FINISH-DRIVER"]["critical"])
        self.assertGreater(result["C"]["total_slack_minutes"], 0)
        self.assertEqual(result["A"]["early_finish"], result["A-ORDER-TWIN"]["early_finish"])
        self.assertEqual(result["C"]["late_start"], result["C-CALENDAR-IDENTITY-TWIN"]["late_start"])

    def test_unrecalculated_input_and_synthetic_oracle_not_evidence(self):
        input_result = native.analyze(matrix.build_fixture())
        self.assertEqual(input_result["classification"]["verdict"],
                         "V3_NETWORKED_ASSIGNMENT_ENVELOPE_INCONCLUSIVE")
        self.assertFalse(input_result["decision"]["production_rc01_correction_authorized"])
        # Deliberately forged test data exercises predicates without claiming
        # a Project result. It is never committed, returned or logged as native.
        sample = native.analyze(synthetic_oracle_save())
        self.assertEqual(sample["classification"]["verdict"],
                         "V3_NETWORKED_ASSIGNMENT_ENVELOPE_SUPPORTED")
        self.assertFalse(sample["decision"]["production_rc01_correction_authorized"])
        self.assertFalse(sample["decision"]["native_v3_supported"])
        self.assertTrue(sample["decision"]["machine_predicates_match_candidate"])
        self.assertEqual(sample["decision"]["native_provenance"],
                         "UNVERIFIED_OPERATOR_ATTESTATION_REQUIRED")
        self.assertEqual(sample["root_to_native_case"], matrix.root_mapping(ROOT / matrix.AUDIT))

    def test_project_calendar_duration_predicates_for_off_hours(self):
        prereg = json.loads((ROOT / "docs/evidence/p1-g2-rc01-networked-native-v3-r3-predeclared-2026-09-28.json").read_text())
        self.assertEqual(prereg["preregistration_id"], matrix.EXPERIMENT_ID + "-R3-WORKING-DURATION")
        self.assertEqual(prereg["input"]["sha256"], matrix.INPUT_SHA256)
        self.assertEqual(prereg["input"]["bytes"], matrix.INPUT_BYTES)
        self.assertEqual(prereg["supersedes_unrun_r2_preregistration"]["json_sha256"],
                         hashlib.sha256((ROOT / "docs/evidence/p1-g2-rc01-networked-native-v3-r2-predeclared-2026-09-28.json").read_bytes()).hexdigest())
        self.assertEqual(prereg["supersedes_unrun_r2_preregistration"]["md_sha256"],
                         hashlib.sha256((ROOT / "docs/evidence/p1-g2-rc01-networked-native-v3-r2-predeclared-2026-09-28.md").read_bytes()).hexdigest())
        root = ET.fromstring(synthetic_oracle_save())
        tasks = matrix.graph()[0]
        gap = find(root, "Tasks", tasks["GAP"]["uid"])
        driver = find(root, "Tasks", tasks["FINISH-DRIVER"]["uid"])
        self.assertEqual(gap.findtext("p:Duration", namespaces=NS), "PT0H30M0S")
        self.assertEqual(driver.findtext("p:Duration", namespaces=NS), "PT24H0M0S")
        self.assertEqual(native.analyze(encoded(root))["classification"]["verdict"],
                         "V3_NETWORKED_ASSIGNMENT_ENVELOPE_SUPPORTED")
        padded = native.analyze(synthetic_oracle_save(padded=True))
        self.assertEqual(padded["classification"]["verdict"],
                         "V3_NETWORKED_ASSIGNMENT_ENVELOPE_REJECTED")
        self.assertFalse(padded["decision"]["production_rc01_correction_authorized"])

    def test_distinguishing_duration_models_do_not_assume_v2_result(self):
        prereg = json.loads((ROOT / "docs/evidence/p1-g2-rc01-networked-native-v3-r4-predeclared-2026-09-28.json").read_text())
        self.assertEqual(prereg["preregistration_id"], matrix.PREREGISTRATION_ID)
        self.assertEqual(prereg["input"]["sha256"], matrix.INPUT_SHA256)
        self.assertEqual(prereg["input"]["bytes"], matrix.INPUT_BYTES)
        self.assertEqual(prereg["supersedes_unrun_r3_preregistration"]["json_sha256"],
                         hashlib.sha256((ROOT / "docs/evidence/p1-g2-rc01-networked-native-v3-r3-predeclared-2026-09-28.json").read_bytes()).hexdigest())
        self.assertEqual(prereg["supersedes_unrun_r3_preregistration"]["md_sha256"],
                         hashlib.sha256((ROOT / "docs/evidence/p1-g2-rc01-networked-native-v3-r3-predeclared-2026-09-28.md").read_bytes()).hexdigest())
        tasks = matrix.graph()[0]
        for mode, gap, driver, post in (("PROJECT", "PT0H30M0S", "PT24H0M0S", "PT0H0M0S"),
                                         ("RESOURCE_UNION", "PT16H0M0S", "PT72H0M0S", "PT1H0M0S")):
            with self.subTest(mode=mode):
                root = ET.fromstring(synthetic_oracle_save(duration_model=mode))
                for name, value in (("GAP", gap), ("FINISH-DRIVER", driver), ("D-POST", post)):
                    self.assertEqual(find(root, "Tasks", tasks[name]["uid"]).findtext("p:Duration", namespaces=NS), value)
                outcome = native.analyze(encoded(root))
                self.assertEqual(outcome["classification"]["verdict"],
                                 "V3_NETWORKED_ASSIGNMENT_ENVELOPE_SUPPORTED")
                self.assertEqual(outcome["classification"]["duration_model"], mode)
                rejected = native.analyze(synthetic_oracle_save(padded=True, duration_model=mode))
                self.assertEqual(rejected["classification"]["verdict"],
                                 "V3_NETWORKED_ASSIGNMENT_ENVELOPE_REJECTED")
                self.assertEqual(rejected["classification"]["duration_model"], mode)
                self.assertFalse(outcome["decision"]["production_rc01_correction_authorized"])
        root = ET.fromstring(synthetic_oracle_save(duration_model="PROJECT"))
        set_field(find(root, "Tasks", tasks["D-POST"]["uid"]), "Duration", "PT1H0M0S")
        set_field(find(root, "Tasks", tasks["D-POST"]["uid"]), "RemainingDuration", "PT1H0M0S")
        self.assertEqual(native.analyze(encoded(root))["classification"]["verdict"],
                         "V3_NETWORKED_ASSIGNMENT_ENVELOPE_INCONCLUSIVE")

    def test_input_mutations_fail_before_classification(self):
        tasks, _, assignments = matrix.graph()
        mutations = [
            ("Tasks", tasks["A"]["uid"], "UID", "900"),
            ("Tasks", tasks["A"]["uid"], "GUID", "00000000-0000-4000-8000-000000000001"),
            ("Tasks", tasks["A"]["uid"], "Type", "1"),
            ("Tasks", tasks["A"]["uid"], "EffortDriven", "1"),
            ("Tasks", tasks["A"]["uid"], "IgnoreResourceCalendar", "1"),
            ("Tasks", tasks["A"]["uid"], "Work", "PT9H0M0S"),
            ("Tasks", tasks["A"]["uid"], "Manual", "1"),
            ("Tasks", tasks["A"]["uid"], "PercentComplete", "1"),
            ("Tasks", tasks["A"]["uid"], "ConstraintType", "2"),
            ("Tasks", tasks["A"]["uid"], "LevelingDelay", "1"),
            ("Resources", 21, "UID", "900"),
            ("Resources", 21, "CalendarUID", "3"),
            ("Resources", 21, "CanLevel", "1"),
            ("Calendars", 3, "BaseCalendarUID", "2"),
            ("Assignments", 21, "UID", "900"),
            ("Assignments", 21, "Work", "PT5H0M0S"),
            ("Assignments", 21, "Units", "1"),
            ("Assignments", 21, "ResourceUID", "22"),
            ("Assignments", 21, "Delay", "1"),
            ("Assignments", 21, "LevelingDelay", "1"),
        ]
        for section, uid, field, value in mutations:
            with self.subTest(section=section, uid=uid, field=field):
                root = ET.fromstring(synthetic_oracle_save())
                set_field(find(root, section, uid), field, value)
                self.assertEqual(native.analyze(encoded(root))["classification"]["verdict"],
                                 "V3_INPUT_CONTRACT_VIOLATED")
        for mode in ("predecessor", "lag", "calendar_interval", "assignment_order",
                     "added_levelling", "unbounded_start", "task_calendar", "project_start"):
            with self.subTest(mode=mode):
                root = ET.fromstring(synthetic_oracle_save())
                if mode in ("predecessor", "lag"):
                    link = find(root, "Tasks", tasks["D-POST"]["uid"]).findall("p:PredecessorLink", NS)[0]
                    set_field(link, "PredecessorUID" if mode == "predecessor" else "LinkLag", "55")
                elif mode == "calendar_interval":
                    set_field(find(root, "Calendars", 3).find("p:WeekDays/p:WeekDay/p:WorkingTimes/p:WorkingTime", NS),
                              "FromTime", "08:00:00")
                elif mode == "assignment_order":
                    rows = root.find("p:Assignments", NS)
                    rows[0], rows[1] = rows[1], rows[0]
                elif mode == "added_levelling":
                    matrix.add(find(root, "Tasks", tasks["A"]["uid"]), "UnknownSchedulingFlag", 1)
                elif mode == "unbounded_start":
                    set_field(find(root, "Tasks", tasks["A-PRE"]["uid"]), "Start", "2026-10-13T08:00:00")
                elif mode == "task_calendar":
                    matrix.add(find(root, "Tasks", tasks["A"]["uid"]), "CalendarUID", 2)
                else:
                    set_field(root, "StartDate", "2026-10-13T08:00:00")
                self.assertEqual(native.analyze(encoded(root))["classification"]["verdict"],
                                 "V3_INPUT_CONTRACT_VIOLATED")

    def test_v2_witnessed_normalization_only(self):
        root = ET.fromstring(synthetic_oracle_save())
        set_field(root, "GUID", "04C578DF-D5BA-F111-9818-902E162C1984")
        set_field(root, "AutoLink", "0")
        for uid in (2, 3, 4):
            set_field(find(root, "Calendars", uid), "Name", "Unassigned")
        set_field(find(root, "Resources", 21), "GUID", matrix.guid("calendar", 2))
        task = find(root, "Tasks", matrix.graph()[0]["A"]["uid"])
        matrix.add(task, "CalendarUID", "-1")
        set_field(task, "LevelingDelayFormat", "8")
        self.assertEqual(native.analyze(encoded(root))["classification"]["verdict"],
                         "V3_NETWORKED_ASSIGNMENT_ENVELOPE_SUPPORTED")
        set_field(find(root, "Calendars", 3), "GUID", matrix.guid("calendar", 2))
        self.assertEqual(native.analyze(encoded(root))["classification"]["verdict"],
                         "V3_INPUT_CONTRACT_VIOLATED")

    def test_repeated_valid_timephased_rows_and_changed_work(self):
        root = ET.fromstring(synthetic_oracle_save())
        uid = next(uid for uid, spec in matrix.graph()[2].items()
                   if spec["task"] == "FINISH-DRIVER")
        row = find(root, "Assignments", uid)
        for start, finish in (("2026-10-12T08:00:00", "2026-10-13T20:00:00"),
                              ("2026-10-13T20:00:00", "2026-10-15T08:00:00")):
            period = ET.SubElement(row, matrix.q("TimephasedData"))
            for field, value in (("Type", 1), ("UID", uid), ("Unit", 1),
                                 ("Start", start), ("Finish", finish),
                                 ("Value", "PT36H0M0S")):
                matrix.add(period, field, value)
        self.assertEqual(native.analyze(encoded(root))["classification"]["verdict"],
                         "V3_NETWORKED_ASSIGNMENT_ENVELOPE_SUPPORTED")
        set_field(row.findall("p:TimephasedData", NS)[1], "Value", "PT35H0M0S")
        self.assertEqual(native.analyze(encoded(root))["classification"]["verdict"],
                         "V3_INPUT_CONTRACT_VIOLATED")

    def test_output_changes_are_not_oracle_inputs(self):
        root = ET.fromstring(synthetic_oracle_save())
        set_field(find(root, "Tasks", matrix.graph()[0]["C"]["uid"]), "LateStart",
                  "2026-10-14T10:00:00")
        result = native.analyze(encoded(root))
        self.assertEqual(result["classification"]["verdict"],
                         "V3_NETWORKED_ASSIGNMENT_ENVELOPE_INCONCLUSIVE")
        self.assertIn("C.LateStart", result["classification"]["failed_predicates"])
        self.assertFalse(result["decision"]["production_rc01_correction_authorized"])

    def test_only_coherent_alternative_is_rejected(self):
        alternative = oracle.padded_reference()
        for name, row in alternative.items():
            if name == "_project_finish":
                continue
            self.assertTrue(all(row["early_start"] <= start <= finish <= row["early_finish"]
                                for start, finish in row["assignments"].values()))
            self.assertTrue(all(row["late_start"] <= start <= finish <= row["late_finish"]
                                for start, finish in row["late_assignments"].values()))
        result = native.analyze(synthetic_oracle_save(padded=True))
        self.assertEqual(result["classification"]["verdict"],
                         "V3_NETWORKED_ASSIGNMENT_ENVELOPE_REJECTED")
        self.assertFalse(result["decision"]["production_rc01_correction_authorized"])
        altered = ET.fromstring(synthetic_oracle_save(padded=True))
        set_field(find(altered, "Tasks", matrix.graph()[0]["B"]["uid"]),
                  "LateStart", "2026-10-14T08:00:00")
        self.assertEqual(native.analyze(encoded(altered))["classification"]["verdict"],
                         "V3_NETWORKED_ASSIGNMENT_ENVELOPE_INCONCLUSIVE")

    def test_aliases_atomic_output_and_immutable_sources(self):
        lineage_before = {path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest()
                          for path in native.LINEAGE}
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            source = directory / "returned.xml"
            source.write_bytes(matrix.build_fixture())
            original = hashlib.sha256(source.read_bytes()).hexdigest()
            output = directory / "receipt.json"
            command = [sys.executable, str(ROOT / "scripts/evidence/p1_g2_rc01_networked_v3.py"),
                       str(source), "--output"]
            aliases = [source, directory / "missing" / ".." / "returned.xml"]
            symlink = directory / "alias.xml"
            symlink.symlink_to(source)
            aliases.append(symlink)
            hardlink = directory / "hardlink.xml"
            os.link(source, hardlink)
            aliases.append(hardlink)
            for alias in aliases:
                with self.subTest(alias=str(alias)):
                    process = subprocess.run(command + [str(alias)], cwd=ROOT,
                                             capture_output=True, text=True)
                    self.assertNotEqual(process.returncode, 0)
                    self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), original)
            for _ in range(2):
                process = subprocess.run(command + [str(output)], cwd=ROOT,
                                         capture_output=True, text=True)
                self.assertEqual(process.returncode, 0, process.stderr)
                self.assertEqual(json.loads(output.read_text())["classification"]["verdict"],
                                 "V3_NETWORKED_ASSIGNMENT_ENVELOPE_INCONCLUSIVE")
                self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), original)
            self.assertFalse(list(directory.glob(".receipt.json.*.tmp")))
            from scripts.evidence import p1_g2_rc01_assignment_native_v2 as publisher
            prior = output.read_bytes()
            real_replace = publisher.os.replace
            def check_replacement(temporary, destination):
                self.assertEqual(output.read_bytes(), prior)
                self.assertEqual(Path(temporary).read_text(), '{"complete": true}\n')
                return real_replace(temporary, destination)
            with patch.object(publisher.os, "replace", side_effect=check_replacement):
                publisher.write_output_safely(output, '{"complete": true}\n',
                                              {"returned source": source})
            self.assertEqual(output.read_text(), '{"complete": true}\n')
        self.assertEqual(lineage_before,
                         {path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest()
                          for path in native.LINEAGE})


if __name__ == "__main__":
    unittest.main()
