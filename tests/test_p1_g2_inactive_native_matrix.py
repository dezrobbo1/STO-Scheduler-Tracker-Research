"""Tests for the bounded P1-G2 RC02 inactive native matrix tooling."""
from __future__ import annotations

import tempfile
from pathlib import Path
import unittest
import xml.etree.ElementTree as ET

from scripts.evidence import p1_g2_inactive_native_matrix as matrix
from scripts.evidence import p1_g2_inactive_native_matrix_generate as generate

NS = {"p": "http://schemas.microsoft.com/project"}


def _write_fixture(path: Path) -> Path:
    path.write_bytes(generate.build_fixture())
    return path


def _mutated_fixture(verdict: str, target: Path) -> Path:
    _write_fixture(target)
    tree = ET.parse(target)
    root = tree.getroot()
    tasks = {
        task.findtext("p:Name", namespaces=NS): task
        for task in root.findall("p:Tasks/p:Task", NS)
    }

    def value(name: str, field: str) -> str:
        result = tasks[name].findtext(f"p:{field}", namespaces=NS)
        assert result is not None
        return result

    def set_value(name: str, field: str, text: str) -> None:
        node = tasks[name].find(f"p:{field}", NS)
        assert node is not None
        node.text = text

    if verdict == "splice":
        set_value("RC02-A-I-SUCC", "Start", value("RC02-A-I-PRED", "Finish"))
        set_value("RC02-B-I-SUCC", "Start", value("RC02-B-I-PRED", "Finish"))
        set_value("RC02-C-I-PRED", "FreeSlack", "100")
        set_value("RC02-C-I-PRED", "TotalSlack", "900")
    elif verdict == "drop":
        project_start = root.findtext("p:StartDate", namespaces=NS)
        assert project_start is not None
        set_value("RC02-A-I-SUCC", "Start", project_start)
        set_value("RC02-B-I-SUCC", "Start", value("RC02-B-I-OTHER", "Finish"))
        set_value("RC02-C-I-PRED", "FreeSlack", "900")
        set_value("RC02-C-I-PRED", "TotalSlack", "900")
    else:
        raise AssertionError(verdict)
    tree.write(target, encoding="utf-8", xml_declaration=True)
    return target


class Rc02NativeMatrixTests(unittest.TestCase):
    def test_generator_is_deterministic_and_matrix_is_paired(self):
        first = generate.build_fixture()
        self.assertEqual(first, generate.build_fixture())
        self.assertEqual(len(first), 48322)
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

    def test_classifier_distinguishes_direct_splice_and_drop(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for fixture_verdict, expected in (
                ("splice", "DIRECT_ZERO_LAG_FS_SPLICE_SUPPORTED"),
                ("drop", "DROP_BOTH_ENDPOINT_EDGES_SUPPORTED"),
            ):
                with self.subTest(fixture_verdict=fixture_verdict):
                    path = _mutated_fixture(fixture_verdict, root / f"{fixture_verdict}.xml")
                    _, rows = matrix.read(path)
                    self.assertEqual(matrix.classify(rows)["verdict"], expected)

    def test_mixed_observations_do_not_establish_a_rule(self):
        with tempfile.TemporaryDirectory() as directory:
            path = _mutated_fixture("splice", Path(directory) / "mixed.xml")
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
            tree.write(path, encoding="utf-8", xml_declaration=True)
            _, rows = matrix.read(path)
            self.assertEqual(
                matrix.classify(rows)["verdict"],
                "NO_SINGLE_TESTED_RULE_ESTABLISHED",
            )


if __name__ == "__main__":
    unittest.main()
