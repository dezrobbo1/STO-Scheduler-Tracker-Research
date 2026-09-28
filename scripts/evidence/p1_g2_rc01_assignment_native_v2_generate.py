#!/usr/bin/env python3
"""Generate the V2 synthetic MSPDI with V1's frozen semantic case matrix.

Only the project Name/Title identity changes between versions. Importing the
original generator reuses all its pinned task, calendar, resource, assignment,
topology, units and work fields byte-for-byte rather than copying them.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.evidence import p1_g2_rc01_assignment_native_generate as v1

URI = v1.URI
PROJECT_START = v1.PROJECT_START
PROJECT_GUID = v1.PROJECT_GUID
TASK_DURATION = v1.TASK_DURATION
ASSIGNMENT_WORK = v1.ASSIGNMENT_WORK
ASSIGNMENT_UNITS = v1.ASSIGNMENT_UNITS
CALENDARS = v1.CALENDARS
TASKS = v1.TASKS
RESOURCES = v1.RESOURCES
ASSIGNMENTS = v1.ASSIGNMENTS
ASSIGNMENT_ORDER = v1.ASSIGNMENT_ORDER
ASSIGNMENT_ROLES = v1.ASSIGNMENT_ROLES
q = v1.q
add = v1.add

EXPERIMENT_ID = "P1-G2-RC01-ASSIGNMENT-ENVELOPE-NATIVE-MATRIX-V2"
PROJECT_NAME = f"{EXPERIMENT_ID}.xml"
INPUT_BYTES = 20_989
INPUT_SHA256 = "f8c0b622e257186ee30c6b933aedebe697841dc41f72b2c3137ba0f77126cb0c"


def build_fixture() -> bytes:
    original = v1.build_fixture()
    previous_id = v1.EXPERIMENT_ID.encode("ascii")
    assert original.count(previous_id) == 2, "V1 identity insertion changed"
    return original.replace(previous_id, EXPERIMENT_ID.encode("ascii"))


def canonical_import_contract(payload: bytes) -> dict[str, object]:
    return v1.canonical_import_contract(payload)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    payload = build_fixture()
    if len(payload) != INPUT_BYTES or hashlib.sha256(payload).hexdigest() != INPUT_SHA256:
        raise ValueError("V2 generator bytes diverged from the preregistered fixture")
    args.output.write_bytes(payload)
    print(json.dumps({"path": str(args.output), "bytes": len(payload),
                      "sha256": INPUT_SHA256}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
