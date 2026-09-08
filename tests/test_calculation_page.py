"""The read-only page, checked against the API it claims to read (PL13).

Not a browser test: nothing here renders anything. It asks the one question a
static page can get wrong without anybody noticing, which is whether the routes
and fields it names still exist. A page that fetched a renamed field would show
empty cells and pass every other test in this repository.
"""

from __future__ import annotations

import os
import re
import unittest
from html.parser import HTMLParser
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "src" / "sto" / "api" / "static"

# The page's own consistency needs nothing installed. Comparing it with the
# response models needs pydantic, which the bare suite does not have; the api
# job sets STO_REQUIRE_DB=1 and turns its absence into a failure there.
try:
    from sto.api import schemas
except ImportError as error:  # the bare suite: no api extra
    if os.environ.get("STO_REQUIRE_DB") == "1":
        raise RuntimeError(
            f"STO_REQUIRE_DB=1 but the api extra is missing ({error.name})"
        ) from error
    schemas = None  # type: ignore[assignment]


class _Links(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.assets: list[str] = []
        self.ids: set[str] = set()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "script" and values.get("src"):
            self.assets.append(values["src"])
        if tag == "link" and values.get("href"):
            self.assets.append(values["href"])
        if values.get("id"):
            self.ids.add(values["id"])


class ThePageIsSelfConsistentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.html = (STATIC / "index.html").read_text(encoding="utf-8")
        self.script = (STATIC / "app.js").read_text(encoding="utf-8")
        self.parser = _Links()
        self.parser.feed(self.html)

    def test_every_asset_it_asks_for_is_there(self):
        """A relative href is a file that must exist beside the page.

        An inline ``data:`` URI asks the server for nothing -- the page uses one
        to stop the browser's automatic favicon request becoming a 404 in the
        console -- so it is not an asset and there is nothing to find.
        """

        requested = [asset for asset in self.parser.assets if not asset.startswith("data:")]
        self.assertTrue(requested, "the page requests no assets; this would pass vacuously")
        for asset in requested:
            with self.subTest(asset):
                self.assertTrue((STATIC / asset).is_file(), f"{asset} is not in {STATIC}")

    def test_every_element_the_script_reaches_for_exists_in_the_page(self):
        wanted = set(re.findall(r'querySelector\("#([\w-]+)', self.script))
        self.assertTrue(wanted, "the script selects nothing; this test would pass vacuously")
        self.assertEqual(sorted(wanted - self.parser.ids), [])


@unittest.skipUnless(schemas is not None, "the api extra is not installed")
class ThePageAndTheApiAgreeTests(unittest.TestCase):
    """The fields it reads are the fields the responses declare."""

    def setUp(self) -> None:
        self.script = (STATIC / "app.js").read_text(encoding="utf-8")

    def test_the_routes_it_fetches_are_the_routes_that_exist(self):
        from sto.api.app import create_app

        app = create_app(workspace=None)  # type: ignore[arg-type]
        routes = {getattr(route, "path", "") for route in app.routes}
        for path in (
            "/api/projects",
            "/api/projects/{project_id}/calculations",
            "/api/projects/{project_id}/calculations/latest",
        ):
            with self.subTest(path):
                self.assertIn(path, routes)

    def test_the_row_fields_it_reads_are_declared_by_the_response(self):
        declared = set(schemas.ActivityRow.model_fields)
        read = set(re.findall(r"\brow\.(\w+)", self.script))
        self.assertTrue(read, "the script reads no row fields; this would pass vacuously")
        self.assertEqual(sorted(read - declared), [])

    def test_the_header_fields_it_reads_are_declared_too(self):
        declared = set(schemas.CalculationResponse.model_fields)
        read = set(re.findall(r"\bresult\.(\w+)", self.script))
        self.assertTrue(read)
        self.assertEqual(sorted(read - declared), [])

    def test_the_counts_it_names_are_the_counts_the_workspace_produces(self):
        named = set(re.findall(r"\bcounts\.(\w+)", self.script))
        produced = {
            "activities",
            "scheduled",
            "summaries",
            "compared_with_source",
            "agreeing_with_source",
        }
        self.assertTrue(named)
        self.assertEqual(sorted(named - produced), [])


if __name__ == "__main__":
    unittest.main()
