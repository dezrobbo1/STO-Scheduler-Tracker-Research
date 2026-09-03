"""Documentation must not carry customer schedule content or credentials.

Enforces PR-no-schedule-content from `docs/goals/roadmap.json`.

This repository is public. Real schedules stay outside it (`AGENTS.md`,
`fixtures/README.md`), and a session record is the likeliest place for a task
name or a work-order number to slip in by accident.

The patterns below are *shapes*, not values. Listing the real work-order numbers
or hostnames here would put the very content this guards against into the
repository. Shape-matching catches the mechanical leaks; the judgement ones —
task names, resource descriptions — are the documented policy's job and a
reviewer's.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCANNED = ("docs", "fixtures", "src", "tests", "scripts")
SUFFIXES = {".md", ".json", ".yaml", ".yml", ".txt", ".py"}

PATTERNS: dict[str, re.Pattern[str]] = {
    "work-order number": re.compile(r"\bWO\d{6,}\b"),
    "operation/order pair": re.compile(r"\bWO\d{6,}\s*/\s*\d{2,}\b"),
    # Site schedule exports are named after a numeric job identifier.
    "job-numbered schedule filename": re.compile(r"\bNEW_\d{6,}[-_]"),
    # Loopback and the unspecified address are configuration, not location.
    "routable IPv4 address": re.compile(
        r"\b(?!127\.|0\.0\.0\.0)(?:\d{1,3}\.){3}\d{1,3}\b"
    ),
    "unmasked GitHub token": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}"),
    "Anthropic API key": re.compile(r"\bsk-ant-[A-Za-z0-9_-]{10,}"),
    "private key block": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
}


def _documents() -> list[Path]:
    found: list[Path] = []
    for directory in SCANNED:
        root = REPO / directory
        if not root.is_dir():
            continue
        found.extend(
            path
            for path in root.rglob("*")
            if path.is_file() and path.suffix in SUFFIXES
        )
    return found


class DocumentationHygieneTests(unittest.TestCase):
    def test_no_schedule_content_or_credentials_in_documentation(self):
        offences: list[str] = []
        for path in _documents():
            text = path.read_text(encoding="utf-8", errors="replace")
            for name, pattern in PATTERNS.items():
                match = pattern.search(text)
                if match is None:
                    continue
                line = text[: match.start()].count("\n") + 1
                offences.append(
                    f"{path.relative_to(REPO)}:{line} looks like a {name}"
                )
        self.assertEqual(
            offences,
            [],
            "documentation must not carry customer schedule content or "
            "credentials; see fixtures/README.md:\n  " + "\n  ".join(offences),
        )

    def test_the_scan_covers_code_as_well_as_prose(self):
        """The first real leak this guard found was a work-order number in a
        test fixture literal, not in prose."""

        scanned = {path.suffix for path in _documents()}
        self.assertIn(".py", scanned)

    def test_the_scan_actually_covers_the_history_directory(self):
        """A guard that silently scans nothing is worse than none."""

        scanned = {path.relative_to(REPO).parts[0] for path in _documents()}
        self.assertIn("docs", scanned)
        self.assertTrue(
            any("history" in path.parts for path in _documents()),
            "docs/history is not being scanned",
        )
