"""RC03 exact BOILER production check and immutable source publication."""
from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import timedelta
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock
from xml.etree import ElementTree as ET

from scripts.evidence import p1_g2_post_rc02_review as safe
from scripts.evidence import p1_g2_rc03_production_verification as verification
from scripts.evidence import p1_g2_baseline_diagnostics as baseline
from scripts.evidence import p1_g2_rc02_boiler_counterfactual as keys
from sto.core.engine.plan import build_plan
from sto.core.model.entities import Duration
from sto.core.model.enums import RelationshipType
from sto.legacy import MSPDI_NAMESPACE


RESULT = (Path(__file__).resolve().parents[1] / "docs/evidence" /
          "p1-g2-rc03-elapsed-float-production-2026-09-28.json")


class Rc03ProductionEvidenceTests(unittest.TestCase):
    def test_committed_record_leaves_controlled_gate_open(self):
        record = json.loads(RESULT.read_bytes())
        self.assertEqual(record["after"]["keys"], [])
        self.assertEqual(record["movement"]["new_keys"], [])
        self.assertEqual(record["movement"]["worsened_keys"], [])
        self.assertEqual(record["projection"]["coordinates_before_and_after_sha256"],
                         verification.COORDINATES_SHA)
        self.assertEqual(record["eligibility"]["elapsed_float_leaves"],
                         ["L0407", "L0411"])
        self.assertEqual(record["validator"]["violations"], [])
        self.assertTrue(record["decision"]["p1_g2_met"])
        self.assertEqual(record["controlled_uid227"]["classifications"],
                         {"UNCHANGED": 4016, "ENGINE_NATIVE_AGREEMENT": 43,
                          "EXPLICIT_EXCLUSION": 81})
        self.assertEqual(hashlib.sha256(verification.PR65_RECORD.read_bytes()).hexdigest(),
                         verification.PR65_SHA)

    def test_source_aliases_refused_and_bytes_unchanged(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            source = folder / "baseline.xml"
            source.write_bytes(b"source byte identity")
            native = folder / "native.xml"
            native.write_bytes(b"native byte identity")
            (folder / "subdir").mkdir()
            symlink = folder / "symlink.xml"
            symlink.symlink_to(source)
            hardlink = folder / "hardlink.xml"
            os.link(source, hardlink)
            before = hashlib.sha256(source.read_bytes()).hexdigest()
            for alias in (source, folder / "subdir" / ".." / "baseline.xml",
                          symlink, hardlink, verification.PR65_RECORD, native):
                with self.subTest(alias=alias):
                    with self.assertRaisesRegex(safe.EvidenceError, "aliases"):
                        safe.refuse_output_alias(alias, verification.protected(source, native))
                    self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), before)
                    self.assertEqual(native.read_bytes(), b"native byte identity")

    def test_atomic_candidate_replacement_preserves_source(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            source = folder / "baseline.xml"
            source.write_bytes(b"source byte identity")
            native = folder / "native.xml"
            native.write_bytes(b"native byte identity")
            candidate = folder / "candidate.json"
            candidate.write_bytes(b"old candidate")
            seen = []
            real_replace = os.replace

            def replace(temporary, destination):
                seen.append((Path(temporary).read_bytes(), candidate.read_bytes()))
                real_replace(temporary, destination)

            with mock.patch.object(safe.os, "replace", side_effect=replace):
                safe.write_output_safely(candidate, "new candidate\n",
                                         verification.protected(source, native))
            self.assertEqual(seen, [(b"new candidate\n", b"old candidate")])
            self.assertEqual(candidate.read_bytes(), b"new candidate\n")
            self.assertEqual(source.read_bytes(), b"source byte identity")
            self.assertEqual(native.read_bytes(), b"native byte identity")

    def test_wrong_source_refuses_before_calculation(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "wrong.xml"
            source.write_bytes(b"not the controlled baseline")
            with self.assertRaisesRegex(verification.VerificationError, "identity differs"):
                verification.build_record(source, source)
            self.assertEqual(source.read_bytes(), b"not the controlled baseline")

    def test_required_boiler_exact_three_to_zero_and_no_date_movement(self):
        path = os.environ.get("STO_RC03_PRODUCTION_BOILER")
        native_path = os.environ.get("STO_RC03_CONTROLLED_NATIVE")
        if not path or not native_path:
            if os.environ.get("STO_REQUIRE_RC03_PRODUCTION") == "1":
                self.fail("STO_RC03_PRODUCTION_BOILER and STO_RC03_CONTROLLED_NATIVE must supply exact sources")
            self.skipTest("external BOILER/native pair not supplied")
        source = Path(path)
        native = Path(native_path)
        before = source.read_bytes()
        returned = native.read_bytes()
        record = verification.build_record(source, native)
        self.assertEqual((json.dumps(record, sort_keys=True, indent=2) + "\n").encode(),
                         RESULT.read_bytes())
        self.assertEqual(source.read_bytes(), before)
        self.assertEqual(native.read_bytes(), returned)

    def test_measured_root_refuses_outside_shapes(self):
        path = os.environ.get("STO_RC03_PRODUCTION_BOILER")
        if not path:
            if os.environ.get("STO_REQUIRE_RC03_PRODUCTION") == "1":
                self.fail("STO_RC03_PRODUCTION_BOILER required for eligibility mutations")
            self.skipTest("external BOILER baseline not supplied")
        schedule = baseline._load(Path(path).read_bytes())
        _, uid_by_leaf, _ = keys._leaf_maps(schedule)
        root = uid_by_leaf["L0407"]
        activity = next(row for row in schedule.activities if row.uid == root)
        assignment = next(row for row in schedule.assignments if row.activity_uid == root)
        incoming = next(row for row in schedule.relationships if row.successor_uid == root)
        outgoing = next(row for row in schedule.relationships if row.predecessor_uid == root)

        def basis(changed):
            start = changed.project.start
            plan = build_plan(changed, (start - timedelta(days=90),
                                        start + timedelta(days=365)))
            planned = plan.network.activity_by_uid().get(root)
            return "excluded" if planned is None else planned.float_basis

        self.assertEqual(basis(schedule), "elapsed")
        for changed in (
            replace(activity, actual_start=schedule.project.start),
            replace(activity, manual=True),
            replace(activity, calendar_uid=schedule.project.default_calendar_uid),
            replace(activity, planned_duration=replace(activity.planned_duration,
                                                       seconds=activity.planned_duration.seconds - 3600)),
            replace(activity, remaining_duration=replace(activity.remaining_duration,
                                                         elapsed=False)),
            replace(activity, source_fields={**activity.source_fields,
                                            "ignore_resource_calendar_source": "1"}),
        ):
            with self.subTest(activity=changed.uid, manual=changed.manual,
                              duration=changed.planned_duration.seconds,
                              source_fields=changed.source_fields):
                amended = replace(schedule, activities=tuple(
                    changed if row.uid == root else row for row in schedule.activities))
                self.assertNotEqual(basis(amended), "elapsed")
        for changed in (
            replace(assignment, units=replace(assignment.units, budgeted_permille=2000)),
            replace(assignment, source_fields={**assignment.source_fields,
                                               "units_lexeme_source": "1.00001"}),
            replace(assignment, source_fields={**assignment.source_fields,
                "units_lexeme_source": "1.00000000000000000000000000001"}),
            replace(assignment, source_fields={**assignment.source_fields,
                                               "work_contour_source": "1"}),
            replace(assignment, source_fields={**assignment.source_fields,
                                               "percent_work_complete_source": "1"}),
            replace(assignment, timephased_ref="synthetic-timephased"),
            replace(assignment, curve_uid=assignment.uid),
            replace(assignment, source_fields={key: value
                for key, value in assignment.source_fields.items()
                if key != "units_lexeme_source"}),
            replace(assignment, source_fields={key: value
                for key, value in assignment.source_fields.items()
                if key != "actual_work_source_present"}),
            replace(assignment, source_fields={**assignment.source_fields,
                                               "delay_tenths_minutes_source": "10"}),
            replace(assignment, source_fields={**assignment.source_fields,
                                               "leveling_delay_tenths_minutes_source": "10"}),
        ):
            with self.subTest(assignment_units=changed.units.budgeted_permille,
                              source_fields=changed.source_fields):
                amended = replace(schedule, assignments=tuple(
                    changed if row.uid == assignment.uid else row
                    for row in schedule.assignments))
                self.assertEqual(basis(amended), "working")

        for marker in (
            "delay_ambiguous_source", "leveling_delay_ambiguous_source",
            "units_ambiguous_source", "work_ambiguous_source",
            "remaining_work_ambiguous_source", "actual_work_ambiguous_source",
            "percent_work_complete_ambiguous_source", "work_contour_ambiguous_source",
            "work_unsupported_source", "remaining_work_unsupported_source",
            "actual_work_unsupported_source",
        ):
            with self.subTest(marker=marker):
                changed = replace(assignment, source_fields={
                    **assignment.source_fields, marker: "1"})
                amended = replace(schedule, assignments=tuple(
                    changed if row.uid == assignment.uid else row
                    for row in schedule.assignments))
                self.assertEqual(basis(amended), "working")
        for changed in (replace(incoming, type=RelationshipType.SS),
                        replace(incoming, lag=Duration(seconds=60)),
                        replace(incoming, cross_project=True),
                        replace(outgoing, type=RelationshipType.FF)):
            with self.subTest(relationship=changed.type, lag=changed.lag):
                amended = replace(schedule, relationships=tuple(
                    changed if row.uid == changed.uid else row
                    for row in schedule.relationships))
                self.assertEqual(basis(amended), "working")


    def test_xml_import_does_not_promote_unmeasured_source_fields(self):
        path = os.environ.get("STO_RC03_PRODUCTION_BOILER")
        if not path:
            if os.environ.get("STO_REQUIRE_RC03_PRODUCTION") == "1":
                self.fail("STO_RC03_PRODUCTION_BOILER required for source guard test")
            self.skipTest("external BOILER baseline not supplied")
        original = Path(path).read_bytes()
        schedule = baseline._load(original)
        root_uid = keys._leaf_maps(schedule)[1]["L0407"]
        root_task = next(row for row in schedule.activities if row.uid == root_uid)
        assignment = next(row for row in schedule.assignments
                          if row.activity_uid == root_uid)
        resource = next(row for row in schedule.resources
                        if row.uid == assignment.resource_uid)
        task_code = baseline._source_uid(root_task)
        assignment_code = baseline._source_uid(assignment)
        resource_code = baseline._source_uid(resource)
        ns = f"{{{MSPDI_NAMESPACE}}}"

        def source_node(tree, group, kind, code):
            return next(row for row in tree.findall(f"{ns}{group}/{ns}{kind}")
                        if row.findtext(f"{ns}UID") == code)

        for label, group, kind, code, field, value in (
            ("effort driven", "Tasks", "Task", task_code, "EffortDriven", "1"),
            ("task leveling", "Tasks", "Task", task_code, "LevelingDelay", "60"),
            ("generic resource", "Resources", "Resource", resource_code, "IsGeneric", "1"),
            ("unreadable actual work", "Tasks", "Task", task_code, "ActualWork", "P1M"),
            ("unreadable actual duration", "Tasks", "Task", task_code, "ActualDuration", "P1M"),
            ("unreadable remaining work", "Tasks", "Task", task_code, "RemainingWork", "P1M"),
            ("rounded source units", "Assignments", "Assignment", assignment_code,
             "Units", "1.00000000000000000000000000001"),
            ("changed timephased work", "Assignments", "Assignment",
             assignment_code, "TimephasedData/Value", "PT23H0M0S"),
        ):
            with self.subTest(source=label):
                tree = ET.fromstring(original)
                node = source_node(tree, group, kind, code)
                target = node.find("/".join(f"{ns}{part}"
                                            for part in field.split("/")))
                self.assertIsNotNone(target)
                target.text = value
                changed = baseline._load(ET.tostring(tree, encoding="utf-8"))
                task = next(row for row in changed.activities
                            if baseline._source_uid(row) == task_code)
                start = changed.project.start
                plan = build_plan(changed, (start - timedelta(days=90),
                                            start + timedelta(days=365)))
                planned = plan.network.activity_by_uid().get(task.uid)
                self.assertEqual(planned.float_basis if planned else "excluded",
                                 "working")
        self.assertEqual(Path(path).read_bytes(), original)

if __name__ == "__main__":
    unittest.main()
