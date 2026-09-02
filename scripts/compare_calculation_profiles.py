from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Any

from sto_scheduler_core.profile_comparison import (
    build_sanitized_profile_comparison,
)
from sto_scheduler_core.provenance import canonical_sha256


_PIPELINE_SNIPPET = r"""
from pathlib import Path
import json
import sys

from sto_scheduler_core import import_mspdi
from sto_scheduler_core.calculation_profile import (
    build_calculation_profile,
    build_engine_projection,
    calculate_forward_schedule,
)

source = Path(sys.argv[1])
output = Path(sys.argv[2])
document = import_mspdi(source)
profile = build_calculation_profile(document)
projection = build_engine_projection(document, profile)
calculation = calculate_forward_schedule(projection)
output.write_text(
    json.dumps(
        {
            "document": document,
            "profile": profile,
            "calculation": calculation,
        },
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ),
    encoding="utf-8",
)
"""


def _run_checkout_pipeline(
    root: Path, source: Path, output: Path
) -> dict[str, Any]:
    src = root / "src"
    if not src.is_dir():
        raise FileNotFoundError(f"Checkout has no src directory: {root}")
    env = os.environ.copy()
    existing = env.get("PYTHONPATH")
    env["PYTHONPATH"] = (
        str(src) if not existing else os.pathsep.join((str(src), existing))
    )
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            _PIPELINE_SNIPPET,
            str(source),
            str(output),
        ],
        cwd=root,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise RuntimeError(
            f"Calculation pipeline failed in {root}: {detail}"
        )
    value = json.loads(output.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Pipeline output from {root} is not an object")
    return value


def _assert_sanitized(value: object) -> None:
    if isinstance(value, list):
        raise ValueError("Sanitized comparison must not contain arrays")
    if isinstance(value, str) and (
        value.startswith("task:") or value.startswith("relationship:")
    ):
        raise ValueError("Sanitized comparison contains a raw canonical id")
    if isinstance(value, dict):
        for child in value.values():
            _assert_sanitized(child)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run the same external MSPDI source through two repository checkouts, "
            "then write a sanitized calculation-profile cohort comparison."
        )
    )
    parser.add_argument(
        "source", type=Path, help="External MSPDI/XML source path"
    )
    parser.add_argument(
        "--baseline-root",
        type=Path,
        required=True,
        help="Checkout/worktree containing the baseline calculation profile",
    )
    parser.add_argument(
        "--candidate-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="Checkout containing the candidate profile; defaults to this repository",
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Sanitized JSON comparison output path",
    )
    parser.add_argument(
        "--expected-source-sha256",
        help="Fail unless both checkouts import this exact source SHA-256",
    )
    parser.add_argument(
        "--expected-canonical-sha256",
        help="Fail unless both checkouts produce this canonical SHA-256",
    )
    parser.add_argument(
        "--require-zero-differences",
        action="store_true",
        help="Fail unless every newly admitted candidate activity matches source Start/Finish",
    )
    args = parser.parse_args()

    source = args.source.resolve()
    baseline_root = args.baseline_root.resolve()
    candidate_root = args.candidate_root.resolve()
    output = args.output.resolve()

    if not source.is_file():
        raise FileNotFoundError(source)
    if not baseline_root.is_dir():
        raise NotADirectoryError(baseline_root)
    if not candidate_root.is_dir():
        raise NotADirectoryError(candidate_root)
    if output == source:
        raise ValueError("Comparison output must not overwrite the source XML")

    with tempfile.TemporaryDirectory(
        prefix="sto-profile-comparison-"
    ) as directory:
        temporary = Path(directory)
        baseline_first = _run_checkout_pipeline(
            baseline_root, source, temporary / "baseline-first.json"
        )
        baseline_second = _run_checkout_pipeline(
            baseline_root, source, temporary / "baseline-second.json"
        )
        candidate_first = _run_checkout_pipeline(
            candidate_root, source, temporary / "candidate-first.json"
        )
        candidate_second = _run_checkout_pipeline(
            candidate_root, source, temporary / "candidate-second.json"
        )

    if canonical_sha256(baseline_first) != canonical_sha256(
        baseline_second
    ):
        raise SystemExit("Baseline checkout pipeline is not deterministic")
    if canonical_sha256(candidate_first) != canonical_sha256(
        candidate_second
    ):
        raise SystemExit("Candidate checkout pipeline is not deterministic")

    baseline_document = baseline_first["document"]
    candidate_document = candidate_first["document"]
    baseline_canonical = canonical_sha256(baseline_document)
    candidate_canonical = canonical_sha256(candidate_document)
    if baseline_canonical != candidate_canonical:
        raise SystemExit(
            "Baseline and candidate checkouts produced different canonical documents"
        )

    baseline_source = baseline_document["source"]["sha256"]
    candidate_source = candidate_document["source"]["sha256"]
    if baseline_source != candidate_source:
        raise SystemExit(
            "Baseline and candidate checkouts imported different source identities"
        )
    if (
        args.expected_source_sha256
        and baseline_source != args.expected_source_sha256
    ):
        raise SystemExit("Source SHA-256 does not match the required source")
    if (
        args.expected_canonical_sha256
        and baseline_canonical != args.expected_canonical_sha256
    ):
        raise SystemExit(
            "Canonical SHA-256 does not match the required import"
        )

    comparison = build_sanitized_profile_comparison(
        candidate_document,
        baseline_first["profile"],
        candidate_first["profile"],
        candidate_first["calculation"],
    )
    comparison["reproducibility"] = {
        "baseline_pipeline_runs": 2,
        "candidate_pipeline_runs": 2,
        "baseline_pipeline_equal": True,
        "candidate_pipeline_equal": True,
        "source_sha256_equal": True,
        "canonical_sha256_equal": True,
    }
    if (
        args.require_zero_differences
        and comparison["changed_cohort_comparison"][
            "coordinate_differences"
        ]
        != 0
    ):
        raise SystemExit(
            "Coordinate differences remain in the newly admitted cohort"
        )

    _assert_sanitized(comparison)
    serialized = (
        json.dumps(
            comparison, indent=2, sort_keys=True, ensure_ascii=True
        )
        + "\n"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(serialized, encoding="utf-8")

    print(
        json.dumps(
            {
                "baseline_profile": comparison["baseline"][
                    "calculation_profile"
                ],
                "candidate_profile": comparison["candidate"][
                    "calculation_profile"
                ],
                "newly_eligible_activities": comparison[
                    "changed_cohorts"
                ]["newly_eligible_activities"],
                "newly_eligible_relationships": comparison[
                    "changed_cohorts"
                ]["newly_eligible_relationships"],
                "coordinate_differences": comparison[
                    "changed_cohort_comparison"
                ]["coordinate_differences"],
                "output": str(output),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
