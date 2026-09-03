"""Enforces ``PR-migrations``: a migration once written is never rewritten.

The database side is ``scripts/db/apply-migrations.sh``, which refuses a file
whose hash differs from the one it recorded. This is the repository side:
``infra/migrations/CHECKSUMS`` pins every migration's SHA-256, so changing one
means changing the checksum file in the same diff, where a reviewer sees it,
and adding a migration means adding its line. Numbering must be contiguous so a
gap cannot hide a file that was dropped.
"""

from __future__ import annotations

import hashlib
import re
import unittest
from pathlib import Path

MIGRATIONS = Path(__file__).resolve().parent.parent / "infra" / "migrations"
NAME = re.compile(r"^V(\d{3})__[a-z0-9_]+\.sql$")


def _checksums() -> dict[str, str]:
    out: dict[str, str] = {}
    for line in (MIGRATIONS / "CHECKSUMS").read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        digest, _, name = line.partition("  ")
        out[name.strip()] = digest.strip()
    return out


class MigrationImmutabilityTests(unittest.TestCase):
    def setUp(self):
        self.files = sorted(p for p in MIGRATIONS.glob("V*.sql"))
        self.pinned = _checksums()

    def test_there_is_at_least_one_migration(self):
        self.assertTrue(self.files, "PR-migrations is live but infra/migrations is empty")

    def test_every_migration_is_named_and_numbered_contiguously(self):
        numbers = []
        for path in self.files:
            match = NAME.match(path.name)
            self.assertIsNotNone(match, f"{path.name} does not match V###__snake_case.sql")
            numbers.append(int(match.group(1)))  # type: ignore[union-attr]
        self.assertEqual(numbers, list(range(1, len(numbers) + 1)), "numbering has a gap")

    def test_every_migration_matches_its_pinned_checksum(self):
        for path in self.files:
            with self.subTest(path.name):
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
                self.assertIn(
                    path.name,
                    self.pinned,
                    f"{path.name} is not pinned in infra/migrations/CHECKSUMS; add its line",
                )
                self.assertEqual(
                    digest,
                    self.pinned[path.name],
                    f"{path.name} has changed since it was pinned. A migration is never "
                    "rewritten; add the next V### instead.",
                )

    def test_every_pinned_checksum_has_its_file(self):
        names = {path.name for path in self.files}
        for name in self.pinned:
            self.assertIn(name, names, f"CHECKSUMS pins {name}, which no longer exists")
