"""``sto`` command line.

Two commands so far, both about the canonical model:

``canonicalise``
    Read a schedule and emit the canonical v1 document and its hash.

``reconcile``
    Read two snapshots of the same schedule and report what identity did:
    how many rows carried their identifiers forward, how many are new, and how
    many the later file no longer carries.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from ..core.hashing import canonical_json_bytes, canonical_sha256
from ..core.model import encode_schedule
from ..core.model.enums import EntityKind
from ..core.model.ids import IdentityMap, ReconciliationReport
from ..core.model.migrate.sto_v011 import migrate
from ..legacy.mspdi import import_mspdi

_KINDS = (
    EntityKind.WBS_NODE,
    EntityKind.ACTIVITY,
    EntityKind.RELATIONSHIP,
    EntityKind.CALENDAR,
    EntityKind.RESOURCE,
    EntityKind.ASSIGNMENT,
)


def _load(path: Path, identity: IdentityMap | None = None, schedule_id: str | None = None):
    return migrate(import_mspdi(str(path)), identity=identity, schedule_id=schedule_id)


def _emit(payload: object, output: Path | None, pretty: bool) -> None:
    if pretty:
        text = json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    else:
        text = canonical_json_bytes(payload).decode("utf-8") + "\n"
    if output is None:
        print(text, end="")
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(text, encoding="utf-8")


def _canonicalise(args: argparse.Namespace) -> int:
    schedule, identity, _ = _load(args.source)
    payload = encode_schedule(schedule)
    digest = canonical_sha256(payload)

    if args.output is not None:
        _emit(payload, args.output, args.pretty)
    if args.identity_out is not None:
        _emit(identity.to_dict(), args.identity_out, args.pretty)

    counts = schedule.counts()
    snapshot = schedule.snapshots[0] if schedule.snapshots else None
    print(f"schedule_id     {schedule.schedule_id}")
    print(f"canonical_sha256 {digest}")
    if snapshot is not None:
        print(f"source_sha256   {snapshot.file_sha256}")
        if snapshot.application_version:
            print(f"written_by      {snapshot.application} {snapshot.application_version}")
    if schedule.project.status_date is not None:
        print(f"status_date     {schedule.project.status_date.isoformat()}")
    for name, value in counts.items():
        if value:
            print(f"{name:<16}{value}")
    if args.output is None and not args.quiet:
        print()
        _emit(payload, None, args.pretty)
    return 0


def _report_line(report: ReconciliationReport, kind: EntityKind, missing: int) -> str:
    entries = report.of_kind(kind)
    matched = sum(1 for entry in entries if str(entry.outcome) == "matched")
    new = sum(1 for entry in entries if str(entry.outcome) == "new")
    rekeyed = sum(1 for entry in entries if str(entry.outcome) == "rekeyed")
    return f"{str(kind):<14}{matched:>8}{new:>8}{rekeyed:>9}{missing:>9}"


def _reconcile(args: argparse.Namespace) -> int:
    earlier, identity, _ = _load(args.earlier)
    _, _, report = _load(args.later, identity=identity, schedule_id=earlier.schedule_id)

    print(f"schedule_id {earlier.schedule_id}")
    print(f"{'kind':<14}{'matched':>8}{'new':>8}{'rekeyed':>9}{'missing':>9}")
    for kind in _KINDS:
        seen = [entry.external_uid for entry in report.of_kind(kind)]
        missing = len(identity.missing_since(kind, seen))
        print(_report_line(report, kind, missing))

    if args.output is not None:
        _emit(report.to_dict(), args.output, args.pretty)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sto", description="STO canonical schedule tooling"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    canonicalise = subparsers.add_parser(
        "canonicalise", help="Read a schedule and emit the canonical v1 document"
    )
    canonicalise.add_argument("source", type=Path)
    canonicalise.add_argument("--output", type=Path)
    canonicalise.add_argument("--identity-out", type=Path)
    canonicalise.add_argument("--pretty", action="store_true")
    canonicalise.add_argument(
        "--quiet", action="store_true", help="Print the summary only, not the document"
    )
    canonicalise.set_defaults(handler=_canonicalise)

    reconcile = subparsers.add_parser(
        "reconcile", help="Report what identity did across two snapshots"
    )
    reconcile.add_argument("earlier", type=Path)
    reconcile.add_argument("later", type=Path)
    reconcile.add_argument("--output", type=Path)
    reconcile.add_argument("--pretty", action="store_true")
    reconcile.set_defaults(handler=_reconcile)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.handler(args))
