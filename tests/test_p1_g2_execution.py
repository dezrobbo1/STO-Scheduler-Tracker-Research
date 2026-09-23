"""The P1-G2 record producer uses verified source, not caller-resident code."""
from __future__ import annotations

from contextlib import contextmanager, redirect_stderr, redirect_stdout
import hashlib
import importlib.util
import io
import json
import marshal
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from scripts.evidence import p1_g2_baseline_diagnostics as diagnostic
from scripts.evidence.p1_g2_execution import DiagnosticError, EXECUTION_PATH, TOOL_PATH

ROOT = Path(__file__).resolve().parents[1]
CLASSIFIER = "tests/controlled_native_progress_evidence.py"
# A synthetic record stub isolates execution provenance without requiring private
# schedules. Exact external-fixture comparison remains in its own required test.
STUB = '''

def _build_record(baseline_path, repeat_path):
    return {
        "lineage": {
            "production_basis": _VERIFIED_PRODUCTION_BASIS,
            "evidence_tool": _evidence_tool_identity(),
        },
        "classifier_marker": getattr(
            sys.modules["tests.controlled_native_progress_evidence"],
            "_LINEAGE_PROBE", False,
        ),
        "tool_marker": globals().get("_LINEAGE_PROBE", False),
    }
'''


@contextmanager
def checkout(*, stub=True):
    """A disposable checkout containing real pinned calculation source."""
    with tempfile.TemporaryDirectory(prefix="sto-source-execution-test-") as directory:
        root = Path(directory)
        for relative in ("src/sto/core", "src/sto/legacy"):
            shutil.copytree(ROOT / relative, root / relative,
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        for relative in ("src/sto/__init__.py", CLASSIFIER, TOOL_PATH, EXECUTION_PATH):
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / relative, target)
        (root / ".gitignore").write_text("__pycache__/\n*.pyc\n", encoding="utf-8")
        subprocess.run(["git", "init", "-q", str(root)], check=True)
        subprocess.run(["git", "-C", str(root), "add", "."], check=True)
        # Verification checks actual blobs and the pinned path-tree digest; a
        # commit object is deliberately unnecessary, as in shallow hosted CI.
        if stub:
            with (root / TOOL_PATH).open("a", encoding="utf-8") as stream:
                stream.write(STUB)
        (root / "baseline.xml").write_bytes(b"baseline source\n")
        (root / "repeat.xml").write_bytes(b"repeat source\n")
        yield root


def poison_cache(path: Path) -> None:
    source = path.read_bytes()
    metadata = path.stat()
    code = compile(source + b"\nraise RuntimeError('poisoned cache executed')\n",
                   str(path), "exec")
    cache = Path(importlib.util.cache_from_source(str(path)))
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_bytes(importlib.util.MAGIC_NUMBER
                      + struct.pack("<III", 0, int(metadata.st_mtime), len(source))
                      + marshal.dumps(code))


def command(root: Path, *, entry=TOOL_PATH):
    return [sys.executable, "-I", "-S", "-B", str(root / entry),
            str(root / "baseline.xml"), str(root / "repeat.xml"),
            "--output", str(root / "record.json")]


class VerifiedSourceExecutionTests(unittest.TestCase):
    def test_source_command_bypasses_poisoned_tool_helper_and_classifier_caches(self):
        with checkout() as root:
            for relative in (TOOL_PATH, EXECUTION_PATH, CLASSIFIER):
                poison_cache(root / relative)
            completed = subprocess.run(command(root), capture_output=True, text=True)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(completed.stdout, "")
            record = json.loads((root / "record.json").read_text())
            self.assertFalse(record["tool_marker"])
            self.assertFalse(record["classifier_marker"])
            for key, relative in (("evidence_tool", TOOL_PATH),
                                  ("execution", EXECUTION_PATH)):
                payload = (root / relative).read_bytes()
                self.assertEqual(record["lineage"][key]["bytes"], len(payload))
                self.assertEqual(record["lineage"][key]["sha256"],
                                 hashlib.sha256(payload).hexdigest())
            self.assertEqual(record["lineage"]["execution"]["production_imports"],
                             "compiled_from_verified_retained_bytes")

    def test_changed_source_is_refused_before_its_import_side_effect(self):
        with checkout() as root:
            marker = root / "unverified-import-executed"
            with (root / CLASSIFIER).open("a", encoding="utf-8") as stream:
                stream.write(f"\nfrom pathlib import Path\nPath({str(marker)!r}).touch()\n")
            completed = subprocess.run(command(root), capture_output=True, text=True)
            self.assertNotEqual(completed.returncode, 0)
            self.assertIn("production basis", completed.stderr)
            self.assertFalse(marker.exists())
            self.assertFalse((root / "record.json").exists())
            self.assertEqual((root / "baseline.xml").read_bytes(), b"baseline source\n")

    def test_import_restore_cannot_reuse_the_callers_loaded_classifier(self):
        with checkout() as root:
            probe = r'''
from pathlib import Path
import json, sys
root = Path(sys.argv[1]); sys.path[:0] = [str(root), str(root / "src")]
p = root / "tests/controlled_native_progress_evidence.py"
source = p.read_bytes()
p.write_bytes(source + b"\n_LINEAGE_PROBE=True\n")
try:
    import scripts.evidence.p1_g2_baseline_diagnostics as d
finally:
    p.write_bytes(source)
assert sys.modules["tests.controlled_native_progress_evidence"]._LINEAGE_PROBE
assert d.verify_production_basis()["verified_against_worktree"]
result = d.build_record(root / "baseline.xml", root / "repeat.xml")
print(json.dumps(result))
'''
            completed = subprocess.run([sys.executable, "-I", "-S", "-B", "-c",
                                        probe, str(root)], capture_output=True, text=True)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertFalse(json.loads(completed.stdout)["classifier_marker"])

    def _public_builder_with_restored_helper(self, *, stub):
        with checkout(stub=stub) as root:
            if not stub:
                (root / "baseline.xml").unlink()
                (root / "repeat.xml").unlink()
            probe = r'''
from pathlib import Path
import json, sys
root = Path(sys.argv[1]); sys.path[:0] = [str(root), str(root / "src")]
substitute = root / "substituted_worker.py"
marker = root / "substituted-worker-ran"
substitute.write_text(
    "from pathlib import Path\nimport json, sys\n"
    + f"Path({str(marker)!r}).touch()\n"
    + "Path(sys.argv[sys.argv.index('--output') + 1]).write_text("
      "json.dumps({'counterfeit': True}))\n"
)
helper = root / "scripts/evidence/p1_g2_execution.py"
source = helper.read_bytes()
helper.write_bytes(source + f"\nEXECUTION_PATH = {str(substitute)!r}\n".encode())
try:
    import scripts.evidence.p1_g2_execution as resident
finally:
    helper.write_bytes(source)
assert resident.EXECUTION_PATH == str(substitute)
import scripts.evidence.p1_g2_baseline_diagnostics as d
try:
    result = d.build_record(root / "baseline.xml", root / "repeat.xml")
except d.DiagnosticError as error:
    outcome = {"accepted": False, "error": str(error)}
else:
    outcome = {"accepted": True, "record": result}
assert helper.read_bytes() == source
outcome["substituted_worker_ran"] = marker.exists()
print(json.dumps(outcome))
'''
            completed = subprocess.run(
                [sys.executable, "-I", "-S", "-B", "-c", probe, str(root)],
                capture_output=True, text=True,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            return json.loads(completed.stdout)

    def test_restored_resident_helper_cannot_substitute_the_public_worker(self):
        outcome = self._public_builder_with_restored_helper(stub=False)
        self.assertFalse(outcome["accepted"], outcome)
        self.assertFalse(outcome["substituted_worker_ran"])
        self.assertIn("BOILER baseline", outcome["error"])

    def test_restored_resident_helper_keeps_the_real_worker_counter_case(self):
        outcome = self._public_builder_with_restored_helper(stub=True)
        self.assertTrue(outcome["accepted"], outcome)
        self.assertFalse(outcome["substituted_worker_ran"])
        record = outcome["record"]
        self.assertNotIn("counterfeit", record)
        self.assertFalse(record["tool_marker"])
        self.assertFalse(record["classifier_marker"])
        self.assertEqual(record["lineage"]["execution"]["profile"],
                         "sto-p1-g2-verified-source-v1")

    def test_public_builder_refuses_missing_or_symlinked_worker(self):
        for replacement in ("missing", "symlink"):
            with self.subTest(replacement=replacement), checkout() as root:
                probe = r'''
from pathlib import Path
import sys
root = Path(sys.argv[1]); sys.path[:0] = [str(root), str(root / "src")]
import scripts.evidence.p1_g2_baseline_diagnostics as d
helper = root / "scripts/evidence/p1_g2_execution.py"
helper.unlink()
marker = root / "substituted-worker-ran"
if sys.argv[2] == "symlink":
    substitute = root / "substituted_worker.py"
    substitute.write_text(f"from pathlib import Path\nPath({str(marker)!r}).touch()\n")
    helper.symlink_to(substitute)
try:
    d.build_record(root / "baseline.xml", root / "repeat.xml")
except d.DiagnosticError as error:
    assert "sibling" in str(error), str(error)
else:
    raise AssertionError("missing/nonregular worker accepted")
assert not marker.exists()
'''
                completed = subprocess.run(
                    [sys.executable, "-I", "-S", "-B", "-c", probe,
                     str(root), replacement], capture_output=True, text=True,
                )
                self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_retained_verified_bytes_survive_a_change_between_check_and_import(self):
        with checkout() as root:
            probe = r'''
from pathlib import Path
import importlib.util, json, sys
root = Path(sys.argv[1])
path = root / "scripts/evidence/p1_g2_execution.py"
name = "execution_probe"
spec = importlib.util.spec_from_file_location(name, path)
m = importlib.util.module_from_spec(spec); sys.modules[name] = m
spec.loader.exec_module(m)
original = m.VerifiedSources.exec_module
changed = []
def replace_at_import(self, module):
    if module.__name__ == "tests.controlled_native_progress_evidence":
        p = root / "tests/controlled_native_progress_evidence.py"
        p.write_bytes(p.read_bytes() + b"\n_LINEAGE_PROBE=True\n")
        changed.append(True)
    return original(self, module)
m.VerifiedSources.exec_module = replace_at_import
tool = m.load_verified_diagnostic(root=root)
print(json.dumps({"changed": bool(changed), "marker": getattr(
    sys.modules["tests.controlled_native_progress_evidence"], "_LINEAGE_PROBE", False)}))
'''
            completed = subprocess.run([sys.executable, "-I", "-S", "-B", "-c",
                                        probe, str(root)], capture_output=True, text=True)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(json.loads(completed.stdout), {"changed": True, "marker": False})

    def test_in_process_private_builder_does_not_issue_a_verified_record(self):
        with self.assertRaisesRegex(DiagnosticError, "verified source worker"):
            diagnostic._build_record(Path("unused.xml"), Path("unused-repeat.xml"))

    def test_uncontrolled_worker_refuses_preloaded_calculation_modules(self):
        with checkout() as root:
            probe = r'''
from pathlib import Path
import importlib.util, sys
root = Path(sys.argv[1]); sys.path[:0] = [str(root), str(root / "src")]
from scripts.evidence.p1_g2_execution import load_verified_diagnostic, DiagnosticError
import sto
try:
    load_verified_diagnostic(root=root)
except DiagnosticError as error:
    assert "loaded before source verification" in str(error)
else:
    raise AssertionError("worker accepted a resident calculation module")
'''
            completed = subprocess.run([sys.executable, "-I", "-S", "-B", "-c",
                                        probe, str(root)], capture_output=True, text=True)
            self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_verified_source_loader_preserves_real_synthetic_calculation(self):
        fixture = ROOT / "tests/fixtures/synthetic-workspace-chain.mspdi.xml"
        expected = diagnostic._calculate(diagnostic._load(fixture.read_bytes()))
        expected_rows = {
            str(uid): [value.isoformat() if hasattr(value, "isoformat") else value
                       for value in row]
            for uid, row in expected.result.items()
        }
        with checkout(stub=False) as root:
            probe = r'''
from pathlib import Path
import importlib.util, json, sys
root = Path(sys.argv[1])
p = root / "scripts/evidence/p1_g2_execution.py"
spec = importlib.util.spec_from_file_location("execution_probe", p)
m = importlib.util.module_from_spec(spec); sys.modules[spec.name] = m
spec.loader.exec_module(m)
tool = m.load_verified_diagnostic(root=root)
result = tool._calculate(tool._load(Path(sys.argv[2]).read_bytes()))
print(json.dumps({str(uid): [v.isoformat() if hasattr(v, "isoformat") else v
                            for v in row] for uid, row in result.result.items()}))
'''
            completed = subprocess.run(
                [sys.executable, "-I", "-S", "-B", "-c", probe, str(root), str(fixture)],
                capture_output=True, text=True,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertTrue(expected_rows)
            self.assertEqual(json.loads(completed.stdout), expected_rows)

    def test_source_worker_preserves_real_fixture_rejection(self):
        with checkout(stub=False) as root:
            completed = subprocess.run(command(root), capture_output=True, text=True)
            self.assertNotEqual(completed.returncode, 0)
            self.assertIn("BOILER baseline", completed.stderr)
            self.assertFalse((root / "record.json").exists())

    def test_required_output_prevents_the_original_stdout_append_corruption(self):
        with tempfile.TemporaryDirectory() as directory:
            baseline = Path(directory) / "baseline.xml"
            repeat = Path(directory) / "repeat.xml"
            baseline.write_bytes(b"baseline source\n")
            repeat.write_bytes(b"repeat source\n")
            with baseline.open("a") as stdout, redirect_stdout(stdout), \
                    redirect_stderr(io.StringIO()), \
                    patch.object(diagnostic, "build_record") as build:
                with self.assertRaises(SystemExit) as raised:
                    diagnostic.main([str(baseline), str(repeat)])
                self.assertEqual(raised.exception.code, 2)
            build.assert_not_called()
            self.assertEqual(baseline.read_bytes(), b"baseline source\n")
            self.assertEqual(repeat.read_bytes(), b"repeat source\n")

    def test_controlled_cli_keeps_stdout_fixture_unchanged(self):
        with checkout() as root:
            baseline = root / "baseline.xml"
            with baseline.open("ab") as stdout:
                completed = subprocess.run(command(root), stdout=stdout,
                                           stderr=subprocess.PIPE)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(baseline.read_bytes(), b"baseline source\n")
            self.assertTrue((root / "record.json").is_file())

    def test_controlled_cli_refuses_both_output_fixture_aliases(self):
        with checkout() as root:
            for role in ("baseline.xml", "repeat.xml"):
                with self.subTest(role=role):
                    args = command(root)
                    args[-1] = str(root / role)
                    completed = subprocess.run(args, capture_output=True, text=True)
                    self.assertNotEqual(completed.returncode, 0)
                    self.assertIn("aliases", completed.stderr)
            self.assertEqual((root / "baseline.xml").read_bytes(), b"baseline source\n")
            self.assertEqual((root / "repeat.xml").read_bytes(), b"repeat source\n")


if __name__ == "__main__":
    unittest.main()
