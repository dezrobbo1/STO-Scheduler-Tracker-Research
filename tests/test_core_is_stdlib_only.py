"""`sto.core` must depend on the standard library alone.

Enforces PR-core-stdlib-only from `docs/goals/roadmap.json`.

Two reasons, both load-bearing. The canonical model and its hashing have to be
testable without a database or a web framework, so the engine can be exercised
anywhere. And a canonical document must not pass through a validation library
that could reorder, coerce or default a field, because any of those moves the
hash — and the hash is how two imports of one file are shown to agree.

Third-party dependencies belong at the API edge, converting to and from core
dataclasses.
"""

from __future__ import annotations

import ast
import sys
import unittest
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src" / "sto"
#: ``sto.core`` for the reason in AGENTS.md; ``sto.legacy`` because it is the
#: importer and oracle, and a third-party import there would put the file
#: oracle behind the extra the API needs (ADR-005).
CORE = SRC / "core"
GUARDED = (CORE, SRC / "legacy")
STDLIB = set(sys.stdlib_module_names)
FIRST_PARTY = {"sto"}


def _imported_roots(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            # level > 0 is a relative import, which is first-party by definition
            if node.level == 0 and node.module:
                roots.add(node.module.split(".")[0])
    return roots


class CorePurityTests(unittest.TestCase):
    def test_core_imports_nothing_third_party(self):
        offences: list[str] = []
        for path in sorted(p for root in GUARDED for p in root.rglob("*.py")):
            for root in sorted(_imported_roots(path)):
                if root in STDLIB or root in FIRST_PARTY:
                    continue
                offences.append(f"{path.relative_to(CORE.parents[2])} imports {root}")
        self.assertEqual(
            offences,
            [],
            "sto.core must depend on the standard library only; move this to "
            "the API edge:\n  " + "\n  ".join(offences),
        )

    def test_the_scan_found_the_core_package(self):
        """A purity check that silently scans nothing would always pass."""

        modules = [p for root in GUARDED for p in root.rglob("*.py")]
        self.assertGreater(len(modules), 5)
        self.assertTrue(any(path.name == "hashing.py" for path in modules))
