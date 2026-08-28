from __future__ import annotations

import argparse
import json
from pathlib import Path

from sto_scheduler_core import canonical_sha256, import_mspdi
from sto_scheduler_core.calculation_profile import (
    build_calculation_profile,
    build_engine_projection,
    calculate_forward_schedule,
    compare_source_coordinates,
    sanitized_profile_evidence,
)


def _run_pipeline(document: dict[str, object]) -> dict[str, dict[str, object]]:
    profile = build_calculation_profile(document)
    projection = build_engine_projection(document, profile)
    calculation = calculate_forward_schedule(projection)
    comparison = compare_source_coordinates(document, calculation)
    evidence = sanitized_profile_evidence(
        document,
        profile=profile,
        projection=projection,
        calculation=calculation,
        comparison=comparison,
    )
    return {
        "profile": profile,
        "projection": projection,
        "calculation": calculation,
        "comparison": comparison,
        "evidence": evidence,
    }


def _assert_equal(first: object, second: object, label: str) -> None:
    if first != second:
        raise SystemExit(f"Repeated pipeline runs produced different {label}")


def _source_descriptive_values(document: dict[str, object]) -> list[str]:
    values: list[str] = []
    for collection, keys in (
        ("activities", ("name", "notes")),
        ("wbs_nodes", ("name", "notes")),
        ("work_packages", ("name", "notes")),
        ("resources", ("name",)),
        ("calendars", ("name",)),
        ("custom_field_definitions", ("name",)),
    ):
        for item in document.get(collection, []):
            if not isinstance(item, dict):
                continue
            for key in keys:
                value = item.get(key)
                if isinstance(value, str) and value:
                    values.append(value)
    project = document.get("project", {})
    if isinstance(project, dict):
        for key in ("name", "title", "notes"):
            value = project.get(key)
            if isinstance(value, str) and value:
                values.append(value)
    return values


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run the bounded MSPDI v0.1.1 import and calculation-profile trial twice, "
            "then write sanitized evidence only."
        )
    )
    parser.add_argument("source", type=Path, help="External MSPDI/XML source path")
    parser.add_argument("--output", type=Path, required=True, help="Sanitized JSON evidence path")
    parser.add_argument(
        "--expected-source-sha256",
        help="Fail unless the imported source has this exact SHA-256",
    )
    parser.add_argument(
        "--expected-canonical-sha256",
        help="Fail unless the canonical import has this exact SHA-256",
    )
    parser.add_argument(
        "--require-zero-differences",
        action="store_true",
        help="Fail unless every admitted activity exactly matches source Start/Finish",
    )
    args = parser.parse_args()

    source = args.source.resolve()
    output = args.output.resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    if source == output:
        raise ValueError("Evidence output must not overwrite the source XML")

    first_document = import_mspdi(source)
    second_document = import_mspdi(source)
    first_canonical_hash = canonical_sha256(first_document)
    second_canonical_hash = canonical_sha256(second_document)
    if first_canonical_hash != second_canonical_hash:
        raise SystemExit("Repeated imports produced different canonical hashes")
    if (
        args.expected_source_sha256
        and first_document["source"]["sha256"] != args.expected_source_sha256
    ):
        raise SystemExit("Imported source SHA-256 does not match the required source")
    if (
        args.expected_canonical_sha256
        and first_canonical_hash != args.expected_canonical_sha256
    ):
        raise SystemExit("Canonical SHA-256 does not match the required import")

    first_run = _run_pipeline(first_document)
    second_run = _run_pipeline(second_document)
    stage_hashes = {
        stage: (
            canonical_sha256(first_run[stage]),
            canonical_sha256(second_run[stage]),
        )
        for stage in ("profile", "projection", "calculation")
    }
    _assert_equal(first_run["profile"], second_run["profile"], "eligibility profiles")
    _assert_equal(first_run["comparison"], second_run["comparison"], "comparison evidence")
    _assert_equal(first_run["evidence"], second_run["evidence"], "sanitized evidence")
    for stage, (first_hash, second_hash) in stage_hashes.items():
        _assert_equal(first_hash, second_hash, f"{stage} fingerprints")

    first_evidence = first_run["evidence"]
    if (
        args.require_zero_differences
        and first_evidence["comparison"]["coordinate_differences"] != 0
    ):
        raise SystemExit("Coordinate differences remain in the admitted activity cohort")
    first_evidence["reproducibility"] = {
        "pipeline_runs": 2,
        "import_runs": 2,
        "canonical_hashes_equal": True,
        "eligibility_profile_evidence_equal": True,
        "profile_sha256_equal": True,
        "projection_sha256_equal": True,
        "calculation_sha256_equal": True,
        "comparison_evidence_equal": True,
        "sanitized_evidence_equal": True,
    }
    serialized = json.dumps(first_evidence, indent=2, sort_keys=True, ensure_ascii=True) + "\n"
    for value in _source_descriptive_values(first_document):
        if value in serialized:
            raise SystemExit("Sanitized evidence unexpectedly contains source descriptive data")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(serialized, encoding="utf-8")

    print(
        json.dumps(
            {
                "evidence_profile": first_evidence["evidence_profile"],
                "source_sha256": first_evidence["source"]["source_sha256"],
                "canonical_sha256": first_evidence["source"]["canonical_sha256"],
                "eligible_activities": first_evidence["profile_counts"]["eligible_activities"],
                "exact_coordinate_matches": first_evidence["comparison"]["exact_coordinate_matches"],
                "coordinate_differences": first_evidence["comparison"]["coordinate_differences"],
                "output": str(output),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
