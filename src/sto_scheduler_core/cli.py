from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from .mspdi import import_mspdi, inventory_mspdi
from .provenance import canonical_json_bytes, canonical_sha256
from .validation import validate_canonical_schedule


def _write_json(path: Path | None, value: object, *, pretty: bool) -> None:
    if pretty:
        payload = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    else:
        payload = canonical_json_bytes(value).decode("utf-8") + "\n"
    if path is None:
        print(payload, end="")
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(payload, encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sto-scheduler-core")
    subparsers = parser.add_subparsers(dest="command", required=True)

    inventory = subparsers.add_parser(
        "inventory-mspdi", help="Emit a sanitized structural inventory"
    )
    inventory.add_argument("source", type=Path)
    inventory.add_argument("--output", type=Path)

    importer = subparsers.add_parser(
        "import-mspdi", help="Import MSPDI into canonical JSON"
    )
    importer.add_argument("source", type=Path)
    importer.add_argument("--output", type=Path, required=True)
    importer.add_argument("--pretty", action="store_true")

    validator = subparsers.add_parser(
        "validate", help="Validate a canonical JSON document"
    )
    validator.add_argument("source", type=Path)

    digest = subparsers.add_parser(
        "hash", help="Calculate the canonical SHA-256 of a canonical JSON document"
    )
    digest.add_argument("source", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "inventory-mspdi":
        _write_json(args.output, inventory_mspdi(args.source), pretty=True)
        return 0
    if args.command == "import-mspdi":
        document = import_mspdi(args.source)
        _write_json(args.output, document, pretty=args.pretty)
        print(canonical_sha256(document))
        return 0
    if args.command == "validate":
        document = json.loads(args.source.read_text(encoding="utf-8"))
        report = validate_canonical_schedule(document)
        _write_json(None, report.as_dict(), pretty=True)
        return 0 if report.valid else 1
    if args.command == "hash":
        document = json.loads(args.source.read_text(encoding="utf-8"))
        print(canonical_sha256(document))
        return 0
    raise AssertionError(args.command)
