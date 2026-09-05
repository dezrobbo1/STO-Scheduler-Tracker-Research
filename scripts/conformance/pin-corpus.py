#!/usr/bin/env python3
"""Copy the semantic conformance corpus in from a PM-Software clone and pin it.

    scripts/conformance/pin-corpus.py /path/to/PM-Software <commit>

The clone must contain <commit>; the files are read from that commit with
``git show``, never from the working tree, so a dirty or moved-on clone cannot
leak into the pins. Every file's SHA-256 is written to
``src/sto/conformance/MANIFEST.json``; ``tests/test_conformance_corpus.py``
refuses any later drift between the manifest and the files, and
``sto.conformance.load_case`` refuses a case whose bytes no longer match.

Re-running with a different commit is how the corpus is deliberately moved.
There is no other way.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE = REPO_ROOT / "src" / "sto" / "conformance"
CORPUS = PACKAGE / "corpus"
MANIFEST = PACKAGE / "MANIFEST.json"
UPSTREAM_PATH = "benchmarks/semantic"
REPOSITORY = "dezrobbo1/PM-Software"


def _git(clone: Path, *args: str) -> bytes:
    return subprocess.run(
        ["git", "-C", str(clone), *args], check=True, capture_output=True
    ).stdout


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(__doc__, file=sys.stderr)
        return 2
    clone, commit = Path(argv[1]), argv[2]
    full = _git(clone, "rev-parse", "--verify", f"{commit}^{{commit}}").decode().strip()
    listing = _git(clone, "ls-tree", "-r", "--name-only", full, UPSTREAM_PATH).decode().split()
    if not listing:
        print(f"{full} has nothing under {UPSTREAM_PATH}", file=sys.stderr)
        return 1

    if CORPUS.exists():
        for stale in sorted(CORPUS.rglob("*"), reverse=True):
            stale.unlink() if stale.is_file() else stale.rmdir()
    files: dict[str, str] = {}
    for upstream in sorted(listing):
        relative = upstream[len(UPSTREAM_PATH) + 1 :]
        data = _git(clone, "show", f"{full}:{upstream}")
        target = CORPUS / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        files[relative] = hashlib.sha256(data).hexdigest()

    manifest = {
        "source": {"repository": REPOSITORY, "commit": full, "path": UPSTREAM_PATH},
        "copied_on": dt.date.today().isoformat(),
        "algorithm": "sha256",
        "files": files,
    }
    MANIFEST.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"pinned {len(files)} files from {REPOSITORY}@{full[:7]} into {CORPUS.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
