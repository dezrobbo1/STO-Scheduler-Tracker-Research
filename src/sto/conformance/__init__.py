"""The semantic conformance corpus, copied in and pinned.

The corpus is ``dezrobbo1/PM-Software``'s ``benchmarks/semantic``, taken at the
commit ``MANIFEST.json`` names and copied under ``corpus/`` byte for byte by
``scripts/conformance/pin-corpus.py``. The manifest carries a SHA-256 for every
file. Nothing here reads a case without re-deriving that hash first: a case
whose bytes have drifted from the pin raises :class:`CorpusIntegrityError`
rather than becoming a quietly different oracle.

The corpus bounds the engine's claims (``PR-conformance-suite``), so the one
thing this module must never do is generate or repair expected values. It reads
and it checks; that is all.

The three subsets the roadmap counts -- cases only a native run can answer,
cases that arrive with levelling, and everything else, which the CPM engine
must pass -- are derived here from the cases' own fields, so the roadmap's
numbers are checked against the corpus rather than against a hand count.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

PACKAGE_DIR = Path(__file__).resolve().parent
CORPUS_DIR = PACKAGE_DIR / "corpus"
CASES_DIR = CORPUS_DIR / "cases"
MANIFEST_PATH = PACKAGE_DIR / "MANIFEST.json"

#: The keys of the roadmap's ``conformance`` block that this module derives.
NATIVE_ONLY = "native_validation_only"
LEVELLING_ONLY = "levelling_only"
EXECUTABLE = "executable_by_the_cpm_engine"


class CorpusIntegrityError(RuntimeError):
    """A corpus file is missing, unlisted, or no longer matches its pin."""


@dataclass(frozen=True)
class Manifest:
    repository: str
    commit: str
    upstream_path: str
    copied_on: str
    files: dict[str, str]

    @property
    def case_files(self) -> tuple[str, ...]:
        return tuple(sorted(name for name in self.files if name.startswith("cases/") and name.endswith(".json")))


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_manifest(path: Path = MANIFEST_PATH) -> Manifest:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("algorithm") != "sha256":
        raise CorpusIntegrityError(f"{path}: unsupported algorithm {payload.get('algorithm')!r}")
    source = payload["source"]
    return Manifest(
        repository=source["repository"],
        commit=source["commit"],
        upstream_path=source["path"],
        copied_on=payload["copied_on"],
        files=dict(payload["files"]),
    )


def verify(root: Path = CORPUS_DIR, manifest: Manifest | None = None) -> list[str]:
    """Every way the files on disk and the manifest can disagree, as messages.

    Empty means the copy is exactly what was pinned. Three kinds of drift are
    named separately because they are fixed differently: a *missing* file was
    deleted, a *changed* file was edited, an *unlisted* file was added without
    re-pinning.
    """

    manifest = manifest or load_manifest()
    problems: list[str] = []
    for relative, expected in sorted(manifest.files.items()):
        path = root / relative
        if not path.is_file():
            problems.append(f"missing: {relative}")
        elif sha256_of(path) != expected:
            problems.append(f"changed: {relative}")
    listed = set(manifest.files)
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.relative_to(root).as_posix() not in listed:
            problems.append(f"unlisted: {path.relative_to(root).as_posix()}")
    return problems


def case_ids(manifest: Manifest | None = None) -> tuple[str, ...]:
    """The corpus's case ids as the files spell them: ``sem-rel-001`` and so on."""

    manifest = manifest or load_manifest()
    return tuple(Path(name).stem for name in manifest.case_files)


def load_case(case_id: str, manifest: Manifest | None = None) -> dict[str, Any]:
    """One case, after its bytes have been checked against the pin."""

    manifest = manifest or load_manifest()
    relative = f"cases/{case_id.lower()}.json"
    expected = manifest.files.get(relative)
    if expected is None:
        raise CorpusIntegrityError(f"{case_id}: not a pinned case")
    path = CORPUS_DIR / relative
    if not path.is_file():
        raise CorpusIntegrityError(f"{case_id}: pinned but missing from {CORPUS_DIR}")
    data = path.read_bytes()
    actual = hashlib.sha256(data).hexdigest()
    if actual != expected:
        raise CorpusIntegrityError(
            f"{case_id}: bytes do not match the pin (manifest {expected[:16]}, file {actual[:16]})"
        )
    case = json.loads(data.decode("utf-8"))
    if case.get("case_id", "").lower() != case_id.lower():
        raise CorpusIntegrityError(f"{case_id}: file declares case_id {case.get('case_id')!r}")
    return case


def classify(case: dict[str, Any]) -> str:
    """Which of the roadmap's three subsets a case belongs to, from its own fields.

    A case with no declared reference forecast can only be checked by a native
    run. A case whose expectation includes a resource order is about levelling
    and cannot be answered by a CPM pass. Everything else is the engine's to
    pass.
    """

    expected = case["expected"]
    if expected.get("reference_status") != "declared":
        return NATIVE_ONLY
    if expected.get("resource_order"):
        return LEVELLING_ONLY
    return EXECUTABLE


def census(ids: Iterable[str] | None = None) -> dict[str, int]:
    """Counts by subset plus ``cases_total``, keyed as the roadmap keys them."""

    counts = {NATIVE_ONLY: 0, LEVELLING_ONLY: 0, EXECUTABLE: 0}
    for case_id in ids if ids is not None else case_ids():
        counts[classify(load_case(case_id))] += 1
    counts["cases_total"] = sum(counts.values())
    return counts


def executable_case_ids() -> tuple[str, ...]:
    return tuple(case_id for case_id in case_ids() if classify(load_case(case_id)) == EXECUTABLE)
