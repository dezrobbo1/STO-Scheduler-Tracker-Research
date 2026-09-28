"""Predeclared V2 native matrix, normalization boundary and fail-closed tests."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET

from scripts.evidence import p1_g2_rc01_assignment_native_v2 as native
from scripts.evidence import p1_g2_rc01_assignment_native_v2_generate as generator
from scripts.evidence import p1_g2_rc01_assignment_native as old_native

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/P1-G2-RC01-ASSIGNMENT-ENVELOPE-NATIVE-MATRIX-V2.xml"
RECEIPT = ROOT / "docs/evidence/p1-g2-rc01-native-v1-invalid-return-2026-09-28.json"
EXTERNAL_V1 = os.getenv("STO_RC01_V1_NATIVE_RETURN")
NS = {"p": generator.URI}


def get(root: ET.Element, container: str, uid: int) -> ET.Element:
    rows = root.findall(f"p:{container}/*", NS)
    return next(row for row in rows if row.findtext("p:UID", namespaces=NS) == str(uid))


def set_field(row: ET.Element, field: str, value: str) -> None:
    tag = row.find(f"p:{field}", NS)
    assert tag is not None
    tag.text = value


def encode(root: ET.Element) -> bytes:
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def synthetic_v1_style_save() -> bytes:
    """Synthetic unit-test return; never claimed as Project evidence."""
    root = ET.fromstring(generator.build_fixture())
    set_field(root, "BuildNumber", "16.0.99999.99999")
    set_field(root, "GUID", "04C578DF-D5BA-F111-9818-902E162C1984")
    set_field(root, "FinishDate", "2026-10-12T17:00:00")
    for uid in range(2, 6):
        set_field(get(root, "Calendars", uid), "Name", "Unassigned")
    for uid, spec in generator.RESOURCES.items():
        set_field(get(root, "Resources", uid), "GUID",
                  generator.CALENDARS[spec["calendar"]]["guid"])
    for case, spec in generator.TASKS.items():
        task = get(root, "Tasks", spec["uid"])
        generator.add(task, "CalendarUID", "-1")
        set_field(task, "LevelingDelayFormat", "8")
        if case in "AB":
            for field in ("Duration", "RemainingDuration"):
                set_field(task, field, "PT8H0M0S")
            for field in ("Finish", "EarlyFinish", "LateFinish"):
                set_field(task, field, "2026-10-12T17:00:00")
    for uid in (102, 103):
        assignment = get(root, "Assignments", uid)
        set_field(assignment, "Start", "2026-10-12T13:00:00")
        set_field(assignment, "Finish", "2026-10-12T17:00:00")
    return encode(root)


class Rc01V2Tests(unittest.TestCase):
    def test_exact_generator_and_import_boundary(self):
        payload = generator.build_fixture()
        self.assertEqual(FIXTURE.read_bytes(), payload)
        self.assertEqual(payload, generator.build_fixture())
        self.assertEqual(len(payload), generator.INPUT_BYTES)
        self.assertEqual(hashlib.sha256(payload).hexdigest(), generator.INPUT_SHA256)
        imported = generator.canonical_import_contract(payload)
        self.assertEqual(imported["activity_count"], 4)
        self.assertEqual(imported["assignment_count"], 7)
        self.assertTrue(imported["resource_calendar_identity_preserved"])
        self.assertTrue(imported["assignment_work_and_units_preserved"])

    def test_standalone_generator_command_emits_pinned_bytes(self):
        import subprocess
        import sys

        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "input.xml"
            process = subprocess.run(
                [sys.executable, str(ROOT / "scripts/evidence/p1_g2_rc01_assignment_native_v2_generate.py"),
                 str(target)], cwd=ROOT, capture_output=True, text=True,
            )
            self.assertEqual(process.returncode, 0, process.stderr)
            self.assertEqual(target.read_bytes(), FIXTURE.read_bytes())

    def test_exact_four_cases_and_order_twin(self):
        parsed = native.parse_and_validate(generator.build_fixture())
        self.assertEqual(parsed["assignment_order"], list(generator.ASSIGNMENT_ORDER))
        self.assertEqual([row["role"] for row in parsed["assignments"].values()],
                         ["AM", "PM", "PM", "AM", "AM", "AM", "AM"])
        self.assertEqual([parsed["resources"][uid]["calendar_uid"] for uid in (1, 2, 3, 4)],
                         [2, 3, 4, 5])
        self.assertEqual(parsed["tasks"]["A"]["duration"], "PT4H0M0S")
        self.assertEqual(parsed["tasks"]["D"]["duration"], "PT4H0M0S")

    def test_unrecalculated_input_stops_without_authorization(self):
        result = native.analyze(generator.build_fixture())
        self.assertEqual(result["classification"]["verdict"],
                         "V2_NOT_RUN_UNRECALCULATED_INPUT")
        self.assertFalse(result["decision"]["boiler_counterfactual_authorized"])
        self.assertFalse(result["decision"]["production_correction_authorized"])

    def test_v1_style_normalization_allowed_only_for_declared_fields(self):
        payload = synthetic_v1_style_save()
        self.assertEqual(native.analyze(payload)["classification"]["verdict"],
                         "V2_ASSIGNMENT_ENVELOPE_SUPPORTED")
        self.assertFalse(native.analyze(payload)["decision"]["production_correction_authorized"])
        # The old V1 contract rejected the same changes even when input name was V1.
        with self.assertRaisesRegex(old_native.NativeEvidenceError, "project input changed: Name"):
            old_native.parse_and_validate(payload)

    def test_mutations_to_semantic_inputs_fail_closed(self):
        changes = (
            ("Tasks", 1, "UID", "55"),
            ("Tasks", 1, "GUID", "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"),
            ("Tasks", 1, "Type", "1"),
            ("Tasks", 1, "EffortDriven", "1"),
            ("Tasks", 1, "IgnoreResourceCalendar", "1"),
            ("Tasks", 1, "Start", "2026-10-12T09:00:00"),
            ("Tasks", 1, "Manual", "1"),
            ("Tasks", 1, "PercentComplete", "1"),
            ("Tasks", 1, "ConstraintType", "2"),
            ("Tasks", 1, "LevelAssignments", "1"),
            ("Tasks", 1, "ActualWork", "PT1H0M0S"),
            ("Resources", 1, "UID", "55"),
            ("Resources", 1, "CalendarUID", "3"),
            ("Resources", 1, "CanLevel", "1"),
            ("Resources", 1, "GUID", "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"),
            ("Calendars", 2, "UID", "55"),
            ("Calendars", 2, "GUID", "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"),
            ("Assignments", 101, "UID", "999"),
            ("Assignments", 101, "GUID", "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"),
            ("Assignments", 101, "TaskUID", "2"),
            ("Assignments", 101, "ResourceUID", "2"),
            ("Assignments", 101, "Work", "PT5H0M0S"),
            ("Assignments", 101, "Units", "0.5"),
        )
        for container, uid, field, value in changes:
            with self.subTest(container=container, uid=uid, field=field):
                root = ET.fromstring(synthetic_v1_style_save())
                set_field(get(root, container, uid), field, value)
                result = native.analyze(encode(root))
                self.assertEqual(result["classification"]["verdict"],
                                 "V2_INPUT_CONTRACT_VIOLATED")
                self.assertFalse(result["decision"]["boiler_counterfactual_authorized"])

    def test_input_failure_precedes_unreadable_native_output(self):
        root = ET.fromstring(synthetic_v1_style_save())
        set_field(get(root, "Tasks", 1), "Finish", "not-a-native-date")
        set_field(get(root, "Assignments", 107), "Work", "PT5H0M0S")
        result = native.analyze(encode(root))
        self.assertEqual(result["classification"]["verdict"], "V2_INPUT_CONTRACT_VIOLATED")
        self.assertIn("assignment 107.Work", result["classification"]["validation_failure"])

    def test_calendar_intervals_order_topology_and_new_options_fail_closed(self):
        for name in ("calendar", "assignment order", "topology", "option"):
            with self.subTest(name=name):
                root = ET.fromstring(synthetic_v1_style_save())
                if name == "calendar":
                    interval = get(root, "Calendars", 2).find(
                        "p:WeekDays/p:WeekDay/p:WorkingTimes/p:WorkingTime/p:ToTime", NS)
                    assert interval is not None
                    interval.text = "12:30:00"
                elif name == "assignment order":
                    assignments = root.find("p:Assignments", NS)
                    assert assignments is not None
                    first = list(assignments)[0]
                    assignments.remove(first)
                    assignments.insert(1, first)
                elif name == "topology":
                    link = ET.SubElement(get(root, "Tasks", 1), generator.q("PredecessorLink"))
                    generator.add(link, "PredecessorUID", "4")
                else:
                    generator.add(root, "HonorConstraints", "1")
                self.assertEqual(native.analyze(encode(root))["classification"]["verdict"],
                                 "V2_INPUT_CONTRACT_VIOLATED")

    def test_duration_can_recalculate_but_unexplained_duration_is_inconclusive(self):
        root = ET.fromstring(synthetic_v1_style_save())
        set_field(get(root, "Tasks", 1), "Duration", "PT7H0M0S")
        result = native.analyze(encode(root))
        self.assertEqual(result["classification"]["verdict"],
                         "V2_NATIVE_RESULT_INCONCLUSIVE")
        self.assertFalse(result["decision"]["boiler_counterfactual_authorized"])

    def test_invalid_control_and_order_effect_are_inconclusive(self):
        for name, uid, field, value in (
            ("control", 106, "Finish", "2026-10-12T11:00:00"),
            ("order twin", 103, "Start", "2026-10-12T14:00:00"),
        ):
            with self.subTest(name=name):
                root = ET.fromstring(synthetic_v1_style_save())
                set_field(get(root, "Assignments", uid), field, value)
                self.assertEqual(native.analyze(encode(root))["classification"]["verdict"],
                                 "V2_NATIVE_RESULT_INCONCLUSIVE")

        root = ET.fromstring(synthetic_v1_style_save())
        set_field(get(root, "Tasks", 1), "EarlyFinish", "2026-10-12T12:00:00")
        self.assertEqual(native.analyze(encode(root))["classification"]["verdict"],
                         "V2_NATIVE_RESULT_INCONCLUSIVE")

    def test_exact_coherent_union_signature_rejects_envelope(self):
        root = ET.fromstring(synthetic_v1_style_save())
        for uid in (1, 2):
            task = get(root, "Tasks", uid)
            for field in ("Duration", "RemainingDuration"):
                set_field(task, field, "PT4H0M0S")
            for field in ("Finish", "EarlyFinish"):
                set_field(task, field, "2026-10-12T12:00:00")
        result = native.analyze(encode(root))
        self.assertEqual(result["classification"]["verdict"],
                         "V2_ASSIGNMENT_ENVELOPE_REJECTED")
        self.assertFalse(result["decision"]["boiler_counterfactual_authorized"])

    def test_unobserved_calendar_and_option_changes_fail_closed(self):
        root = ET.fromstring(synthetic_v1_style_save())
        generator.add(root, "Autolink", "1")
        self.assertEqual(native.analyze(encode(root))["classification"]["verdict"],
                         "V2_INPUT_CONTRACT_VIOLATED")

    def test_added_actual_overtime_cannot_fake_no_progress(self):
        root = ET.fromstring(synthetic_v1_style_save())
        generator.add(get(root, "Tasks", 1), "ActualOvertimeWork", "PT1H0M0S")
        result = native.analyze(encode(root))
        self.assertEqual(result["classification"]["verdict"],
                         "V2_INPUT_CONTRACT_VIOLATED")
        self.assertFalse(result["decision"]["boiler_counterfactual_authorized"])
        root = ET.fromstring(synthetic_v1_style_save())
        sunday = get(root, "Calendars", 1).find("p:WeekDays/p:WeekDay", NS)
        assert sunday is not None
        set_field(sunday, "DayWorking", "2")
        self.assertEqual(native.analyze(encode(root))["classification"]["verdict"],
                         "V2_INPUT_CONTRACT_VIOLATED")

    def test_append_only_receipt_has_exact_return_identity(self):
        receipt = json.loads(RECEIPT.read_text())
        self.assertEqual(receipt["classification"],
                         "NATIVE_RETURN_INPUT_NORMALIZED_BEYOND_V1_CONTRACT")
        self.assertEqual(receipt["native_return"]["sha256"],
                         "5c190a0d4f41068559f37db845ec0d17a265dea89442453898d6daa3bc2b28ab")
        self.assertEqual(receipt["native_return"]["first_validator_error"],
                         "project input changed: GUID")
        self.assertFalse(receipt["decision"]["boiler_counterfactual_authorized"])

    @unittest.skipUnless(EXTERNAL_V1, "external immutable V1 return not supplied")
    def test_optional_external_return_matches_receipt_without_writing(self):
        payload = Path(EXTERNAL_V1 or "").read_bytes()
        receipt = json.loads(RECEIPT.read_text())
        self.assertEqual(len(payload), receipt["native_return"]["bytes"])
        self.assertEqual(hashlib.sha256(payload).hexdigest(), receipt["native_return"]["sha256"])
        with self.assertRaisesRegex(old_native.NativeEvidenceError, "project input changed: GUID"):
            old_native.parse_and_validate(payload)
        # V1 is not V2 evidence. Rewrite identity IN MEMORY solely to check
        # that the V2 parser recognizes every observed V1 normalization.
        root = ET.fromstring(payload)
        set_field(root, "Name", generator.PROJECT_NAME)
        set_field(root, "Title", generator.EXPERIMENT_ID)
        set_field(get(root, "Tasks", 0), "Name", generator.EXPERIMENT_ID)
        parsed = native.parse_and_validate(encode(root))
        self.assertEqual(set(parsed["tasks"]), {"A", "B", "C", "D"})

    def test_native_analyzer_safe_output_alias_and_atomic_replacement(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            source = base / "return.xml"
            source.write_bytes(synthetic_v1_style_save())
            before = source.read_bytes()
            symlink = base / "symlink.xml"
            symlink.symlink_to(source)
            hardlink = base / "hardlink.xml"
            os.link(source, hardlink)
            for candidate in (source, base / "." / source.name, symlink, hardlink):
                with self.subTest(candidate=candidate):
                    with self.assertRaises(native.NativeEvidenceError):
                        native.write_output_safely(candidate, "{}\n", {"native_return": source})
                    self.assertEqual(before, source.read_bytes())
            result = base / "analysis.json"
            result.write_text("prior candidate", encoding="utf-8")
            native.write_output_safely(result, "{}\n", {"native_return": source})
            self.assertEqual(result.read_text(), "{}\n")
            self.assertEqual(before, source.read_bytes())

    def test_cli_refuses_output_aliased_to_pinned_input(self):
        import subprocess
        import sys

        before = FIXTURE.read_bytes()
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts/evidence/p1_g2_rc01_assignment_native_v2.py"),
             str(FIXTURE), "--output", str(FIXTURE)],
            capture_output=True, text=True,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("separate", result.stderr)
        self.assertEqual(FIXTURE.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
