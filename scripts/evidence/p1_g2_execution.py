"""Source-only execution boundary for the fixed P1-G2 diagnostic.

Run this source file with python3 -I -S -B so isolation precedes all imports.
The public diagnostic also delegates here from an isolated child interpreter.
This worker retains verified calculation sources before importing any of them.
It is not a sandbox for an untrusted interpreter or arbitrary hostile code.
"""
# Only the built-in sys module may load before the command's isolation guard.
import sys

if __name__ == "__main__" and not (
    sys.flags.isolated and sys.flags.no_site and sys.flags.dont_write_bytecode
):
    raise SystemExit(
        "Evidence generation requires isolated source execution:\n"
        "python3 -I -S -B scripts/evidence/p1_g2_execution.py "
        "BASELINE REPEAT --output OUTPUT"
    )

import argparse
import hashlib
import importlib.abc
import importlib.util
import os
from pathlib import Path
import stat
import subprocess
from types import ModuleType
from typing import Sequence

_EXECUTED_SOURCE_BYTES = Path(__file__).resolve().read_bytes()
if sys._getframe().f_code != compile(
    _EXECUTED_SOURCE_BYTES, __file__, "exec", dont_inherit=True,
    optimize=sys.flags.optimize,
):
    raise RuntimeError("execution helper bytecode differs from source")

ROOT = Path(__file__).resolve().parents[2]
REPOSITORY_BASE = "1982789f1c0aab83892dbac2f2d7b690ec9a85d6"
PRODUCTION_BASIS_PATHS = (
    "src/sto/core", "src/sto/legacy", "tests/controlled_native_progress_evidence.py",
)
PRODUCTION_BASIS_PATH_TREE_SHA256 = (
    "f7ca47d7e71f9c1e92fd13eaf2b02f351ffb8ca5a8fbb707c51aacb8b8a2ef11"
)
EXECUTION_PATH = "scripts/evidence/p1_g2_execution.py"
TOOL_PATH = "scripts/evidence/p1_g2_baseline_diagnostics.py"
STO_PACKAGE_SHA256 = "59c93d2281f8158499a9dfb80ae661f5b9a2488974bc9c500ba09e954b54cd00"


class DiagnosticError(RuntimeError):
    """The fixed diagnostic execution or evidence contract was not met."""


def _git(
    repository_root: Path,
    *arguments: str,
    check: bool = True,
) -> subprocess.CompletedProcess[bytes]:
    try:
        completed = subprocess.run(
            ("git", *arguments),
            cwd=repository_root,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except OSError as error:  # pragma: no cover - environment failure
        raise DiagnosticError(f"cannot verify production basis: {error}") from error
    if check and completed.returncode != 0:
        detail = completed.stderr.decode("utf-8", errors="replace").strip()
        raise DiagnosticError(
            f"cannot verify production basis with git {' '.join(arguments)}: {detail}"
        )
    return completed


def _worktree_blob_id(
    repository_root: Path,
    relative_path: bytes,
    index_mode: bytes,
    object_format: str,
    captured: dict[str, bytes] | None = None,
) -> bytes:
    try:
        path = repository_root / relative_path.decode("utf-8")
        metadata = path.lstat()
        if index_mode == b"120000":
            if not stat.S_ISLNK(metadata.st_mode):
                raise DiagnosticError("production basis file type differs from its index")
            payload = os.fsencode(os.readlink(path))
        elif index_mode in {b"100644", b"100755"}:
            if not stat.S_ISREG(metadata.st_mode):
                raise DiagnosticError("production basis file type differs from its index")
            executable = bool(metadata.st_mode & stat.S_IXUSR)
            if executable != (index_mode == b"100755"):
                raise DiagnosticError("production basis file mode differs from its index")
            payload = path.read_bytes()
        else:
            raise DiagnosticError(
                f"unsupported production basis index mode {index_mode.decode('ascii')}"
            )
    except (OSError, UnicodeError) as error:
        raise DiagnosticError("cannot read production basis worktree bytes") from error
    if object_format == "sha1":
        digest = hashlib.sha1()
    elif object_format == "sha256":
        digest = hashlib.sha256()
    else:
        raise DiagnosticError(f"unsupported git object format {object_format}")
    if captured is not None:
        if index_mode not in {b"100644", b"100755"}:
            raise DiagnosticError("source execution requires regular tracked files")
        captured[relative_path.decode("utf-8")] = payload
    digest.update(f"blob {len(payload)}\0".encode("ascii"))
    digest.update(payload)
    return digest.hexdigest().encode("ascii")


def verify_production_basis(
    *,
    repository_root: Path = ROOT,
    declared_commit: str = REPOSITORY_BASE,
    production_paths: Sequence[str] = PRODUCTION_BASIS_PATHS,
    expected_path_tree_sha256: str | None = PRODUCTION_BASIS_PATH_TREE_SHA256,
    captured: dict[str, bytes] | None = None,
) -> dict[str, object]:
    """Verify that the calculation code matches its declared immutable basis."""

    commit_probe = _git(
        repository_root,
        "cat-file",
        "-e",
        f"{declared_commit}^{{commit}}",
        check=False,
    )
    if commit_probe.returncode == 0:
        declared_tree_entries = _git(
            repository_root,
            "ls-tree",
            "-r",
            "-z",
            declared_commit,
            "--",
            *production_paths,
        ).stdout
        if not declared_tree_entries:
            raise DiagnosticError("declared production basis contains no tracked paths")
        declared_tree_sha256 = hashlib.sha256(declared_tree_entries).hexdigest()
        if expected_path_tree_sha256 is None:
            expected_path_tree_sha256 = declared_tree_sha256
        elif declared_tree_sha256 != expected_path_tree_sha256:
            raise DiagnosticError(
                "declared production basis does not match its pinned path-tree digest"
            )
    elif expected_path_tree_sha256 is None:
        raise DiagnosticError(
            "declared production basis is unavailable and has no pinned path-tree digest"
        )

    index_entries = _git(
        repository_root,
        "ls-files",
        "--stage",
        "-z",
        "--",
        *production_paths,
    ).stdout
    object_format = (
        _git(repository_root, "rev-parse", "--show-object-format")
        .stdout.decode("ascii")
        .strip()
    )
    tree_entries = bytearray()
    for entry in index_entries.split(b"\0"):
        if not entry:
            continue
        try:
            header, path = entry.split(b"\t", 1)
            mode, object_id, stage = header.split(b" ", 2)
        except ValueError as error:
            raise DiagnosticError("cannot interpret the production basis index") from error
        if stage != b"0":
            raise DiagnosticError(
                "production basis contains an unmerged index entry; refusing stale lineage"
            )
        if _worktree_blob_id(
            repository_root, path, mode, object_format, captured
        ) != object_id:
            raise DiagnosticError(
                "production basis worktree bytes differ from the declared evidence "
                "commit; refusing stale lineage"
            )
        tree_entries.extend(mode + b" blob " + object_id + b"\t" + path + b"\0")
    if not tree_entries:
        raise DiagnosticError("working production basis contains no tracked paths")
    path_tree_sha256 = hashlib.sha256(tree_entries).hexdigest()
    if path_tree_sha256 != expected_path_tree_sha256:
        raise DiagnosticError(
            "production basis differs from the declared evidence commit; "
            f"actual={path_tree_sha256} expected={expected_path_tree_sha256}; "
            "refusing stale lineage"
        )

    worktree_comparison = _git(
        repository_root,
        "diff",
        "--no-ext-diff",
        "--quiet",
        "--",
        *production_paths,
        check=False,
    )
    if worktree_comparison.returncode == 1:
        raise DiagnosticError(
            "production basis differs from the declared evidence commit; "
            "refusing stale lineage"
        )
    if worktree_comparison.returncode != 0:
        detail = worktree_comparison.stderr.decode("utf-8", errors="replace").strip()
        raise DiagnosticError(f"cannot compare production basis: {detail}")
    untracked = _git(
        repository_root,
        "ls-files",
        "--others",
        "--exclude-standard",
        "--",
        *production_paths,
    ).stdout
    if untracked:
        raise DiagnosticError(
            "production basis contains untracked files; refusing stale lineage"
        )
    return {
        "declared_commit": declared_commit,
        "paths": list(production_paths),
        "path_tree_sha256": path_tree_sha256,
        "tracked_entry_count": tree_entries.count(b"\0"),
        "verified_against_worktree": True,
    }


class VerifiedSources(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    """Import only the bytes retained by the pinned production verification."""

    def __init__(self, root: Path, payloads: dict[str, bytes]) -> None:
        self.root = root
        self.modules: dict[str, tuple[str, bytes, bool]] = {}
        for path, payload in payloads.items():
            if not path.endswith(".py"):
                continue
            logical = path.removeprefix("src/")[:-3].replace("/", ".")
            package = logical.endswith(".__init__")
            if package:
                logical = logical.removesuffix(".__init__")
            self.modules[logical] = (path, payload, package)

    def find_spec(self, fullname, path=None, target=None):
        if fullname == "tests":
            return importlib.util.spec_from_loader(fullname, self, is_package=True)
        if fullname in self.modules:
            return importlib.util.spec_from_loader(
                fullname, self, is_package=self.modules[fullname][2]
            )
        if fullname == "sto" or fullname.startswith(("sto.", "tests.")):
            raise DiagnosticError(f"module is outside verified source bundle: {fullname}")
        return None

    def create_module(self, spec):
        return None

    def exec_module(self, module) -> None:
        if module.__name__ == "tests":
            module.__path__ = []
            return
        path, payload, package = self.modules[module.__name__]
        module.__file__ = str(self.root / path)
        if package:
            module.__path__ = []
        exec(compile(payload, module.__file__, "exec", dont_inherit=True), module.__dict__)


def load_verified_diagnostic(*, root: Path = ROOT) -> ModuleType:
    """Verify first, then compile the retained tool and calculation sources."""

    if not sys.flags.isolated or not sys.flags.no_site:
        raise DiagnosticError("record generation requires the isolated source worker")
    if any(name == "sto" or name == "tests" or name.startswith(("sto.", "tests."))
           for name in sys.modules):
        raise DiagnosticError("calculation modules were loaded before source verification")
    payloads: dict[str, bytes] = {}
    basis = verify_production_basis(repository_root=root, captured=payloads)
    package = (root / "src/sto/__init__.py").read_bytes()
    if hashlib.sha256(package).hexdigest() != STO_PACKAGE_SHA256:
        raise DiagnosticError("sto package initializer differs from verified basis")
    payloads["src/sto/__init__.py"] = package
    tool_payload = (root / TOOL_PATH).read_bytes()
    tool_name = "scripts.evidence.p1_g2_baseline_diagnostics"
    # These parents are namespace containers, not another executable input.
    for name in ("scripts", "scripts.evidence"):
        parent = ModuleType(name)
        parent.__path__ = []
        sys.modules[name] = parent
    sys.modules["scripts.evidence.p1_g2_execution"] = sys.modules[__name__]
    finder = VerifiedSources(root, payloads)
    sys.meta_path.insert(0, finder)
    tool = ModuleType(tool_name)
    tool.__file__ = str(root / TOOL_PATH)
    tool.__package__ = "scripts.evidence"
    tool._VERIFIED_TOOL_BYTES = tool_payload
    tool._VERIFIED_PRODUCTION_BASIS = basis
    sys.modules[tool_name] = tool
    try:
        exec(compile(tool_payload, tool.__file__, "exec", dont_inherit=True), tool.__dict__)
    except BaseException:
        sys.meta_path.remove(finder)
        sys.modules.pop(tool_name, None)
        raise
    return tool


def run(baseline: str, repeat: str, output: str) -> None:
    """Generate only through a verified worker and the protected file writer."""

    tool = load_verified_diagnostic()
    fixtures = {"baseline": Path(baseline), "repeat": Path(repeat)}
    destination = Path(output)
    tool.refuse_output_alias(destination, fixtures)
    record = tool._build_record(fixtures["baseline"], fixtures["repeat"])
    # Startup checked the executing module code against these retained bytes.
    # Never attribute execution to a different file read at end-of-run.
    payload = globals().get("_EXECUTED_SOURCE_BYTES")
    if not isinstance(payload, bytes):
        raise DiagnosticError("source worker has no captured execution identity")
    if (ROOT / EXECUTION_PATH).read_bytes() != payload:
        raise DiagnosticError("execution helper changed during generation")
    record["lineage"]["execution"] = {
        "profile": "sto-p1-g2-verified-source-v1",
        "path": EXECUTION_PATH,
        "bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "production_imports": "compiled_from_verified_retained_bytes",
        "sto_package_sha256": STO_PACKAGE_SHA256,
    }
    tool.write_output_safely(destination, tool.canonical_json(record), fixtures)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("baseline")
    parser.add_argument("repeat")
    parser.add_argument("--output", required=True)
    arguments = parser.parse_args()
    run(arguments.baseline, arguments.repeat, arguments.output)
