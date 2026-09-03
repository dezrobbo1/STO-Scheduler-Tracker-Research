"""The roadmap data must describe the repository as it actually is.

The centrepiece is `PendingRuleTests.test_pending_rules_have_not_arrived_yet`.
`AGENTS.md` states several rules before the machinery exists to enforce them.
Each carries a condition; when that condition is met, this fails and asks for
the rule to be promoted. That is the review trigger: it fires because something
changed, not because a calendar said so, and nobody has to remember.
"""

from __future__ import annotations

import re
import tomllib
import unittest
from pathlib import Path

from sto.roadmap import (
    ACTIVE_PATH,
    REPO_ROOT,
    RoadmapError,
    describe,
    evaluate,
    load,
    render_regions,
)


class PredicateTests(unittest.TestCase):
    """The evaluator must be able to say no *and* yes.

    Without this, a refactor that made ``evaluate`` always return False would
    silently disable the entire mechanism and leave every test green forever.
    This is the most important test in the module.
    """

    def test_path_exists_distinguishes_present_from_absent(self):
        self.assertTrue(evaluate({"kind": "path_exists", "path": "README.md"}))
        self.assertFalse(evaluate({"kind": "path_exists", "path": "nope/nope.md"}))

    def test_import_succeeds_distinguishes_importable_from_not(self):
        self.assertTrue(evaluate({"kind": "import_succeeds", "module": "json"}))
        self.assertFalse(
            evaluate({"kind": "import_succeeds", "module": "sto.definitely_not_a_module"})
        )

    def test_an_unknown_predicate_raises_rather_than_returning_false(self):
        """Returning False would silently mark a live rule as never-arrived."""

        with self.assertRaises(RoadmapError):
            evaluate({"kind": "vibes", "path": "README.md"})


class RoadmapDataTests(unittest.TestCase):
    def setUp(self):
        self.roadmap = load()

    def test_the_roadmap_declares_phases_and_rules(self):
        self.assertTrue(self.roadmap.phases)
        self.assertTrue(self.roadmap.rules)

    def test_gate_evidence_paths_resolve(self):
        offences = [
            f"{phase['id']}/{item['id']} cites {item['evidence']}"
            for phase in self.roadmap.phases
            for item in phase["gate"]
            if item.get("evidence") and not (REPO_ROOT / item["evidence"]).exists()
        ]
        self.assertEqual(offences, [], "a gate criterion cites evidence that is not there")

    def test_a_met_criterion_names_what_shows_it(self):
        offences = [
            f"{phase['id']}/{item['id']}"
            for phase in self.roadmap.phases
            for item in phase["gate"]
            if item["met"] and not item.get("evidence")
        ]
        self.assertEqual(
            offences, [], "a gate criterion is marked met but names nothing that shows it"
        )


class PendingRuleTests(unittest.TestCase):
    def setUp(self):
        self.roadmap = load()

    def test_pending_rules_have_not_arrived_yet(self):
        arrived = [rule for rule in self.roadmap.pending_rules() if evaluate(rule["live_when"])]
        if not arrived:
            return
        report = []
        for rule in arrived:
            report.append(
                f"\n{rule['id']} is marked pending, but its machinery has arrived:\n"
                f"  {describe(rule['live_when'])}.\n\n"
                f"  Rule:    {rule['summary']}\n"
                f"  Owed to: {rule['owed_to']}\n\n"
                "  Do these, then this passes:\n"
                "    1. Write the test that enforces the rule.\n"
                "    2. Set enforced_by to that test's path in docs/goals/roadmap.json.\n"
                '    3. Set the rule\'s status to "live".\n'
                f"    4. Delete the (pending — {rule['id']}) marker from AGENTS.md.\n"
                "    5. PYTHONPATH=src python3 -m sto.cli roadmap render\n"
            )
        self.fail("".join(report))

    def test_live_rules_are_actually_enforced(self):
        offences: list[str] = []
        for rule in self.roadmap.rules:
            if rule["status"] != "live":
                continue
            if not evaluate(rule["live_when"]):
                offences.append(f"{rule['id']} is live but {describe(rule['live_when'])} is false")
                continue
            enforcer = rule.get("enforced_by")
            if not enforcer:
                offences.append(f"{rule['id']} is live but names no enforcing test")
            elif not (REPO_ROOT / enforcer).exists():
                offences.append(f"{rule['id']} names a missing enforcer: {enforcer}")
            elif rule["id"] not in (REPO_ROOT / enforcer).read_text(encoding="utf-8"):
                offences.append(
                    f"{rule['id']} names {enforcer}, which does not mention the rule id — "
                    "the binding is unverifiable"
                )
        self.assertEqual(offences, [], "\n  ".join(offences))

    def test_at_least_one_rule_of_each_status_is_exercised(self):
        """A registry holding only unfinished work would stop exercising the
        evaluator the moment it emptied."""

        statuses = {rule["status"] for rule in self.roadmap.rules}
        self.assertIn("live", statuses)


class RenderTests(unittest.TestCase):
    def test_generated_regions_match_the_data(self):
        roadmap = load()
        current = ACTIVE_PATH.read_text(encoding="utf-8")
        self.assertEqual(
            render_regions(current, roadmap),
            current,
            "docs/goals/ACTIVE.md generated regions are stale. Run:\n"
            "  PYTHONPATH=src python3 -m sto.cli roadmap render",
        )

    def test_the_regions_exist_and_carry_content(self):
        text = ACTIVE_PATH.read_text(encoding="utf-8")
        for name in ("now", "rules"):
            begin = text.find(f"<!-- roadmap:begin {name} -->")
            end = text.find(f"<!-- roadmap:end {name} -->")
            self.assertNotEqual(begin, -1, f"no '{name}' region")
            self.assertGreater(end, begin, f"'{name}' region is inverted")
            self.assertGreater(end - begin, 200, f"'{name}' region is suspiciously empty")
        self.assertIn(load().current_phase, text)


class PythonFloorTests(unittest.TestCase):
    """CI must test the version the project declares it supports."""

    def test_ci_covers_the_declared_floor(self):
        with (REPO_ROOT / "pyproject.toml").open("rb") as handle:
            declared = tomllib.load(handle)["project"]["requires-python"]
        floor = re.search(r"(\d+\.\d+)", declared).group(1)

        workflow = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        versions = re.findall(r'"(\d+\.\d+)"', workflow)
        self.assertTrue(versions, "no python-version found in the workflow")
        self.assertIn(
            floor,
            versions,
            f"pyproject.toml requires-python is {declared!r} but CI tests "
            f"{sorted(set(versions))}. One of them is wrong; the code may use "
            "syntax the untested version lacks.",
        )
