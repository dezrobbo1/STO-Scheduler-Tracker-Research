"""Tests for the independently recomputed post-RC02 P1-G2 review."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from scripts.evidence import p1_g2_post_rc02_review as review

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "docs/evidence/p1-g2-post-rc02-review-2026-09-25.json"
HISTORICAL_SHA256 = "2408fc99f282e9c600d3821b3c926f7deafa8c05044c7fec9a5f08b2b656bf63"
POST_RC02_SHA256 = "6985456f4da7d758e828a744fac426a05ea864daa264a2f5e3839078e2b29694"


def _committed() -> dict[str, object]:
    return json.loads(EVIDENCE.read_bytes())


class PostRc02ReviewTests(unittest.TestCase):
    def test_committed_record_is_canonical_and_carries_recomputation(self):
        record = _committed()
        self.assertEqual(record["schema"], "sto-p1-g2-post-rc02-review-v2")
        self.assertEqual(EVIDENCE.read_bytes(), review.serialize(record).encode("utf-8"))
        current = record["current_recomputation"]
        self.assertEqual(current["method"], "CURRENT_PRODUCTION_SOURCE_COORDINATE_REPLAY")
        self.assertEqual(len(current["mismatches"]), 147)

    def test_current_inventory_and_roots_are_recomputed(self):
        record = _committed()
        current = record["current_inventory"]
        self.assertEqual(current["slots"], 147)
        self.assertEqual(current["leaves"], 39)
        self.assertEqual(current["by_group"], {"G2-RC01": 144, "G2-RC03": 3})
        self.assertEqual(
            current["by_role"],
            {"DEPENDENT": 120, "DERIVED": 2, "FIRST_DIVERGENCE": 25},
        )
        self.assertEqual(
            record["rc01_review"]["root_leaf_ids"],
            ["L0070", "L0075", "L0080", "L0083", "L0084", "L0114",
             "L0127", "L0148", "L0157", "L0190"],
        )
        self.assertEqual(record["rc03_review"]["root_leaf_ids"], ["L0407", "L0411"])
        self.assertEqual(record["rc04_review"]["current_slots"], 0)

    def test_historical_labels_are_not_inputs_to_current_classification(self):
        historical, post = review.load_inputs()
        recomputation = deepcopy(_committed()["current_recomputation"])
        mutated = deepcopy(post)
        for row in mutated["inventory"]["remaining_mismatches"]:
            row["diagnostic_group"] = "HISTORICAL_LABEL_MUST_NOT_DRIVE_RESULT"
            row["dependency_role"] = "FIRST_DIVERGENCE"
        record = review.review_documents(historical, mutated, recomputation)
        self.assertEqual(record["current_inventory"]["by_group"], {"G2-RC01": 144, "G2-RC03": 3})
        self.assertEqual(record["current_inventory"]["by_role"]["FIRST_DIVERGENCE"], 25)

    def test_current_paths_not_historical_paths_reclassify_old_compound_slot(self):
        record = _committed()
        slot = next(
            row for row in record["current_recomputation"]["mismatches"]
            if row["leaf_id"] == "L0084" and row["field"] == "total_float"
        )
        self.assertEqual(slot["diagnostic_group"], "G2-RC01")
        self.assertEqual(slot["dependency_role"], "DEPENDENT")
        self.assertEqual(slot["dependency_paths"], [["L0080", "L0084"], ["L0084"]])

    def test_every_recomputed_slot_reconciles_once_with_current_production_record(self):
        historical, post = review.load_inputs()
        recomputation = deepcopy(_committed()["current_recomputation"])
        record = review.review_documents(historical, post, recomputation)
        post_keys = {
            (row["leaf_id"], row["field"], row["sto_minus_source_seconds"])
            for row in post["inventory"]["remaining_mismatches"]
        }
        current_keys = {
            (row["leaf_id"], row["field"], row["sto_minus_source_seconds"])
            for row in record["current_recomputation"]["mismatches"]
        }
        self.assertEqual(len(current_keys), 147)
        self.assertEqual(current_keys, post_keys)

        duplicate = deepcopy(recomputation)
        duplicate["mismatches"].append(deepcopy(duplicate["mismatches"][0]))
        with self.assertRaisesRegex(review.EvidenceError, "147 unique"):
            review.review_documents(historical, post, duplicate)

    def test_current_replay_change_is_not_hidden_by_surviving_mismatch_key(self):
        historical, post = review.load_inputs()
        recomputation = deepcopy(_committed()["current_recomputation"])
        slot = next(row for row in recomputation["mismatches"] if row["dependency_role"] == "DEPENDENT")
        slot["dependency_role"] = "FIRST_DIVERGENCE"
        slot["dependency_paths"] = [[slot["leaf_id"]]]
        record = review.review_documents(historical, post, recomputation)
        self.assertNotEqual(record["current_inventory"]["by_role"], _committed()["current_inventory"]["by_role"])

    def test_historical_evidence_bytes_are_unchanged(self):
        self.assertEqual(hashlib.sha256(review.HISTORICAL_PATH.read_bytes()).hexdigest(), HISTORICAL_SHA256)
        self.assertEqual(hashlib.sha256(review.POST_RC02_PATH.read_bytes()).hexdigest(), POST_RC02_SHA256)

    def test_output_aliases_are_refused_and_sources_remain_immutable(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            historical = root / "historical.json"
            post = root / "post.json"
            baseline = root / "baseline.xml"
            historical.write_text("historical", encoding="utf-8")
            post.write_text("post", encoding="utf-8")
            baseline.write_text("baseline", encoding="utf-8")
            before = {path: path.read_bytes() for path in (historical, post, baseline)}
            nested = root / "nested"
            nested.mkdir()
            symlink = root / "historical-symlink.json"
            symlink.symlink_to(historical)
            hardlink = root / "post-hardlink.json"
            os.link(post, hardlink)
            aliases = (
                historical,
                nested / ".." / "historical.json",
                symlink,
                hardlink,
            )
            for destination in aliases:
                with self.subTest(destination=destination):
                    with self.assertRaisesRegex(review.EvidenceError, "aliases"):
                        review.write_output_safely(
                            destination,
                            "candidate\n",
                            {"historical": historical, "post_rc02": post, "baseline": baseline},
                        )
                    for path, payload in before.items():
                        self.assertEqual(path.read_bytes(), payload)

    def test_separate_output_replaces_prior_candidate_atomically(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.json"
            source.write_text("source", encoding="utf-8")
            output = root / "candidate.json"
            output.write_text("old candidate", encoding="utf-8")
            real_replace = os.replace
            observed: list[tuple[Path, Path]] = []

            def replace(source_path, destination_path):
                temporary = Path(source_path)
                destination = Path(destination_path)
                self.assertEqual(temporary.parent, destination.parent)
                self.assertEqual(destination.read_text(encoding="utf-8"), "old candidate")
                self.assertEqual(temporary.read_text(encoding="utf-8"), "new candidate\n")
                observed.append((temporary, destination))
                real_replace(source_path, destination_path)

            with mock.patch.object(review.os, "replace", side_effect=replace):
                review.write_output_safely(output, "new candidate\n", {"source": source})
            self.assertEqual(len(observed), 1)
            self.assertEqual(output.read_text(encoding="utf-8"), "new candidate\n")
            self.assertEqual(source.read_text(encoding="utf-8"), "source")

    @unittest.skipUnless(os.environ.get("STO_BOILER_BEFORE"), "external BOILER baseline not supplied")
    def test_external_current_production_recomputation_matches_committed_record(self):
        source = Path(os.environ["STO_BOILER_BEFORE"])
        before = source.read_bytes()
        record = review.build_record(source)
        self.assertEqual(review.serialize(record).encode("utf-8"), EVIDENCE.read_bytes())
        self.assertEqual(source.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
