from __future__ import annotations

from html.parser import HTMLParser
from importlib import resources
from pathlib import Path
import re
import unittest

from sto.legacy.cli import build_parser


STATIC_DIR = (
    Path(__file__).parents[1]
    / "src"
    / "sto" / "legacy"
    / "workspace_static"
)


class _WorkspaceHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.ids: list[str] = []
        self.asset_urls: list[str] = []

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        attributes = dict(attrs)
        element_id = attributes.get("id")
        if element_id is not None:
            self.ids.append(element_id)
        if tag == "script" and attributes.get("src") is not None:
            self.asset_urls.append(attributes["src"])
        if tag == "link" and attributes.get("href") is not None:
            self.asset_urls.append(attributes["href"])


class WorkspaceStaticContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
        self.javascript = (STATIC_DIR / "app.js").read_text(encoding="utf-8")
        self.styles = (STATIC_DIR / "styles.css").read_text(encoding="utf-8")

    def test_html_ids_are_unique_and_cover_javascript_element_bindings(self) -> None:
        parser = _WorkspaceHTMLParser()
        parser.feed(self.html)

        self.assertEqual(len(parser.ids), len(set(parser.ids)))
        bound_ids = set(
            re.findall(r'document\.querySelector\("#([A-Za-z][\w-]*)"\)', self.javascript)
        )
        self.assertTrue(bound_ids)
        self.assertEqual(bound_ids - set(parser.ids), set())

    def test_workspace_assets_are_local_and_packaged(self) -> None:
        parser = _WorkspaceHTMLParser()
        parser.feed(self.html)
        self.assertEqual(parser.asset_urls, ["/styles.css", "/app.js"])
        self.assertNotRegex(self.styles, r"https?:|@import")

        package = resources.files("sto.legacy").joinpath("workspace_static")
        for filename in ("index.html", "styles.css", "app.js"):
            with self.subTest(filename=filename):
                self.assertTrue(package.joinpath(filename).is_file())

    def test_javascript_uses_the_workspace_api_contract(self) -> None:
        for route in (
            'requestJson("/api/import"',
            "/api/workspaces/${encodeURIComponent(state.view.workspace_id)}/scenario",
            "/api/workspaces/${encodeURIComponent(state.view.workspace_id)}/export",
        ):
            with self.subTest(route=route):
                self.assertIn(route, self.javascript)

    def test_cli_workspace_defaults_to_loopback(self) -> None:
        args = build_parser().parse_args(["workspace"])
        self.assertEqual(args.host, "127.0.0.1")
        self.assertEqual(args.port, 8765)
        self.assertFalse(args.no_open)


if __name__ == "__main__":
    unittest.main()
