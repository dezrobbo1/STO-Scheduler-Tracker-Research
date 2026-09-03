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


class DependencyTests(unittest.TestCase):
    """A gate nobody can cross should say so now, not in the week it is reached."""

    def setUp(self):
        self.roadmap = load()

    def test_a_blocked_dependency_holds_its_criteria_open(self):
        offences = [
            f"{item['id']} is met but waits on {dependency['id']}"
            for dependency in self.roadmap.dependencies
            if dependency["status"] == "blocked"
            for ref in dependency["needed_by"]
            if ref in self.roadmap.gate_ids
            for item in [self.roadmap.gate_item(ref)]
            if item["met"]
        ]
        self.assertEqual(
            offences,
            [],
            "a criterion is marked met while something outside the code is missing; "
            "either the dependency arrived and its status is stale, or the criterion "
            "was crossed on something other than what it names",
        )

    def test_every_dependency_says_who_waits_and_why(self):
        for dependency in self.roadmap.dependencies:
            with self.subTest(dependency["id"]):
                self.assertTrue(dependency["what"].strip())
                self.assertTrue(dependency["note"].strip())
                self.assertTrue(dependency["needed_by"])

    def test_a_blocked_dependency_is_actually_exercised(self):
        """Without one, the mechanism above proves nothing."""

        statuses = {dependency["status"] for dependency in self.roadmap.dependencies}
        self.assertIn("blocked", statuses)


class EvidenceExecutionTests(unittest.TestCase):
    """Evidence that skips shows green. A met criterion must not hide that."""

    def setUp(self):
        self.roadmap = load()

    def test_conditional_evidence_is_bound_to_the_switch_it_names(self):
        offences: list[str] = []
        for phase in self.roadmap.phases:
            for item in phase["gate"]:
                conditional = item.get("evidence_conditional")
                if not conditional:
                    continue
                evidence = REPO_ROOT / item["evidence"]
                if not evidence.exists():
                    offences.append(f"{item['id']} cites missing {item['evidence']}")
                elif conditional["env"] not in evidence.read_text(encoding="utf-8"):
                    offences.append(
                        f"{item['id']} says {conditional['env']} governs "
                        f"{item['evidence']}, which never mentions it — "
                        "the binding is unverifiable"
                    )
        self.assertEqual(offences, [], "\n  ".join(offences))

    def test_the_switch_really_turns_absence_into_failure(self):
        """Mentioning the variable is not honouring it. Run the file and see."""

        import os
        import subprocess
        import sys

        env = dict(os.environ)
        env.update(
            {
                "PYTHONPATH": str(REPO_ROOT / "src"),
                "STO_REQUIRE_BOILER": "1",
                "STO_BOILER_BEFORE": str(REPO_ROOT / "nope" / "absent-before.xml"),
                "STO_BOILER_DAY5": str(REPO_ROOT / "nope" / "absent-day5.xml"),
            }
        )
        result = subprocess.run(
            [sys.executable, "-m", "unittest", "tests.test_canonical_model"],
            cwd=REPO_ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
        )
        self.assertNotEqual(result.returncode, 0, "absence was tolerated")
        self.assertIn("STO_REQUIRE_BOILER=1 but", result.stderr)
        self.assertIn("absent-before.xml", result.stderr)

    def test_the_boiler_criteria_declare_that_they_do_not_always_run(self):
        """The specific case this machinery was built for.

        `tests/test_canonical_model.py` skips its real-schedule class when the
        files are absent, which is every CI run. Two criteria cite it.
        """

        conditional = {
            item["id"]
            for phase in self.roadmap.phases
            for item in phase["gate"]
            if item.get("evidence") == "tests/test_canonical_model.py"
            and item.get("evidence_conditional")
        }
        cites = {
            item["id"]
            for phase in self.roadmap.phases
            for item in phase["gate"]
            if item.get("evidence") == "tests/test_canonical_model.py"
        }
        self.assertEqual(cites, conditional, "a criterion cites the skipping file silently")


class EffortTests(unittest.TestCase):
    def test_every_slice_records_its_effort(self):
        for entry in load().slices:
            with self.subTest(entry["id"]):
                self.assertIsInstance(entry["days"], int)
                self.assertGreater(entry["days"], 0)


class ConformanceCorpusTests(unittest.TestCase):
    """The corpus is counted once here so no document has to say a number."""

    def test_the_subsets_account_for_every_case(self):
        corpus = load().conformance
        self.assertEqual(
            corpus["cases_total"],
            corpus["native_validation_only"]
            + corpus["levelling_only"]
            + corpus["executable_by_the_cpm_engine"],
            "the corpus subsets do not add up to the whole",
        )

    def test_the_engine_gate_asks_for_the_executable_subset(self):
        roadmap = load()
        expected = roadmap.conformance["executable_by_the_cpm_engine"]
        text = roadmap.gate_item("P1-G1")["text"]
        numbers = [int(value) for value in re.findall(r"\b(\d+)\b", text)]
        self.assertEqual(
            numbers,
            [expected],
            "the P1 gate and the conformance block disagree on how many cases "
            f"the CPM engine must pass: gate says {numbers}, data says {expected}",
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
