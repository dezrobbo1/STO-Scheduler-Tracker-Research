from __future__ import annotations

import argparse
import json
from pathlib import Path

from sto_scheduler_core import canonical_sha256, import_mspdi, inventory_mspdi
from sto_scheduler_core.provenance import canonical_json_bytes


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run a deterministic external MSPDI import trial"
    )
    parser.add_argument("source", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    first = import_mspdi(args.source)
    second = import_mspdi(args.source)
    first_hash = canonical_sha256(first)
    second_hash = canonical_sha256(second)
    if first_hash != second_hash:
        raise SystemExit(
            "Determinism failure: repeated imports produced different canonical hashes"
        )

    canonical_path = args.output_dir / "canonical.json"
    inventory_path = args.output_dir / "inventory.json"
    evidence_path = args.output_dir / "evidence.json"
    canonical_path.write_bytes(canonical_json_bytes(first) + b"\n")
    inventory = inventory_mspdi(args.source)
    inventory_path.write_text(
        json.dumps(inventory, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )
    evidence = {
        "experiment": "external-mspdi-import-determinism-v0.1",
        "source": inventory["source"],
        "canonical_schema_version": first["schema_version"],
        "importer_profile": first["importer_profile"],
        "canonical_sha256_run_1": first_hash,
        "canonical_sha256_run_2": second_hash,
        "deterministic": first_hash == second_hash,
        "counts": inventory["counts"],
        "validation": inventory["validation"],
        "native_project_validation": "not_executed",
    }
    evidence_path.write_text(
        json.dumps(evidence, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )
    print(evidence_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
