"""The pinned conformance corpus is exactly what was pinned, and it is what the roadmap counts.

Enforces ``PR-conformance-suite``: engine claims are bounded by the semantic
conformance corpus, and the corpus and its executable subset are counted in the
roadmap's ``conformance`` block, never in prose. That rule is only worth having
if the corpus cannot drift, so this module checks three things:

1. Every file under ``src/sto/conformance/corpus`` matches its SHA-256 in
   ``MANIFEST.json`` -- none missing, none changed, none added unpinned -- and
   a tampered case refuses to load.
2. The subset counts the roadmap carries are what the cases themselves say,
   derived from their own fields rather than counted by hand.
3. When a clone of ``dezrobbo1/PM-Software`` is reachable, the copy is
   byte-identical to the pinned commit *in that clone's history*, whatever its
   working tree is at. ``STO_PM_SOFTWARE_DIR`` names the clone;
   ``STO_REQUIRE_PM=1`` turns its absence into a failure.
"""

from __future__ import annotations

import csv
import hashlib
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from sto import conformance
from sto.conformance import CorpusIntegrityError, Manifest
from sto.roadmap import load as load_roadmap

REPO_ROOT = Path(__file__).resolve().parent.parent
PM_DIR = Path(os.environ.get("STO_PM_SOFTWARE_DIR", "/home/dez/PM-Software"))
REQUIRE_PM = os.environ.get("STO_REQUIRE_PM") == "1"
if REQUIRE_PM and not (PM_DIR / ".git").exists():
    raise RuntimeError(f"STO_REQUIRE_PM=1 but {PM_DIR} is not a git clone")


class ManifestTests(unittest.TestCase):
    def setUp(self):
        self.manifest = conformance.load_manifest()

    def test_the_copy_is_exactly_what_was_pinned(self):
        self.assertEqual(conformance.verify(), [])

    def test_the_manifest_names_its_source(self):
        self.assertEqual(self.manifest.repository, "dezrobbo1/PM-Software")
        self.assertRegex(self.manifest.commit, r"^[0-9a-f]{40}$")
        self.assertEqual(self.manifest.upstream_path, "benchmarks/semantic")

    def test_every_case_file_declares_its_own_id(self):
        for case_id in conformance.case_ids():
            with self.subTest(case_id):
                case = conformance.load_case(case_id)
                self.assertEqual(case["case_id"].lower(), case_id)

    def test_the_catalogue_and_the_case_files_agree(self):
        with (conformance.CORPUS_DIR / "catalogue.csv").open(encoding="utf-8", newline="") as handle:
            catalogued = sorted(row["case_id"].lower() for row in csv.DictReader(handle))
        self.assertEqual(catalogued, sorted(conformance.case_ids()))

    def test_a_tampered_case_refuses_to_load(self):
        """The integrity check is per load, not just per suite run."""

        with tempfile.TemporaryDirectory() as scratch:
            root = Path(scratch) / "corpus"
            shutil.copytree(conformance.CORPUS_DIR, root)
            victim = root / "cases" / "sem-rel-001.json"
            victim.write_text(victim.read_text(encoding="utf-8").replace('"finish": 7', '"finish": 8'), encoding="utf-8")
            (root / "cases" / "sem-xxx-999.json").write_text("{}", encoding="utf-8")
            (root / "README.md").unlink()
            problems = conformance.verify(root, self.manifest)
        self.assertEqual(
            problems,
            ["missing: README.md", "changed: cases/sem-rel-001.json", "unlisted: cases/sem-xxx-999.json"],
        )

    def test_load_case_re_derives_the_hash(self):
        forged = Manifest(
            repository=self.manifest.repository,
            commit=self.manifest.commit,
            upstream_path=self.manifest.upstream_path,
            copied_on=self.manifest.copied_on,
            files={**self.manifest.files, "cases/sem-rel-001.json": "0" * 64},
        )
        with self.assertRaises(CorpusIntegrityError):
            conformance.load_case("sem-rel-001", forged)
        with self.assertRaises(CorpusIntegrityError):
            conformance.load_case("sem-nope-000")


class RoadmapCountTests(unittest.TestCase):
    """The numbers in docs/goals/roadmap.json are the corpus's, not anybody's memory."""

    def setUp(self):
        self.block = load_roadmap().conformance
        self.manifest = conformance.load_manifest()

    def test_the_roadmap_counts_are_derived_from_the_cases(self):
        derived = conformance.census()
        for key, value in derived.items():
            with self.subTest(key):
                self.assertEqual(self.block[key], value, f"roadmap says {self.block[key]}, the corpus says {value}")

    def test_the_roadmap_names_the_pinned_commit(self):
        self.assertEqual(self.block["commit"], self.manifest.commit)
        self.assertEqual(self.block["manifest"], "src/sto/conformance/MANIFEST.json")
        self.assertIn(self.manifest.commit[:7], self.block["source"])

    def test_the_native_only_case_is_the_one_the_note_names(self):
        native = [c for c in conformance.case_ids() if conformance.classify(conformance.load_case(c)) == conformance.NATIVE_ONLY]
        for case_id in native:
            self.assertIn(case_id.upper(), self.block["note"])


@unittest.skipUnless((PM_DIR / ".git").exists(), "PM-Software clone not present; set STO_REQUIRE_PM=1 to fail")
class UpstreamAgreementTests(unittest.TestCase):
    """The copy agrees with the pinned commit in the upstream clone's history."""

    def test_every_pinned_file_matches_the_upstream_commit(self):
        manifest = conformance.load_manifest()
        for relative, expected in sorted(manifest.files.items()):
            with self.subTest(relative):
                shown = subprocess.run(
                    ["git", "-C", str(PM_DIR), "show", f"{manifest.commit}:{manifest.upstream_path}/{relative}"],
                    check=True,
                    capture_output=True,
                ).stdout
                self.assertEqual(hashlib.sha256(shown).hexdigest(), expected)


if __name__ == "__main__":
    unittest.main()
