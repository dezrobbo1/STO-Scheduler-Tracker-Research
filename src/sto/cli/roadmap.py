"""``sto roadmap`` — read the phase data, render the prose, print the ritual."""

from __future__ import annotations

import argparse

from ..roadmap import (
    ACTIVE_PATH,
    RoadmapError,
    describe,
    evaluate,
    gate_checklist,
    load,
    render_regions,
)


def _status(args: argparse.Namespace) -> int:
    roadmap = load()
    phase = roadmap.phase(roadmap.current_phase)
    met = sum(1 for item in phase["gate"] if item["met"])
    print(f"phase    {phase['id']} — {phase['title']} ({phase['status'].replace('_', ' ')})")
    print(f"gate     {met} of {len(phase['gate'])} criteria met")
    for item in phase["gate"]:
        if not item["met"]:
            blockers = roadmap.blockers_for(item["id"])
            state = "blocked" if blockers else "   open"
            print(f"        {state}: {item['id']}  {item['text']}")
            for blocker in blockers:
                print(f"                 waits on {blocker['id']}")
        elif item.get("evidence_conditional"):
            env = item["evidence_conditional"]["env"]
            print(
                f"           met : {item['id']}  shown by evidence that does not "
                f"always run; {env}=1 makes its absence a failure"
            )

    members = set(phase.get("slices", ()))
    remaining = sum(
        entry["days"]
        for entry in roadmap.slices
        if entry["id"] in members and entry["status"] != "done"
    )
    print(f"effort   {remaining} slice-days left in this phase, before contingency")

    blocked = roadmap.blockers_for(*phase.get("slices", ()))
    if blocked:
        print("\nwaiting on")
        for dep in blocked:
            print(f"  {dep['id']:<22} {dep['what']}")
    at_risk = roadmap.at_risk_for(*phase.get("slices", ()))
    if at_risk:
        print("\nat risk")
        for dep in at_risk:
            print(f"  {dep['id']:<22} {dep['what']}")

    print("\nrules")
    for rule in roadmap.rules:
        arrived = evaluate(rule["live_when"])
        if rule["status"] == "live":
            note = "enforced by " + str(rule["enforced_by"])
            flag = "  " if arrived else "!!"
        else:
            note = f"pending until {describe(rule['live_when'])}"
            # The whole point of the registry: say so the moment it arrives.
            flag = "->" if arrived else "  "
        print(f"  {flag} {rule['id']:<24} {note}")
    if any(
        rule["status"] == "pending" and evaluate(rule["live_when"]) for rule in roadmap.rules
    ):
        print("\n-> machinery has arrived for a pending rule; run the suite for what to do")
    return 0


def _render(args: argparse.Namespace) -> int:
    roadmap = load()
    current = ACTIVE_PATH.read_text(encoding="utf-8")
    updated = render_regions(current, roadmap)
    if args.check:
        if updated != current:
            print("docs/goals/ACTIVE.md generated regions are stale; run: sto roadmap render")
            return 1
        print("docs/goals/ACTIVE.md is up to date")
        return 0
    if updated == current:
        print("docs/goals/ACTIVE.md already up to date")
        return 0
    ACTIVE_PATH.write_text(updated, encoding="utf-8")
    print("docs/goals/ACTIVE.md regions regenerated")
    return 0


def _gate(args: argparse.Namespace) -> int:
    print(gate_checklist(load(), args.phase))
    return 0


def _guarded(handler):
    """Report a malformed roadmap as a message, not a traceback."""

    def run(args: argparse.Namespace) -> int:
        try:
            return handler(args)
        except RoadmapError as error:
            print(f"roadmap: {error}")
            return 1

    return run


def add_subparser(subparsers: argparse._SubParsersAction) -> None:
    roadmap = subparsers.add_parser("roadmap", help="Phases, gates and the rule registry")
    inner = roadmap.add_subparsers(dest="roadmap_command", required=True)

    status = inner.add_parser("status", help="Current phase, open criteria, live rule state")
    status.set_defaults(handler=_guarded(_status))

    render = inner.add_parser("render", help="Regenerate the marked regions of ACTIVE.md")
    render.add_argument(
        "--check", action="store_true", help="Exit non-zero if stale, without writing"
    )
    render.set_defaults(handler=_guarded(_render))

    gate = inner.add_parser("gate", help="Print the ritual for crossing a phase gate")
    gate.add_argument("phase", nargs="?", help="Defaults to the current phase")
    gate.set_defaults(handler=_guarded(_gate))
