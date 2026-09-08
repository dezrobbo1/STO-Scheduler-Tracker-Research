"""The governed documents must not cite things that are not there.

`AGENTS.md` was written on 2026-09-02 and by that evening asserted four things
that were not true, including a validation command using tools that are not
installed and a conformance suite that does not exist. Prose rots; a test does
not.

Only the *governed* documents are scanned — the ones a reader is meant to act on
today. `docs/roadmap/CONSOLIDATION-PLAN.md` and `docs/history/` are dated
records, deliberately excluded: 159 of the plan's 178 path-shaped references do
not resolve, because it uses one notation for paths here, paths in sibling
repositories and paths that do not exist yet. A record that has stopped being
true is still an accurate record of what was decided.

There is no hand-maintained exception list. A reference is legitimate if it
exists, if it belongs to a sibling repository (by prefix), or if a *pending* rule
in `docs/goals/roadmap.json` promises to create it — and that last permission
disappears by itself when the rule goes live.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from sto.roadmap import REPO_ROOT, load

GOVERNED = (
    "AGENTS.md",
    "README.md",
    "docs/goals/ACTIVE.md",
    *(str(path.relative_to(REPO_ROOT)) for path in sorted((REPO_ROOT / "docs" / "adr").glob("*.md"))),
)

_BACKTICKED = re.compile(r"`([^`\n]+)`")
_SUFFIXES = (".md", ".py", ".json", ".yml", ".yaml", ".toml", ".xml", ".sh", ".sql")


def is_path_shaped(token: str) -> bool:
    """A token that claims to name a file or directory.

    Deliberately narrow: prose like ``the docs/ directory`` and code like
    ``zip(strict=)`` must not be mistaken for a reference.
    """

    if any(character in token for character in " ()=$<>|*"):
        return False
    # A bare extension (".mpp", ".xml") names a format, not a file.
    if token.startswith(".") and "/" not in token:
        return False
    return "/" in token or token.endswith(_SUFFIXES)


def _references() -> list[tuple[str, int, str]]:
    found: list[tuple[str, int, str]] = []
    for name in GOVERNED:
        path = REPO_ROOT / name
        if not path.is_file():
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            for token in _BACKTICKED.findall(line):
                if is_path_shaped(token):
                    found.append((name, number, token))
    return found


class ReferenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.roadmap = load()
        cls.references = _references()

    def _resolves(self, citing: str, token: str) -> bool:
        bare = token.rstrip("/")
        if (REPO_ROOT / bare).exists():
            return True
        # A sibling document may cite a neighbour by bare filename.
        if ((REPO_ROOT / citing).parent / bare).exists():
            return True
        if any(token.startswith(prefix) for prefix in self.roadmap.foreign_prefixes):
            return True
        return bare in self.roadmap.claimed_paths()

    def test_every_referenced_path_resolves(self):
        offences = [
            f"{citing}:{number} cites '{token}'"
            for citing, number, token in self.references
            if not self._resolves(citing, token)
        ]
        self.assertEqual(
            offences,
            [],
            "a governed document cites something that is not there. Either the "
            "path is wrong, or it belongs to a sibling repository and needs its "
            "owner prefix, or a rule in docs/goals/roadmap.json should promise "
            "to create it:\n  " + "\n  ".join(offences),
        )

    def test_the_scan_found_enough_to_be_meaningful(self):
        """A guard that silently scans nothing is worse than none."""

        self.assertGreaterEqual(len(self.references), 20)
        by_document = {citing for citing, _, _ in self.references}
        self.assertIn("AGENTS.md", by_document)
        self.assertIn("docs/goals/ACTIVE.md", by_document)

    def test_the_shape_test_distinguishes_paths_from_prose(self):
        self.assertTrue(is_path_shaped("docs/goals/ACTIVE.md"))
        self.assertTrue(is_path_shaped("pyproject.toml"))
        self.assertFalse(is_path_shaped("the docs/ directory"))
        self.assertFalse(is_path_shaped("zip(strict=)"))
        self.assertFalse(is_path_shaped("X | None"))
        self.assertFalse(is_path_shaped(".mspdi.xml"))


class PendingMarkerTests(unittest.TestCase):
    """Every ``(pending — PR-x)`` in the prose is a rule in the registry."""

    MARKER = re.compile(r"\(pending[^)]*?(PR-[a-z0-9-]+)")

    def setUp(self):
        self.roadmap = load()
        self.text = (REPO_ROOT / "AGENTS.md").read_text(encoding="utf-8")

    def test_markers_and_registry_agree(self):
        marked = set(self.MARKER.findall(self.text))
        pending = {rule["id"] for rule in self.roadmap.pending_rules()}
        self.assertEqual(
            marked,
            pending,
            "AGENTS.md pending markers and docs/goals/roadmap.json disagree.\n"
            f"  marked in prose but not pending in the registry: {sorted(marked - pending)}\n"
            f"  pending in the registry but unmarked in prose:   {sorted(pending - marked)}",
        )

    def test_no_marker_is_left_without_an_id(self):
        """A bare ``(pending)`` names no rule, so nothing can tell when it
        comes due. The sentence introducing the convention writes the id as an
        ellipsis and is therefore not a marker."""

        self.assertNotIn(
            "(pending)",
            self.text,
            "AGENTS.md carries a bare '(pending)' with no PR- id",
        )

    def test_no_markers_means_no_pending_rules(self):
        if not self.roadmap.pending_rules():
            self.assertNotIn("(pending", self.text)


class SliceCitationTests(unittest.TestCase):
    CITATION = re.compile(r"\b((?:S|I|PL)\d{1,2})\b")

    def test_slice_ids_cited_in_active_resolve(self):
        roadmap = load()
        text = (REPO_ROOT / "docs" / "goals" / "ACTIVE.md").read_text(encoding="utf-8")
        cited = set(self.CITATION.findall(text))
        unknown = sorted(cited - roadmap.slice_ids)
        self.assertEqual(
            unknown,
            [],
            f"docs/goals/ACTIVE.md owes work to {unknown}, which are not slices "
            "in docs/goals/roadmap.json",
        )

    @staticmethod
    def _counted() -> re.Pattern[str]:
        """A number, in digits or words, in front of a thing the roadmap counts."""

        return re.compile(
            r"\b(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|"
            r"thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty)[- ]"
            r"(?:slice-days?|slices|gate criteria)\b",
            re.IGNORECASE,
        )

    def test_no_prose_counts_the_roadmap_already_knows(self):
        """A count of repository contents in prose goes stale by construction.

        ``AGENTS.md`` says so and this is the class it means: how many slices a
        phase carries, how many criteria a gate has, how many slice-days are
        left. Every one of those is in ``docs/goals/roadmap.json`` and is
        rendered into the generated regions of ``docs/goals/ACTIVE.md`` by
        ``sto roadmap render``, so a second copy written by hand can only
        disagree with it later. Numbers measured from a real file are not this:
        they are evidence, they belong with the test that pins them, and they
        name a file rather than a phase.

        The scope is the documents that claim to describe the repository *now*.
        ``docs/adr/`` and ``docs/history/`` are dated records of what was
        decided and what was true when it was decided -- ``AGENTS.md`` puts
        evidence in exactly those two places -- so a count there ages into a
        historical statement rather than into a false one, and rewriting an
        accepted ADR to remove it would be editing the record. An ADR written
        today still should not restate the roadmap's bookkeeping, which is why
        ADR-011 names the slices that moved instead of counting them.
        """

        counted = self._counted()
        offences: list[str] = []
        for path in (
            REPO_ROOT / "docs" / "goals" / "ACTIVE.md",
            REPO_ROOT / "AGENTS.md",
            REPO_ROOT / "README.md",
        ):
            text = path.read_text(encoding="utf-8")
            # The generated regions are rendered from the roadmap itself, so a
            # count there is the roadmap's own and cannot drift from it.
            text = re.sub(
                r"<!-- roadmap:begin .*?<!-- roadmap:end \w+ -->", "", text, flags=re.S
            )
            for match in counted.finditer(text):
                line = text[: match.start()].count("\n") + 1
                offences.append(
                    f"{path.relative_to(REPO_ROOT)}:{line} counts "
                    f"{match.group(0)!r} in prose"
                )
        self.assertEqual(
            offences,
            [],
            "docs/goals/roadmap.json holds these counts and `sto roadmap status` "
            "prints them; name the slices instead:\n  " + "\n  ".join(offences),
        )

    def test_no_document_counts_the_test_suite(self):
        """A test count in prose is stale the next time a test is added.

        ``AGENTS.md`` names tests in the same breath as files and cases. This
        one covers every document, `docs/adr/` and `docs/history/` included:
        a count of *this repository's* tests is never evidence about a real
        file, so unlike a slice count it does not age into a true historical
        statement -- it ages into a wrong one, and a reader chasing it runs a
        command that disagrees.
        """

        counted = re.compile(r"\b\d+\s+tests?\b", re.IGNORECASE)
        offences: list[str] = []
        for path in sorted(REPO_ROOT.glob("docs/**/*.md")) + [
            REPO_ROOT / "AGENTS.md",
            REPO_ROOT / "README.md",
        ]:
            if path.name == "CONSOLIDATION-PLAN.md":
                # Frozen on 2026-09-02 and explicitly not maintained; its own
                # preamble lists the counts in it that have already gone stale.
                continue
            for match in counted.finditer(path.read_text(encoding="utf-8")):
                text = path.read_text(encoding="utf-8")
                line = text[: match.start()].count("\n") + 1
                offences.append(
                    f"{path.relative_to(REPO_ROOT)}:{line} counts {match.group(0)!r}"
                )
        self.assertEqual(
            offences,
            [],
            "name the command that counts them instead:\n  " + "\n  ".join(offences),
        )

    def test_the_guard_catches_a_count_it_should(self):
        counted = self._counted()
        self.assertTrue(counted.search("Phase 1 carries eleven slices"))
        self.assertTrue(counted.search("twenty slice-days left"))
        self.assertTrue(counted.search("two gate criteria rest on those cases"))
        self.assertTrue(counted.search("P1 has 3 slices"))
        # Evidence measured from a real file is not a count of this repository.
        self.assertIsNone(counted.search("451 activities agree with the stored dates"))
        self.assertIsNone(counted.search("the corpus declares 47 executable cases"))

    def test_the_scan_found_slice_citations(self):
        text = (REPO_ROOT / "docs" / "goals" / "ACTIVE.md").read_text(encoding="utf-8")
        self.assertGreaterEqual(len(set(self.CITATION.findall(text))), 4)
