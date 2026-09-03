"""Phases, slices, gate criteria and the rule registry.

`AGENTS.md` holds rules that change rarely. This holds everything that changes
as work proceeds, because a document that mixes the two decays at the rate of
its fastest-moving part -- which is what happened to `AGENTS.md` within four
hours of being written.

The registry is the interesting half. Every rule the working agreement states
before it can be enforced carries a predicate saying when its machinery arrives.
A test evaluates those predicates, so a rule marked pending whose machinery has
appeared fails the suite and asks to be promoted. Nobody has to remember.

Two things beside the registry live here for the same reason. Effort is
recorded per slice in days, so a total is derived rather than written down and
cannot go stale in prose. External dependencies -- a Primavera file, a CMMS
extract -- are rows with the slices and criteria they gate, so a gate that
cannot be crossed says so now rather than in the week it is reached.

Two predicate kinds, deliberately. `path_exists` covers directories, register
files, and -- pointed at a test -- "the enforcing test now exists".
`import_succeeds` covers the one thing it cannot: a package present but not
importable. Running the test suite from inside a predicate was considered and
rejected: it is re-entrant, and it asks whether something is *green* when the
question is whether it has *arrived*.
"""

from __future__ import annotations

import importlib.util
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
ROADMAP_PATH = REPO_ROOT / "docs" / "goals" / "roadmap.json"
ACTIVE_PATH = REPO_ROOT / "docs" / "goals" / "ACTIVE.md"

SCHEMA_VERSION = "sto-roadmap-1"
PREDICATE_KINDS = frozenset({"path_exists", "import_succeeds"})
RULE_STATUSES = frozenset({"pending", "live"})

#: An external dependency is `available`, `blocked` (it does not exist yet, or
#: not to us), or `at_risk` (it exists in one fragile copy). Only `blocked`
#: stops a criterion being met: `at_risk` is a warning about losing something,
#: not about lacking it.
DEPENDENCY_STATUSES = frozenset({"available", "blocked", "at_risk"})
BLOCKING_STATUSES = frozenset({"blocked"})

#: Regions of ACTIVE.md regenerated from this data. Everything outside them is
#: hand-written: narrative is judgement, and generating it would mean editing a
#: template to change a sentence.
REGION_NAMES = ("now", "dependencies", "rules")
_BEGIN = "<!-- roadmap:begin {name} -->"
_END = "<!-- roadmap:end {name} -->"
_WARNING = (
    "<!-- generated from docs/goals/roadmap.json by `sto roadmap render`; "
    "edit the JSON, not this -->"
)


class RoadmapError(ValueError):
    """Raised when the roadmap data is malformed."""


@dataclass(frozen=True, slots=True)
class Roadmap:
    current_phase: str
    phases: tuple[dict[str, Any], ...]
    slices: tuple[dict[str, Any], ...]
    rules: tuple[dict[str, Any], ...]
    foreign_prefixes: tuple[str, ...]
    dependencies: tuple[dict[str, Any], ...] = ()
    conformance: dict[str, Any] | None = None

    def phase(self, phase_id: str) -> dict[str, Any]:
        for entry in self.phases:
            if entry["id"] == phase_id:
                return entry
        raise RoadmapError(f"no phase {phase_id!r}")

    @property
    def slice_ids(self) -> frozenset[str]:
        return frozenset(entry["id"] for entry in self.slices)

    @property
    def gate_ids(self) -> frozenset[str]:
        return frozenset(
            item["id"] for phase in self.phases for item in phase["gate"]
        )

    def gate_item(self, criterion_id: str) -> dict[str, Any]:
        for phase in self.phases:
            for item in phase["gate"]:
                if item["id"] == criterion_id:
                    return item
        raise RoadmapError(f"no gate criterion {criterion_id!r}")

    def blockers_for(self, *refs: str) -> tuple[dict[str, Any], ...]:
        """Blocking dependencies that name any of these slice or criterion ids."""

        return self._dependencies_for(BLOCKING_STATUSES, *refs)

    def at_risk_for(self, *refs: str) -> tuple[dict[str, Any], ...]:
        """Dependencies that exist but could be lost, naming any of these ids.

        They do not hold a criterion open -- the thing is here -- but a gate
        ritual that never mentioned them would let the one copy of an oracle
        stay the one copy.
        """

        return self._dependencies_for(frozenset({"at_risk"}), *refs)

    def _dependencies_for(
        self, statuses: frozenset[str], *refs: str
    ) -> tuple[dict[str, Any], ...]:
        wanted = set(refs)
        return tuple(
            dep
            for dep in self.dependencies
            if dep["status"] in statuses and wanted & set(dep["needed_by"])
        )

    def pending_rules(self) -> tuple[dict[str, Any], ...]:
        return tuple(rule for rule in self.rules if rule["status"] == "pending")

    def claimed_paths(self) -> frozenset[str]:
        """Paths a pending rule licenses as forward references in prose.

        This is what keeps the reference guard free of a hand-maintained
        exception list: the permission is granted by the rule that will create
        the path, and evaporates when the rule goes live.
        """

        return frozenset(
            rule["live_when"]["path"].rstrip("/")
            for rule in self.pending_rules()
            if rule["live_when"]["kind"] == "path_exists"
        )


def load(path: Path | None = None) -> Roadmap:
    """Read the roadmap, validating by construction.

    There is deliberately no JSON Schema file: it would be one more artifact to
    drift, with no consumer outside this function.
    """

    payload = json.loads((path or ROADMAP_PATH).read_text(encoding="utf-8"))

    version = payload.get("schema_version")
    if version != SCHEMA_VERSION:
        raise RoadmapError(f"unsupported schema_version {version!r}")

    phases = tuple(payload.get("phases", ()))
    slices = tuple(payload.get("slices", ()))
    rules = tuple(payload.get("rules", ()))
    if not phases or not rules:
        raise RoadmapError("roadmap must declare phases and rules")

    phase_ids = {entry["id"] for entry in phases}
    current = payload.get("current_phase")
    if current not in phase_ids:
        raise RoadmapError(f"current_phase {current!r} is not a declared phase")

    slice_ids = {entry["id"] for entry in slices}
    for entry in phases:
        for member in entry.get("slices", ()):
            if member not in slice_ids:
                raise RoadmapError(f"phase {entry['id']} lists unknown slice {member!r}")

    for rule in rules:
        if rule["status"] not in RULE_STATUSES:
            raise RoadmapError(f"rule {rule['id']}: bad status {rule['status']!r}")
        kind = rule["live_when"]["kind"]
        if kind not in PREDICATE_KINDS:
            raise RoadmapError(f"rule {rule['id']}: unsupported predicate {kind!r}")
        if rule["owed_to"] not in slice_ids:
            raise RoadmapError(f"rule {rule['id']} is owed to unknown slice {rule['owed_to']!r}")

    dependencies = tuple(payload.get("dependencies", ()))
    gate_ids = {item["id"] for entry in phases for item in entry["gate"]}
    for dependency in dependencies:
        if dependency["status"] not in DEPENDENCY_STATUSES:
            raise RoadmapError(
                f"dependency {dependency['id']}: bad status {dependency['status']!r}"
            )
        if not dependency["needed_by"]:
            raise RoadmapError(
                f"dependency {dependency['id']} gates nothing; a dependency nobody "
                "waits on is a note, not a dependency"
            )
        for ref in dependency["needed_by"]:
            if ref not in slice_ids and ref not in gate_ids:
                raise RoadmapError(
                    f"dependency {dependency['id']} is needed by {ref!r}, "
                    "which is neither a slice nor a gate criterion"
                )

    for entry in phases:
        for item in entry["gate"]:
            if item["met"] and not item.get("evidence"):
                raise RoadmapError(f"{item['id']} is met but names no evidence")

    return Roadmap(
        current_phase=current,
        phases=phases,
        slices=slices,
        rules=rules,
        foreign_prefixes=tuple(payload.get("foreign_prefixes", ())),
        dependencies=dependencies,
        conformance=payload.get("conformance"),
    )


def evaluate(predicate: dict[str, Any], root: Path | None = None) -> bool:
    """Has this rule's machinery arrived?

    Not "is it correct" and not "is it green" -- only whether the thing exists.
    A false positive is the intended direction: an empty stub directory trips
    the alarm, and the alarm means *review this rule*, which is the point.
    """

    kind = predicate["kind"]
    if kind == "path_exists":
        return ((root or REPO_ROOT) / predicate["path"]).exists()
    if kind == "import_succeeds":
        try:
            return importlib.util.find_spec(predicate["module"]) is not None
        except (ImportError, ValueError):
            return False
    raise RoadmapError(f"unsupported predicate kind {kind!r}")


def describe(predicate: dict[str, Any]) -> str:
    if predicate["kind"] == "path_exists":
        return f"{predicate['path']} exists"
    return f"{predicate['module']} imports"


#: Footnote marker for evidence that does not always execute. A criterion can
#: be honestly met and still be invisible in CI; saying which is the point.
CONDITIONAL_MARK = "‡"


def _render_now(roadmap: Roadmap) -> str:
    phase = roadmap.phase(roadmap.current_phase)
    status = phase["status"].replace("_", " ")
    met = sum(1 for item in phase["gate"] if item["met"])
    lines = [
        f"**{phase['id']} — {phase['title']}** ({status}; "
        f"{met} of {len(phase['gate'])} gate criteria met)",
        "",
        "| | Gate criterion | Shown by |",
        "|---|---|---|",
    ]
    footnotes: list[str] = []
    for item in phase["gate"]:
        blockers = roadmap.blockers_for(item["id"])
        if item["met"]:
            mark = "✓"
        elif blockers:
            mark = "⊘"
        else:
            mark = "·"
        evidence = f"`{item['evidence']}`" if item["evidence"] else "—"
        conditional = item.get("evidence_conditional")
        if conditional:
            evidence += f" {CONDITIONAL_MARK}"
            note = (
                f"{CONDITIONAL_MARK} {conditional['why']}; "
                f"set `{conditional['env']}=1` to make their absence a failure "
                "rather than a skip."
            )
            if note not in footnotes:
                footnotes.append(note)
        if blockers:
            evidence += " — waits on " + ", ".join(f"`{b['id']}`" for b in blockers)
        lines.append(f"| {mark} | {item['text']} | {evidence} |")
    if footnotes:
        lines += [""] + footnotes
    return "\n".join(lines)


def _render_dependencies(roadmap: Roadmap) -> str:
    """What the work waits on that no amount of coding supplies."""

    if not roadmap.dependencies:
        return "None recorded."
    lines = [
        "| Dependency | Status | Gates | Asked |",
        "|---|---|---|---|",
    ]
    for dep in roadmap.dependencies:
        gates = ", ".join(dep["needed_by"])
        asked = dep["asked_on"] or "—"
        lines.append(
            f"| `{dep['id']}` — {dep['what']} | {dep['status'].replace('_', ' ')} "
            f"| {gates} | {asked} |"
        )
    return "\n".join(lines)


def _render_rules(roadmap: Roadmap) -> str:
    lines = [
        "| Rule | Owed to | Status | Enforced by / goes live when |",
        "|---|---|---|---|",
    ]
    for rule in roadmap.rules:
        if rule["status"] == "live":
            tail = f"`{rule['enforced_by']}`"
        else:
            tail = describe(rule["live_when"])
        lines.append(
            f"| `{rule['id']}` | {rule['owed_to']} | {rule['status']} | {tail} |"
        )
    return "\n".join(lines)


_RENDERERS = {
    "now": _render_now,
    "dependencies": _render_dependencies,
    "rules": _render_rules,
}


def render_regions(text: str, roadmap: Roadmap) -> str:
    """Replace each marked region with freshly generated content."""

    for name in REGION_NAMES:
        begin, end = _BEGIN.format(name=name), _END.format(name=name)
        try:
            start = text.index(begin)
            finish = text.index(end)
        except ValueError as error:
            raise RoadmapError(
                f"docs/goals/ACTIVE.md has no '{name}' region; expected {begin} … {end}"
            ) from error
        if finish < start:
            raise RoadmapError(f"region {name!r} is inverted")
        body = f"{begin}\n{_WARNING}\n\n{_RENDERERS[name](roadmap)}\n\n"
        text = text[:start] + body + text[finish:]
    return text


def gate_checklist(roadmap: Roadmap, phase_id: str | None = None) -> str:
    """The ritual for crossing a gate, generated so it cannot disagree."""

    phase = roadmap.phase(phase_id or roadmap.current_phase)
    lines = [
        f"Phase {phase['id']} · {phase['title']}"
        f"{' ' * 6}status: {phase['status'].replace('_', ' ')}",
        "",
        "Gate criteria",
    ]
    for item in phase["gate"]:
        lines.append(f"  [{'x' if item['met'] else ' '}] {item['id']}  {item['text']}")
        if item["evidence"]:
            lines.append(f"          shown by: {item['evidence']}")
        conditional = item.get("evidence_conditional")
        if conditional:
            lines.append(
                f"          NOT ALWAYS RUN: {conditional['why']}."
            )
            lines.append(
                f"          Run the gate with {conditional['env']}=1 so a missing "
                "input fails instead of skipping."
            )
        for blocker in roadmap.blockers_for(item["id"]):
            lines.append(f"          BLOCKED by {blocker['id']}: {blocker['what']}")

    refs = (*phase.get("slices", ()), *(i["id"] for i in phase["gate"]))
    blocked = roadmap.blockers_for(*refs)
    if blocked:
        lines += ["", "External dependencies this phase waits on"]
        for dep in blocked:
            lines.append(f"  {dep['id']}  {dep['what']}")
            lines.append(f"          {dep['note']}")
    at_risk = roadmap.at_risk_for(*refs)
    if at_risk:
        lines += ["", "At risk (not blocking, but this phase depends on it)"]
        for dep in at_risk:
            lines.append(f"  {dep['id']}  {dep['what']}")
            lines.append(f"          {dep['note']}")

    owed = [rule for rule in roadmap.pending_rules() if rule["owed_to"] in phase.get("slices", ())]
    if owed:
        lines += ["", "Rules whose machinery is expected in this phase"]
        for rule in owed:
            lines.append(
                f"  {rule['id']}  pending — goes live when {describe(rule['live_when'])}"
            )

    lines += [
        "",
        "Before declaring this phase passed",
        "  1. Every criterion above is [x] and names what shows it, and every",
        "     criterion marked NOT ALWAYS RUN was crossed with its input present.",
        "  2. Re-read AGENTS.md end to end. Anything it asserts that is no longer",
        "     true is a defect: fix it now, not in the next phase.",
        "  3. For each rule that went live: write the enforcing test, set",
        "     enforced_by, set status to \"live\", delete its marker from AGENTS.md.",
        "  4. Write the session record in docs/history/ — what was decided, the",
        "     numbers that moved it, and what was rejected.",
        "  5. Set this phase's status to \"passed\" and advance current_phase.",
        "  6. sto roadmap render; run the suite; commit.",
    ]
    return "\n".join(lines)
