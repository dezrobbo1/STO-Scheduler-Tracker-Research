"""Tests for the bounded P1-G2 RC02 inactive native matrix tooling."""
from __future__ import annotations

from datetime import datetime
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

    def set_start(name: str, source: str, field: str = "Finish") -> None:
        coordinate = value(source, field)
        set_value(name, "Start", coordinate)
        set_value(name, "EarlyStart", coordinate)

    def slack_units(start: str, finish: str) -> str:
        seconds = (datetime.fromisoformat(finish) - datetime.fromisoformat(start)).total_seconds()
        return str(int(seconds / 6))

    # Make the inactive middle row start at its active predecessor finish, as
    # the real native return does, and give all pass-through cases a backward
    # boundary from active successor to active predecessor.
    for pair in ("A", "B", "C"):
        set_start(f"RC02-{pair}-I-MID", f"RC02-{pair}-I-PRED")
        set_value(
            f"RC02-{pair}-I-PRED", "LateFinish",
            value(f"RC02-{pair}-I-SUCC", "LateStart"),
        )

    if verdict in {"splice", "mixed"}:
        set_start("RC02-A-I-SUCC", "RC02-A-I-PRED")
        set_start("RC02-B-I-SUCC", "RC02-B-I-PRED")
        set_start("RC02-C-I-SUCC", "RC02-C-I-OTHER")
        if verdict == "splice":
            set_value(
                "RC02-C-I-PRED", "FreeSlack",
                slack_units(
                    value("RC02-C-I-PRED", "EarlyFinish"),
                    value("RC02-C-I-SUCC", "EarlyStart"),
                ),
            )
        else:
            set_value(
                "RC02-C-I-PRED", "FreeSlack",
                slack_units(
                    value("RC02-C-I-PRED", "EarlyFinish"),
                    value("RC02-C-I-MID", "EarlyStart"),
                ),
            )
        set_value("RC02-C-I-PRED", "TotalSlack", "115200")
    elif verdict == "drop":
        project_start = root.findtext("p:StartDate", namespaces=NS)
        assert project_start is not None
        set_value("RC02-A-I-SUCC", "Start", project_start)
        set_value("RC02-A-I-SUCC", "EarlyStart", project_start)
        set_start("RC02-B-I-SUCC", "RC02-B-I-OTHER")
        set_start("RC02-C-I-SUCC", "RC02-C-I-OTHER")
        set_value("RC02-C-I-PRED", "FreeSlack", "900")
        set_value("RC02-C-I-PRED", "TotalSlack", "900")
        set_value("RC02-C-I-PRED", "LateFinish", value("RC02-FINISH-DRIVER", "Finish"))
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

    def test_classifier_distinguishes_three_supported_shapes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for fixture_verdict, expected in (
                ("splice", "DIRECT_ZERO_LAG_FS_SPLICE_SUPPORTED"),
                ("mixed", "ZERO_DURATION_DATE_PASSTHROUGH_WITH_INACTIVE_EDGE_FREE_SLACK"),
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
                "free_slack_semantic": "ORIGINAL_INACTIVE_EDGE_BOUND_SUPPORTED",
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


if __name__ == "__main__":
    unittest.main()
