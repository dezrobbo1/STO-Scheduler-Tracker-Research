"""Phases, slices, gate criteria and the rule registry.

`AGENTS.md` holds rules that change rarely. This holds everything that changes
as work proceeds, because a document that mixes the two decays at the rate of
its fastest-moving part -- which is what happened to `AGENTS.md` within four
hours of being written.

The registry is the interesting half. Every rule the working agreement states
before it can be enforced carries a predicate saying when its machinery arrives.
A test evaluates those predicates, so a rule marked pending whose machinery has
appeared fails the suite and asks to be promoted. Nobody has to remember.

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

#: Regions of ACTIVE.md regenerated from this data. Everything outside them is
#: hand-written: narrative is judgement, and generating it would mean editing a
#: template to change a sentence.
REGION_NAMES = ("now", "rules")
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

    def phase(self, phase_id: str) -> dict[str, Any]:
        for entry in self.phases:
            if entry["id"] == phase_id:
                return entry
        raise RoadmapError(f"no phase {phase_id!r}")

    @property
    def slice_ids(self) -> frozenset[str]:
        return frozenset(entry["id"] for entry in self.slices)

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

    return Roadmap(
        current_phase=current,
        phases=phases,
        slices=slices,
        rules=rules,
        foreign_prefixes=tuple(payload.get("foreign_prefixes", ())),
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
    for item in phase["gate"]:
        mark = "✓" if item["met"] else "·"
        evidence = f"`{item['evidence']}`" if item["evidence"] else "—"
        lines.append(f"| {mark} | {item['text']} | {evidence} |")
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


_RENDERERS = {"now": _render_now, "rules": _render_rules}


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
        "  1. Every criterion above is [x] and names what shows it.",
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
