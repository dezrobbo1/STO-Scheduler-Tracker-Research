"""Exercise the documented P1-G2 launch, not an assumed isolated substitute."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import unittest

from tests.test_p1_g2_execution import ROOT, checkout

ENTRIES = (
    "scripts/evidence/p1_g2_execution.py",
    "scripts/evidence/p1_g2_baseline_diagnostics.py",
)
GUIDE = ROOT / "docs/evidence/p1-g2-baseline-root-causes-2026-09-22.md"


def documented_command(root: Path) -> list[str]:
    line = next(line for line in GUIDE.read_text(encoding="utf-8").splitlines()
                if line.startswith("python3 "))
    words = shlex.split(line.rstrip(" \\"))
    return [sys.executable, *words[1:-1], str(root / words[-1])]


def inputs(root: Path) -> list[str]:
    return [str(root / "baseline.xml"), str(root / "repeat.xml")]


def fingerprints(root: Path) -> dict[str, str]:
    return {name: hashlib.sha256((root / name).read_bytes()).hexdigest()
            for name in ("baseline.xml", "repeat.xml")}


def shadow_environment(root: Path, module: str = "subprocess") -> dict[str, str]:
    shadow = root / "shadow"
    shadow.mkdir(exist_ok=True)
    marker = root / "shadow-imported"
    # The reported subprocess substitution intercepts the handoff. Other early
    # imports use an immediate counterfeit to prove no shadowable import runs.
    payload = (
        "import os, sys\n"
        f"open({str(marker)!r}, 'w').write('executed')\n"
        "def substitute_exec(*args):\n"
        "    output = sys.argv[sys.argv.index('--output') + 1]\n"
        "    open(output, 'w').write('{\"counterfeit\": true}')\n"
        "    raise SystemExit(0)\n"
        + ("os.execv = substitute_exec\n" if module == "subprocess"
           else "substitute_exec()\n")
    )
    (shadow / f"{module}.py").write_text(payload, encoding="utf-8")
    # Startup customization is ignored by the documented interpreter flags;
    # the script-level guard does not claim to undo arbitrary startup hooks.
    (shadow / "sitecustomize.py").write_text(
        f"open({str(root / 'site-imported')!r}, 'w').write('executed')\n",
        encoding="utf-8",
    )
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(shadow)
    environment["PYTHONPYCACHEPREFIX"] = str(root / "caller-cache")
    return environment


class IsolatedLaunchContractTests(unittest.TestCase):
    def test_unisolated_entrypoints_reject_before_shadowable_imports(self):
        for entry in ENTRIES:
            for module in ("subprocess", "argparse", "__future__"):
                with self.subTest(entry=entry, module=module), checkout() as root:
                    environment = shadow_environment(root, module)
                    before = fingerprints(root)
                    output = root / "record.json"
                    completed = subprocess.run(
                        [sys.executable, "-S", str(root / entry), *inputs(root),
                         "--output", str(output)],
                        cwd=root, env=environment, capture_output=True, text=True,
                    )
                    self.assertNotEqual(completed.returncode, 0, completed.stderr)
                    self.assertIn("python3 -I -S -B", completed.stderr)
                    self.assertFalse((root / "shadow-imported").exists())
                    self.assertFalse(output.exists())
                    self.assertEqual(completed.stdout, "")
                    self.assertEqual(fingerprints(root), before)

    def test_each_required_startup_flag_is_checked(self):
        for entry in ENTRIES:
            for flags in ((), ("-S", "-B"), ("-I", "-B"), ("-I", "-S")):
                with self.subTest(entry=entry, flags=flags), checkout() as root:
                    completed = subprocess.run(
                        [sys.executable, *flags, str(root / entry), *inputs(root),
                         "--output", str(root / "record.json")],
                        cwd=root, capture_output=True, text=True,
                    )
                    self.assertNotEqual(completed.returncode, 0, completed.stderr)
                    self.assertIn("python3 -I -S -B", completed.stderr)
                    self.assertFalse((root / "record.json").exists())
                    self.assertEqual(completed.stdout, "")

    def test_documented_command_ignores_shadow_and_preserves_valid_generation(self):
        with checkout() as root:
            environment = shadow_environment(root)
            before = fingerprints(root)
            output = root / "record.json"
            completed = subprocess.run(
                [*documented_command(root), *inputs(root), "--output", str(output)],
                cwd=root, env=environment, capture_output=True, text=True,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(completed.stdout, "")
            self.assertEqual(completed.stderr, "")
            self.assertFalse((root / "shadow-imported").exists())
            self.assertFalse((root / "site-imported").exists())
            record = json.loads(output.read_text(encoding="utf-8"))
            self.assertNotIn("counterfeit", record)
            self.assertFalse(record["classifier_marker"])
            self.assertEqual(record["lineage"]["execution"]["profile"],
                             "sto-p1-g2-verified-source-v1")
            self.assertEqual(fingerprints(root), before)

    def test_documented_command_rejects_missing_fixtures_under_same_shadow(self):
        with checkout(stub=False) as root:
            environment = shadow_environment(root)
            for name in ("baseline.xml", "repeat.xml"):
                (root / name).unlink()
            completed = subprocess.run(
                [*documented_command(root), *inputs(root),
                 "--output", str(root / "record.json")],
                cwd=root, env=environment, capture_output=True, text=True,
            )
            self.assertNotEqual(completed.returncode, 0)
            self.assertIn("BOILER baseline", completed.stderr)
            self.assertEqual(completed.stdout, "")
            self.assertFalse((root / "shadow-imported").exists())
            self.assertFalse((root / "site-imported").exists())
            self.assertFalse((root / "record.json").exists())

    def test_documented_command_keeps_required_output_and_source_alias_guards(self):
        with checkout() as root:
            before = fingerprints(root)
            for output in (None, root / "baseline.xml", root / "repeat.xml"):
                with self.subTest(output=output):
                    args = [*documented_command(root), *inputs(root)]
                    if output is not None:
                        args.extend(["--output", str(output)])
                    completed = subprocess.run(
                        args, cwd=root, capture_output=True, text=True,
                    )
                    self.assertNotEqual(completed.returncode, 0)
                    self.assertIn("--output" if output is None else "aliases",
                                  completed.stderr)
                    self.assertEqual(completed.stdout, "")
                    self.assertEqual(fingerprints(root), before)


if __name__ == "__main__":
    unittest.main()
