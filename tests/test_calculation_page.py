"""The PL14 planner page, checked against the API it claims to read.

Not a browser test: nothing here renders anything. It asks the one question a
static page can get wrong without anybody noticing, which is whether the routes
and fields it names still exist. A page that fetched a renamed field would show
empty cells and pass every other test in this repository.
"""

from __future__ import annotations

import os
import re
import json
import shutil
import subprocess
import unittest
from html.parser import HTMLParser
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "src" / "sto" / "api" / "static"

# The page's own consistency needs nothing installed. Comparing it with the
# response models needs pydantic, which the bare suite does not have; the api
# job sets STO_REQUIRE_DB=1 and turns its absence into a failure there.
try:
    import fastapi  # noqa: F401 - the route contract needs the application too
    from sto.api import schemas
except ImportError as error:  # the bare suite: no api extra
    if os.environ.get("STO_REQUIRE_DB") == "1":
        raise RuntimeError(
            f"STO_REQUIRE_DB=1 but the api extra is missing ({error.name})"
        ) from error
    schemas = None  # type: ignore[assignment]


class _Links(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.assets: list[str] = []
        self.ids: set[str] = set()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "script" and values.get("src"):
            self.assets.append(values["src"])
        if tag == "link" and values.get("href"):
            self.assets.append(values["href"])
        if values.get("id"):
            self.ids.add(values["id"])


class ThePageIsSelfConsistentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.html = (STATIC / "index.html").read_text(encoding="utf-8")
        self.script = (STATIC / "app.js").read_text(encoding="utf-8")
        self.parser = _Links()
        self.parser.feed(self.html)

    def test_every_asset_it_asks_for_is_there(self):
        """A relative href is a file that must exist beside the page.

        An inline ``data:`` URI asks the server for nothing -- the page uses one
        to stop the browser's automatic favicon request becoming a 404 in the
        console -- so it is not an asset and there is nothing to find.
        """

        requested = [asset for asset in self.parser.assets if not asset.startswith("data:")]
        self.assertTrue(requested, "the page requests no assets; this would pass vacuously")
        for asset in requested:
            with self.subTest(asset):
                self.assertTrue((STATIC / asset).is_file(), f"{asset} is not in {STATIC}")

    def test_it_does_not_read_a_schedule_date_as_a_local_instant(self):
        """A schedule date is wall-clock with no offset.

        `Date.parse` reads one in the browser's zone, so across a
        daylight-saving transition two consecutive midnights come out 23 hours
        apart and every bar on the chart shifts. This is a static check because
        the suite has no browser; what it can say is that the call is not
        there and the neutral reader is.
        """

        code = re.sub(r"//[^\n]*", "", self.script)
        self.assertNotIn("Date.parse(", code)
        self.assertIn("Date.UTC(", code)

    def test_it_tells_an_absent_schedule_from_a_refused_one(self):
        """A project awaiting import is distinct from an integrity refusal."""

        self.assertIn("error.status === 409", self.script)
        self.assertIn("failure.status = response.status", self.script)
        self.assertIn("planner state could not be served", self.script)

    def test_it_does_not_show_a_calculation_for_a_project_left_behind(self):
        """`show` sets the freshness guard itself, so calling it is not safe."""

        self.assertIn("projects.value !== projectId", self.script)

    def test_the_chart_scale_is_built_from_the_rows_it_draws(self):
        """An excluded row far outside the schedule stretched the scale.

        It never appeared, so every drawn bar was squeezed into a sliver of the
        track by a row the reader could not see.
        """

        scale = self.script[self.script.index("function comparisonMoments("):]
        scale = scale[: scale.index("function band(")]
        self.assertIn("if (!row.early_start) continue;", scale)
        self.assertNotIn("result.summaries", scale)

    def test_scale_and_status_behaviour(self):
        node = shutil.which("node") or os.environ.get("CODEX_PRIMARY_RUNTIME_NODE")
        if not node:
            self.skipTest("Node is required to execute the page's JavaScript")
        functions = "\n".join(
            re.search(r"function " + name + r"\([\s\S]*?\n}", self.script).group(0)
            for name in ("instant", "comparisonMoments", "statusDate")
        )
        probe = r"""
const day = '2026-09-09T08:00:00';
const row = {early_start: day, early_finish: day, source_start: day, source_finish: day};
const hidden = {early_start: null, source_start: '2000-01-01T00:00:00'};
const state = {baseline: {activities: [row]}, scenario: null};
const base = comparisonMoments(state);
state.baseline.activities.push(hidden);
console.log(JSON.stringify({base, withHidden: comparisonMoments(state),
  empty: comparisonMoments({baseline: {activities: [hidden]}, scenario: null}),
  status: statusDate({status_time_outside_window: true})}));
"""
        completed = subprocess.run([node, "-e", functions + probe],
                                   check=True, text=True, capture_output=True)
        measured = json.loads(completed.stdout)
        self.assertIsNotNone(measured["base"])
        self.assertGreater(measured["base"]["span"], 0)
        self.assertEqual(measured["base"], measured["withHidden"])
        self.assertIsNone(measured["empty"])
        self.assertIn("scheduling window policy", measured["status"])

    def test_second_precision_and_a_terminal_milestone_are_visible(self):
        node = shutil.which("node") or os.environ.get("CODEX_PRIMARY_RUNTIME_NODE")
        if not node:
            self.skipTest("Node is required to execute the page's JavaScript")
        functions = "\n".join(
            re.search(r"function " + name + r"\([\s\S]*?\n}", self.script).group(0)
            for name in ("moment", "instant", "band")
        )
        probe = r"""
global.document = {createElement: () => ({className: '', style: {}})};
const edge = band(
  {from: Date.UTC(2026, 0, 1, 0, 0, 0), span: 1000},
  '2026-01-01T00:00:01',
  '2026-01-01T00:00:01',
  'bar computed'
);
console.log(JSON.stringify({
  timestamp: moment('2026-01-01T00:00:07'),
  left: edge.style.left,
  width: edge.style.width
}));
"""
        completed = subprocess.run(
            [node, "-e", functions + probe], check=True, text=True, capture_output=True
        )
        measured = json.loads(completed.stdout)
        self.assertEqual(measured["timestamp"], "2026-01-01 00:00:07")
        self.assertAlmostEqual(float(measured["left"].removesuffix("%")), 99.6)
        self.assertAlmostEqual(float(measured["width"].removesuffix("%")), 0.4)

    def test_rendered_movement_and_disposition_contract(self):
        """Execute the logic that marks the edited and downstream rows."""

        node = shutil.which("node") or os.environ.get("CODEX_PRIMARY_RUNTIME_NODE")
        if not node:
            self.skipTest("Node is required to execute the page's JavaScript")
        functions = "\n".join(
            re.search(r"function " + name + r"\([\s\S]*?\n}", self.script).group(0)
            for name in ("classifyMovement", "disposition")
        )
        probe = r"""
const base = {activity_uid: 'a', early_start: '08:00', early_finish: '09:00',
  disposition: 'scheduled', assumptions: []};
const changed = {...base, early_finish: '10:00'};
const movedBase = {...base, activity_uid: 'b'};
const moved = {...movedBase, early_start: '10:00', early_finish: '11:00'};
console.log(JSON.stringify({
  edited: classifyMovement(base, changed, 'a'),
  downstream: classifyMovement(movedBase, moved, 'a'),
  reset: classifyMovement(base, null, 'a'),
  normal: disposition(base).label,
  assumed: disposition({...base, assumptions: ['ACTIVITY_DURATION_ELAPSED']}).label,
  deferred: disposition({...base,
    assumptions: ['ACTIVITY_SECONDARY_CONSTRAINT_NOT_APPLIED']}).label,
  excluded: disposition({...base, disposition: 'excluded'}).label
}));
"""
        measured = json.loads(
            subprocess.run(
                [node, "-e", functions + probe],
                check=True,
                text=True,
                capture_output=True,
            ).stdout
        )
        self.assertEqual(measured["edited"], "edited")
        self.assertEqual(measured["downstream"], "downstream")
        self.assertEqual(measured["reset"], "")
        self.assertEqual(
            {measured[key] for key in ("normal", "assumed", "deferred", "excluded")},
            {
                "calculated normally",
                "calculated with assumption",
                "deferred constraint support",
                "unsupported / excluded",
            },
        )

    def test_it_drops_a_response_for_a_project_no_longer_selected(self):
        """A generation distinguishes out-of-order A to B to A responses."""

        node = shutil.which("node") or os.environ.get("CODEX_PRIMARY_RUNTIME_NODE")
        if not node:
            self.skipTest("Node is required to execute the page's JavaScript")
        functions = "\n".join(
            re.search(r"function " + name + r"\([\s\S]*?\n}", self.script).group(0)
            for name in ("selectedProject", "beginRefresh", "currentRefresh")
        )
        probe = r"""
const projects = {value: 'project-a'};
let refreshGeneration = 0;
const firstA = beginRefresh();
projects.value = 'project-b';
const projectB = beginRefresh();
projects.value = 'project-a';
const secondA = beginRefresh();
console.log(JSON.stringify({
  firstA: currentRefresh(firstA, 'project-a'),
  projectB: currentRefresh(projectB, 'project-b'),
  secondA: currentRefresh(secondA, 'project-a'),
  generations: [firstA, projectB, secondA]
}));
"""
        measured = json.loads(
            subprocess.run(
                [node, "-e", functions + probe],
                check=True,
                text=True,
                capture_output=True,
            ).stdout
        )
        self.assertEqual(
            measured,
            {
                "firstA": False,
                "projectB": False,
                "secondA": True,
                "generations": [1, 2, 3],
            },
        )
        self.assertEqual(self.script.count("currentRefresh(generation, projectId)"), 3)

    def test_import_and_calculation_success_belong_to_the_rendered_project(self):
        """Execute the freshness decisions used after both awaited mutations."""

        node = shutil.which("node") or os.environ.get("CODEX_PRIMARY_RUNTIME_NODE")
        if not node:
            self.skipTest("Node is required to execute the page's JavaScript")
        functions = "\n".join(
            re.search(r"function " + name + r"\([\s\S]*?\n}", self.script).group(0)
            for name in (
                "selectedProject", "renderedImport", "renderedCalculation",
                "renderedScenario", "resetIsDisabled",
            )
        )
        probe = r"""
const projects = {value: 'project-a'};
const imported = {project_id: 'project-a', version_id: 'version-a'};
const calculation = {project_id: 'project-a', version_id: 'version-a',
  calculation_id: 'calculation-a'};
const state = {project_id: 'project-a', baseline_version_id: 'version-a',
  baseline: {version_id: 'version-a', calculation_id: 'calculation-a'}};
const scenario = {...state, current_kind: 'scenario', current_version_id: 'scenario-a',
  scenario: {version_id: 'scenario-a'},
  change: {scenario_version_id: 'scenario-a', activity_uid: 'activity-a',
    after_seconds: 28800}};
const measured = {
  imported: renderedImport(state, imported),
  calculated: renderedCalculation(state, calculation),
  wrongCalculation: renderedCalculation(state,
    {...calculation, calculation_id: 'calculation-old'}),
  scenario: renderedScenario(scenario, 'project-a', 'activity-a', 28800),
  wrongScenario: renderedScenario(scenario, 'project-a', 'activity-a', 14400),
  resetWhileScenario: resetIsDisabled(scenario),
  resetOnBaseline: resetIsDisabled({...state, scenario: null})
};
projects.value = 'project-b';
measured.importAfterSwitch = renderedImport(state, imported);
measured.calculationAfterSwitch = renderedCalculation(state, calculation);
console.log(JSON.stringify(measured));
"""
        measured = json.loads(
            subprocess.run(
                [node, "-e", functions + probe],
                check=True,
                text=True,
                capture_output=True,
            ).stdout
        )
        self.assertEqual(
            measured,
            {
                "imported": True,
                "calculated": True,
                "wrongCalculation": False,
                "scenario": True,
                "wrongScenario": False,
                "resetWhileScenario": False,
                "resetOnBaseline": True,
                "importAfterSwitch": False,
                "calculationAfterSwitch": False,
            },
        )
        import_handler = self.script[self.script.index('importForm.addEventListener'):]
        import_handler = import_handler[: import_handler.index('scenarioForm.addEventListener')]
        self.assertIn("if (!selectedProject(projectId)) return;", import_handler)
        self.assertIn("if (renderedImport(state, imported)) say", import_handler)
        calculation_handler = self.script[
            self.script.index('calculateButton.addEventListener'):
            self.script.index('createProjectForm.addEventListener')
        ]
        self.assertIn("if (!state) return;", calculation_handler)
        self.assertIn("if (!renderedCalculation(state, calculation))", calculation_handler)
        scenario_handler = self.script[
            self.script.index('scenarioForm.addEventListener'):
            self.script.index('resetScenario.addEventListener')
        ]
        self.assertIn("if (!renderedScenario(state, projectId, activityUid, seconds))", scenario_handler)
        reset_handler = self.script[self.script.index('resetScenario.addEventListener'):]
        self.assertIn("resetScenario.disabled = resetIsDisabled(currentState)", reset_handler)
        self.assertIn('if (error.status === 409) await show(projectId);', reset_handler)

    def test_duration_control_and_calculation_detail_keep_the_existing_contract(self):
        self.assertIn('id="duration-hours" type="number" min="0.0003" step="any"', self.html)
        self.assertIn("Calculation details", self.html)
        for field in (
            "late_start", "late_finish", "total_float_seconds", "free_float_seconds",
            "critical", "progress_state", "placed_by", "late_placed_by",
            "constraint_override", "agrees_with_source",
        ):
            with self.subTest(field):
                self.assertIn("row." + field, self.script)

    def test_every_element_the_script_reaches_for_exists_in_the_page(self):
        wanted = set(re.findall(r'querySelector\("#([\w-]+)', self.script))
        self.assertTrue(wanted, "the script selects nothing; this test would pass vacuously")
        self.assertEqual(sorted(wanted - self.parser.ids), [])


@unittest.skipUnless(schemas is not None, "the api extra is not installed")
class ThePageAndTheApiAgreeTests(unittest.TestCase):
    """The fields it reads are the fields the responses declare."""

    def setUp(self) -> None:
        self.script = (STATIC / "app.js").read_text(encoding="utf-8")

    def test_the_routes_it_fetches_are_the_routes_that_exist(self):
        from sto.api.app import create_app

        app = create_app(workspace=None)  # type: ignore[arg-type]
        routes = {getattr(route, "path", "") for route in app.routes}
        for path in (
            "/api/projects",
            "/api/projects/{project_id}/calculations",
            "/api/projects/{project_id}/calculations/latest",
            "/api/projects/{project_id}/planner",
            "/api/projects/{project_id}/scenario",
            "/api/projects/{project_id}/scenario/reset",
            "/api/projects/{project_id}/scenario/export",
        ):
            with self.subTest(path):
                self.assertIn(path, routes)

    def test_the_row_fields_it_reads_are_declared_by_the_response(self):
        """The page renders two kinds of row, so both models are the contract."""

        declared = set(schemas.ActivityRow.model_fields) | set(schemas.SummaryRow.model_fields)
        read = set(re.findall(r"\brow\.(\w+)", self.script))
        self.assertTrue(read, "the script reads no row fields; this would pass vacuously")
        self.assertEqual(sorted(read - declared), [])

    def test_the_header_fields_it_reads_are_declared_too(self):
        declared = set(schemas.CalculationResponse.model_fields)
        read = set(re.findall(r"\bresult\.(\w+)", self.script))
        self.assertTrue(read)
        self.assertEqual(sorted(read - declared), [])

    def test_the_counts_it_names_are_the_counts_the_workspace_produces(self):
        named = set(re.findall(r"\bcounts\.(\w+)", self.script))
        produced = {
            "activities",
            "scheduled",
            "summaries",
            "compared_with_source",
            "agreeing_with_source",
        }
        self.assertTrue(named)
        self.assertEqual(sorted(named - produced), [])


if __name__ == "__main__":
    unittest.main()
