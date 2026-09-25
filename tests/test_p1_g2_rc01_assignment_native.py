"""Contract tests for the predeclared RC01 assignment-envelope native matrix."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import hashlib
import os
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET

from scripts.evidence import p1_g2_rc01_assignment_native as native
from scripts.evidence import p1_g2_rc01_assignment_native_generate as generate

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/P1-G2-RC01-ASSIGNMENT-ENVELOPE-NATIVE-MATRIX-V1.xml"
NATIVE_RETURN = os.environ.get("STO_RC01_ASSIGNMENT_NATIVE_RETURN")
REQUIRE_NATIVE_RETURN = os.environ.get("STO_REQUIRE_RC01_ASSIGNMENT_NATIVE_RETURN") == "1"
NS = {"p": generate.URI}


def _node(root: ET.Element, path: str, name: str | None = None) -> ET.Element:
    rows = root.findall(path, NS)
    if name is None:
        assert len(rows) == 1
        return rows[0]
    return next(row for row in rows if row.findtext("p:Name", namespaces=NS) == name)


def _set(row: ET.Element, field: str, value: object) -> None:
    node = row.find(f"p:{field}", NS)
    assert node is not None
    node.text = str(value)


def _simulated_supported_return() -> bytes:
    """Test data only; this is never described as a native observation."""
    root = ET.fromstring(generate.build_fixture())
    _set(root, "BuildNumber", "16.0.99999.99999")
    tasks = {
        row.findtext("p:Name", namespaces=NS): row
        for row in root.findall("p:Tasks/p:Task", NS)
    }
    assignments = {
        row.findtext("p:UID", namespaces=NS): row
        for row in root.findall("p:Assignments/p:Assignment", NS)
    }
    start = datetime.fromisoformat(generate.PROJECT_START)

    def date(hour: int) -> str:
        return start.replace(hour=hour).isoformat()

    for case in "AB":
        task = tasks[f"RC01-CASE-{case}"]
        for field, value in (("Start", date(8)), ("EarlyStart", date(8)),
                             ("Finish", date(17)), ("EarlyFinish", date(17))):
            _set(task, field, value)
    for case in "CD":
        task = tasks[f"RC01-CASE-{case}"]
        for field, value in (("Start", date(8)), ("EarlyStart", date(8)),
                             ("Finish", date(12)), ("EarlyFinish", date(12))):
            _set(task, field, value)
    for uid, role in generate.ASSIGNMENT_ROLES.items():
        assignment = assignments[str(uid)]
        begin, finish = ((13, 17) if role == "PM" else (8, 12))
        _set(assignment, "Start", date(begin))
        _set(assignment, "Finish", date(finish))
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


class Rc01AssignmentNativeTests(unittest.TestCase):
    def test_generator_is_deterministic_and_committed_fixture_is_exact(self):
        payload = generate.build_fixture()
        self.assertEqual(payload, generate.build_fixture())
        self.assertEqual(FIXTURE.read_bytes(), payload)
        self.assertEqual(len(payload), generate.INPUT_BYTES)
        self.assertEqual(hashlib.sha256(payload).hexdigest(), generate.INPUT_SHA256)

    def test_canonical_import_preserves_the_declared_inputs_and_observations(self):
        contract = generate.canonical_import_contract(generate.build_fixture())
        self.assertEqual(contract["activity_count"], 4)
        self.assertEqual(contract["assignment_count"], 7)
        self.assertTrue(contract["assignment_start_finish_preserved"])
        self.assertTrue(contract["resource_calendar_identity_preserved"])
        self.assertEqual(contract["task_duration_type"], "fixed_units")
        self.assertEqual(contract["canonical_effort_driven"], False)
        self.assertEqual(contract["effort_driven_storage"], "opaque_vendor_extension")
        self.assertEqual(
            contract["ignore_resource_calendar_storage"],
            "opaque_vendor_extension; clear value maps to canonical false semantic",
        )

    def test_parser_confirms_every_experiment_defining_input(self):
        parsed = native.parse_and_validate(generate.build_fixture())
        self.assertEqual(parsed["assignment_order"], list(generate.ASSIGNMENT_ORDER))
        self.assertEqual(set(parsed["tasks"]), {"A", "B", "C", "D"})
        self.assertEqual(parsed["tasks"]["A"]["type"], "0")
        self.assertEqual(parsed["tasks"]["A"]["effort_driven"], "0")
        self.assertEqual(parsed["tasks"]["A"]["ignore_resource_calendar"], "0")

    def test_mutated_task_resource_calendar_assignment_or_topology_fails_closed(self):
        mutations = (
            ("task identity", "p:Tasks/p:Task", "RC01-CASE-A", "GUID", "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"),
            ("task type", "p:Tasks/p:Task", "RC01-CASE-A", "Type", "1"),
            ("effort driven", "p:Tasks/p:Task", "RC01-CASE-A", "EffortDriven", "1"),
            ("ignore resource calendar", "p:Tasks/p:Task", "RC01-CASE-A", "IgnoreResourceCalendar", "1"),
            ("duration", "p:Tasks/p:Task", "RC01-CASE-A", "Duration", "PT5H0M0S"),
            ("start", "p:Tasks/p:Task", "RC01-CASE-A", "Start", "2026-10-12T09:00:00"),
            ("resource identity", "p:Resources/p:Resource", "RC01-AM", "GUID", "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"),
            ("resource calendar", "p:Resources/p:Resource", "RC01-AM", "CalendarUID", "3"),
        )
        for label, path, name, field, value in mutations:
            with self.subTest(label=label):
                root = ET.fromstring(generate.build_fixture())
                _set(_node(root, path, name), field, value)
                with self.assertRaisesRegex(native.NativeEvidenceError, label):
                    native.parse_and_validate(ET.tostring(root, encoding="utf-8", xml_declaration=True))

        for label, field, value in (("assignment work", "Work", "PT5H0M0S"),
                                    ("assignment units", "Units", "0.5"),
                                    ("assignment identity", "GUID", "cccccccc-cccc-4ccc-8ccc-cccccccccccc")):
            with self.subTest(label=label):
                root = ET.fromstring(generate.build_fixture())
                assignment = root.findall("p:Assignments/p:Assignment", NS)[0]
                _set(assignment, field, value)
                with self.assertRaisesRegex(native.NativeEvidenceError, label):
                    native.parse_and_validate(ET.tostring(root, encoding="utf-8", xml_declaration=True))

        root = ET.fromstring(generate.build_fixture())
        assignments = root.find("p:Assignments", NS)
        assert assignments is not None
        first = list(assignments)[0]
        assignments.remove(first)
        assignments.insert(1, first)
        with self.assertRaisesRegex(native.NativeEvidenceError, "assignment order"):
            native.parse_and_validate(ET.tostring(root, encoding="utf-8", xml_declaration=True))

        root = ET.fromstring(generate.build_fixture())
        calendar = _node(root, "p:Calendars/p:Calendar", "RC01-AM-CALENDAR")
        interval = calendar.find("p:WeekDays/p:WeekDay/p:WorkingTimes/p:WorkingTime/p:ToTime", NS)
        assert interval is not None
        interval.text = "12:30:00"
        with self.assertRaisesRegex(native.NativeEvidenceError, "calendar"):
            native.parse_and_validate(ET.tostring(root, encoding="utf-8", xml_declaration=True))

        root = ET.fromstring(generate.build_fixture())
        task = _node(root, "p:Tasks/p:Task", "RC01-CASE-A")
        link = ET.SubElement(task, generate.q("PredecessorLink"))
        generate.add(link, "PredecessorUID", "4")
        generate.add(link, "Type", "1")
        generate.add(link, "LinkLag", "0")
        with self.assertRaisesRegex(native.NativeEvidenceError, "topology"):
            native.parse_and_validate(ET.tostring(root, encoding="utf-8", xml_declaration=True))

        for label, container_name, source_path in (
            ("task identity set", "Tasks", "p:Tasks/p:Task"),
            ("resource identity set", "Resources", "p:Resources/p:Resource"),
            ("calendar identity set", "Calendars", "p:Calendars/p:Calendar"),
        ):
            with self.subTest(label=label):
                root = ET.fromstring(generate.build_fixture())
                container = root.find(f"p:{container_name}", NS)
                source = root.find(source_path, NS)
                assert container is not None and source is not None
                clone = deepcopy(source)
                _set(clone, "Name", f"UNDECLARED-{container_name}")
                container.append(clone)
                with self.assertRaisesRegex(native.NativeEvidenceError, label):
                    native.parse_and_validate(
                        ET.tostring(root, encoding="utf-8", xml_declaration=True)
                    )

    def test_unrecalculated_input_is_not_native_proof_and_authorizes_nothing(self):
        result = native.analyze(generate.build_fixture())
        self.assertEqual(result["classification"]["verdict"], "NOT_RUN_UNRECALCULATED_INPUT")
        self.assertFalse(result["decision"]["native_experiment_passed"])
        self.assertFalse(result["decision"]["boiler_counterfactual_authorized"])
        self.assertFalse(result["decision"]["production_correction_authorized"])

    def test_predeclared_predicates_support_only_the_later_boiler_counterfactual(self):
        result = native.analyze(_simulated_supported_return())
        self.assertEqual(result["classification"]["verdict"], "ASSIGNMENT_ENVELOPE_SUPPORTED")
        self.assertTrue(result["decision"]["native_experiment_passed"])
        self.assertTrue(result["decision"]["boiler_counterfactual_authorized"])
        self.assertFalse(result["decision"]["production_correction_authorized"])

        mutated = deepcopy(result["classification"]["observations"])
        mutated["A"]["task"]["finish"] = mutated["A"]["union_prediction"]["finish"]
        classified = native.classify(mutated)
        self.assertNotEqual(classified["verdict"], "ASSIGNMENT_ENVELOPE_SUPPORTED")

    def test_output_aliases_are_refused_and_separate_output_is_atomic(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "return.xml"
            source.write_bytes(_simulated_supported_return())
            before = source.read_bytes()
            symlink = root / "symlink.xml"
            symlink.symlink_to(source)
            hardlink = root / "hard.xml"
            os.link(source, hardlink)
            nested = root / "nested"
            nested.mkdir()
            for output in (source, nested / ".." / source.name, symlink, hardlink):
                with self.subTest(output=output):
                    with self.assertRaisesRegex(native.NativeEvidenceError, "separate"):
                        native.write_output_safely(output, "{}\n", {"native_return": source})
                    self.assertEqual(source.read_bytes(), before)
            output = root / "result.json"
            output.write_text("old", encoding="utf-8")
            native.write_output_safely(output, "{}\n", {"native_return": source})
            self.assertEqual(output.read_text(encoding="utf-8"), "{}\n")
            self.assertEqual(source.read_bytes(), before)

    @unittest.skipUnless(
        NATIVE_RETURN or REQUIRE_NATIVE_RETURN,
        "set STO_RC01_ASSIGNMENT_NATIVE_RETURN to analyze the Microsoft Project return",
    )
    def test_external_native_return_obeys_the_predeclared_contract(self):
        self.assertTrue(
            NATIVE_RETURN,
            "STO_REQUIRE_RC01_ASSIGNMENT_NATIVE_RETURN=1 requires "
            "STO_RC01_ASSIGNMENT_NATIVE_RETURN",
        )
        path = Path(NATIVE_RETURN or "")
        before = path.read_bytes()
        result = native.analyze(before)
        self.assertEqual(path.read_bytes(), before)
        self.assertNotEqual(
            result["classification"]["verdict"],
            "NOT_RUN_UNRECALCULATED_INPUT",
        )
        self.assertFalse(result["decision"]["production_correction_authorized"])


if __name__ == "__main__":
    unittest.main()
