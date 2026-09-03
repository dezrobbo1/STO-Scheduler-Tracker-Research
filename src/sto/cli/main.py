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
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from ..core.hashing import canonical_json_bytes, canonical_sha256
from ..core.model import encode_schedule
from ..core.model.enums import EntityKind
from ..core.model.ids import IdentityMap, ReconciliationReport, normalise_guid
from ..core.model.migrate.sto_v011 import migrate
from ..legacy.mspdi import import_mspdi
from . import roadmap as _roadmap

_KINDS = (
    EntityKind.WBS_NODE,
    EntityKind.ACTIVITY,
    EntityKind.RELATIONSHIP,
    EntityKind.CALENDAR,
    EntityKind.RESOURCE,
    EntityKind.ASSIGNMENT,
    EntityKind.UDF,
    EntityKind.BASELINE,
)


def _load(path: Path, identity: IdentityMap | None = None, schedule_id: str | None = None):
    return migrate(import_mspdi(str(path)), identity=identity, schedule_id=schedule_id)


def _load_identity(path: Path) -> IdentityMap:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"unable to read identity map {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise SystemExit(f"identity map must be a JSON object: {path}")
    try:
        return IdentityMap.from_dict(payload)
    except (KeyError, TypeError, ValueError) as exc:
        raise SystemExit(f"invalid identity map {path}: {exc}") from exc


def _declared_project_guid(document: dict[str, Any]) -> str | None:
    """Read the source project's declared GUID without inventing identity."""

    project = document.get("project")
    if not isinstance(project, dict):
        return None
    for entry in project.get("external_references", []) or []:
        if (
            isinstance(entry, dict)
            and entry.get("type") == "GUID"
            and entry.get("value") not in (None, "")
        ):
            return normalise_guid(str(entry["value"]))
    return None


def _same_file(left: Path, right: Path) -> bool:
    """Compare paths by inode when possible, falling back to resolved names."""

    try:
        return left.samefile(right)
    except (FileNotFoundError, OSError):
        return left.resolve() == right.resolve()


def _guard_outputs(source: Path, *outputs: Path | None) -> None:
    """Refuse to write over the source, or to have two outputs collide.

    Imported sources are immutable (AGENTS.md), and a mistyped --output that
    aliases the schedule would destroy a customer file that may have no other
    copy. ``Path.resolve`` catches symlinks and ``samefile`` catches hard links.
    """

    seen: list[tuple[str, Path]] = []
    for name, path in zip(("--output", "--identity-out"), outputs, strict=False):
        if path is None:
            continue
        if _same_file(path, source):
            raise SystemExit(f"{name} would overwrite the source schedule: {source}")
        for previous_name, previous_path in seen:
            if _same_file(path, previous_path):
                raise SystemExit(
                    f"{name} and {previous_name} resolve to the same file: {path}"
                )
        seen.append((name, path))


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
    _guard_outputs(args.source, args.output, args.identity_out)
    prior_identity = _load_identity(args.identity_in) if args.identity_in is not None else None
    if args.identity_in is not None and args.output is not None:
        if _same_file(args.identity_in, args.output):
            raise SystemExit(
                f"--output would overwrite the input identity map: {args.identity_in}"
            )

    document = import_mspdi(str(args.source))
    declared_project_guid = _declared_project_guid(document)
    if (
        prior_identity is not None
        and declared_project_guid is not None
        and declared_project_guid != prior_identity.schedule_id
    ):
        if not args.allow_project_identity_mismatch:
            raise SystemExit(
                "identity map does not belong to the imported project's declared GUID:\n"
                f"  identity map {prior_identity.schedule_id}\n"
                f"  source       {declared_project_guid}\n"
                "Use --allow-project-identity-mismatch only when you have verified "
                "that the files are successive snapshots of the same shutdown."
            )
        print(
            "warning: overriding a project-identity mismatch for canonicalisation\n"
            f"         identity map {prior_identity.schedule_id}\n"
            f"         source       {declared_project_guid}",
            file=sys.stderr,
        )

    schedule, identity, _ = migrate(document, identity=prior_identity)
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


def _report_line(report: ReconciliationReport, kind: EntityKind) -> str:
    entries = report.of_kind(kind)

    def count(outcome: str) -> int:
        return sum(1 for entry in entries if str(entry.outcome) == outcome)

    guid_changed = sum(1 for entry in entries if entry.guid_changed)
    return (
        f"{str(kind):<14}{count('matched'):>8}{count('new'):>8}"
        f"{count('rekeyed'):>9}{count('missing'):>9}{guid_changed:>13}"
    )


def _reconcile(args: argparse.Namespace) -> int:
    _guard_outputs(args.earlier, args.output)
    _guard_outputs(args.later, args.output)
    earlier, identity, _ = _load(args.earlier)
    later_id = _load(args.later)[0].schedule_id
    _, _, report = _load(args.later, identity=identity, schedule_id=earlier.schedule_id)

    if later_id != earlier.schedule_id:
        # Legitimate - the two BOILER snapshots carry different project GUIDs
        # and are still the same schedule - but treating them as one is the
        # operator's judgement, not something the files assert. Saying so keeps
        # a coincidental UID overlap from reading as durable-identity evidence.
        print(
            "warning: the two files declare different project identities\n"
            f"         earlier {earlier.schedule_id}\n"
            f"         later   {later_id}\n"
            "         rows are matched on source UID under the earlier identity",
            file=sys.stderr,
        )

    print(f"schedule_id {earlier.schedule_id}")
    print(
        f"{'kind':<14}{'matched':>8}{'new':>8}{'rekeyed':>9}{'missing':>9}"
        f"{'guid changed':>13}"
    )
    for kind in _KINDS:
        print(_report_line(report, kind))

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
    canonicalise.add_argument(
        "--identity-in",
        type=Path,
        help="Reuse a prior identity map when canonicalising a later snapshot",
    )
    canonicalise.add_argument(
        "--allow-project-identity-mismatch",
        action="store_true",
        help=(
            "Reuse --identity-in despite a different declared project GUID; "
            "only for verified successive snapshots of the same shutdown"
        ),
    )
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

    _roadmap.add_subparser(subparsers)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.handler(args))
