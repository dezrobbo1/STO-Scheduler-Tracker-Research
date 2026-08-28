from __future__ import annotations

import argparse
import json
from pathlib import Path

from sto_scheduler_core import canonical_sha256, import_mspdi
from sto_scheduler_core.calculation_profile import sanitized_profile_evidence


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run the bounded MSPDI v0.1.1 import and calculation-profile trial twice, "
            "then write sanitized evidence only."
        )
    )
    parser.add_argument("source", type=Path, help="External MSPDI/XML source path")
    parser.add_argument("--output", type=Path, required=True, help="Sanitized JSON evidence path")
    args = parser.parse_args()

    first_document = import_mspdi(args.source)
    second_document = import_mspdi(args.source)
    first_canonical_hash = canonical_sha256(first_document)
    second_canonical_hash = canonical_sha256(second_document)
    if first_canonical_hash != second_canonical_hash:
        raise SystemExit("Repeated imports produced different canonical hashes")

    first_evidence = sanitized_profile_evidence(first_document)
    second_evidence = sanitized_profile_evidence(second_document)
    if first_evidence != second_evidence:
        raise SystemExit("Repeated calculation-profile runs produced different evidence")

    first_evidence["reproducibility"] = {
        "import_runs": 2,
        "canonical_hashes_equal": True,
        "profile_evidence_equal": True,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(first_evidence, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    print(
        json.dumps(
            {
                "evidence_profile": first_evidence["evidence_profile"],
                "source_sha256": first_evidence["source"]["source_sha256"],
                "canonical_sha256": first_evidence["source"]["canonical_sha256"],
                "eligible_activities": first_evidence["profile_counts"]["eligible_activities"],
                "coordinate_differences": first_evidence["comparison"]["coordinate_differences"],
                "output": str(args.output),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
