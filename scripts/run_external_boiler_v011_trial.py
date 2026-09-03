from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from sto.legacy import canonical_sha256, import_mspdi  # noqa: E402
from sto.legacy.calculation_eligibility import (  # noqa: E402
    classify_calculation_eligibility,
    sanitized_eligibility_evidence,
)

EXPECTED_BOILER_COUNTS = {
    "tasks": 555,
    "summary_tasks": 95,
    "leaf_activities": 460,
    "milestones": 60,
    "activity_milestones": 58,
    "summary_milestones": 2,
    "relationships": 600,
    "calendars": 45,
    "resources": 32,
    "assignments": 472,
    "custom_field_definitions": 8,
    "baselines": 14,
}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run the external Boiler MSPDI v0.1.1 structural and calculation-eligibility trial. "
            "The source XML and full canonical result remain outside Git."
        )
    )
    parser.add_argument("source", type=Path, help="Path to the external Boiler MSPDI XML")
    parser.add_argument("--output", type=Path, required=True, help="Sanitized JSON evidence path")
    parser.add_argument(
        "--skip-known-count-check",
        action="store_true",
        help="Allow a different source inventory; not permitted for the recorded Boiler evidence run",
    )
    return parser


def _assert_known_boiler(inventory: dict[str, object]) -> None:
    mismatches: list[str] = []
    for key, expected in EXPECTED_BOILER_COUNTS.items():
        actual = inventory.get(key)
        if actual != expected:
            mismatches.append(f"{key}: expected {expected}, got {actual!r}")
    relationship_types = inventory.get("relationship_types")
    if relationship_types != {"FS": 600}:
        mismatches.append(f"relationship_types: expected {{'FS': 600}}, got {relationship_types!r}")
    if mismatches:
        raise RuntimeError("External source does not match the recorded Boiler inventory: " + "; ".join(mismatches))


def main() -> int:
    args = _parser().parse_args()
    source = args.source.resolve()
    output = args.output.resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    if source == output:
        raise ValueError("Evidence output must not overwrite the source XML")

    first = import_mspdi(source)
    second = import_mspdi(source)
    first_hash = canonical_sha256(first)
    second_hash = canonical_sha256(second)
    if first_hash != second_hash:
        raise RuntimeError("Repeated v0.1.1 imports produced different canonical hashes")

    inventory = first["source_inventory"]
    if not args.skip_known_count_check:
        _assert_known_boiler(inventory)

    validation = first.get("import_validation", {})
    if not isinstance(validation, dict) or validation.get("valid") is not True:
        raise RuntimeError(f"Canonical structural validation did not pass: {validation!r}")

    eligibility = classify_calculation_eligibility(first)
    sanitized_eligibility = sanitized_eligibility_evidence(eligibility)

    evidence = {
        "experiment_profile": "boiler-mspdi-v0.1.1-structural-and-eligibility-trial",
        "claim_boundary": (
            "Deterministic structural import and fail-closed eligibility classification only. "
            "No schedule-coordinate equivalence or Microsoft Project compatibility claim."
        ),
        "source": {
            "system": first["source"]["system"],
            "format": first["source"]["format"],
            "namespace": first["source"]["namespace"],
            "sha256": first["source"]["sha256"],
            "byte_length": first["source"]["byte_length"],
            "identity_scope": first["source"]["identity_scope"],
            "document_key": first["source"]["document_key"],
        },
        "canonical": {
            "schema_version": first["schema_version"],
            "importer_profile": first["importer_profile"],
            "sha256": first_hash,
            "repeated_import_sha256_equal": True,
        },
        "source_inventory": inventory,
        "structural_validation": validation,
        "calculation_eligibility": sanitized_eligibility,
        "native_microsoft_project_validation": "not_executed",
        "source_xml_committed": False,
        "full_canonical_output_committed": False,
    }

    serialized = json.dumps(evidence, indent=2, sort_keys=True, ensure_ascii=True) + "\n"
    forbidden_values = []
    for activity in first.get("activities", []):
        if isinstance(activity, dict):
            for key in ("name", "notes"):
                value = activity.get(key)
                if isinstance(value, str) and value:
                    forbidden_values.append(value)
    for value in forbidden_values:
        if value in serialized:
            raise RuntimeError("Sanitized evidence unexpectedly contains a source task name or note")

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(serialized, encoding="utf-8")
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
