#!/usr/bin/env python3
"""Exercise PL14 through a rendered Chromium page and a real PostgreSQL."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from urllib.request import urlopen

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "synthetic-workspace-chain.mspdi.xml"
EVIDENCE = ROOT / "artifacts" / "pl14-browser"
PORT = 8092
URL = f"http://127.0.0.1:{PORT}"


def wait_for_server() -> None:
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        try:
            with urlopen(URL + "/api/health", timeout=1) as response:  # noqa: S310
                if response.status == 200:
                    return
        except OSError:
            time.sleep(0.2)
    raise RuntimeError("the PL14 application did not become ready")


def start_server(log) -> subprocess.Popen:
    process = subprocess.Popen(
        [sys.executable, "-m", "sto.cli", "serve", "--host", "127.0.0.1", "--port", str(PORT)],
        cwd=ROOT,
        env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
        stdout=log,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    wait_for_server()
    return process


def stop_server(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    os.killpg(process.pid, signal.SIGTERM)
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=5)


def main() -> int:
    if os.environ.get("STO_REQUIRE_DB") == "1" and not os.environ.get(
        "STO_DATABASE_URL"
    ):
        raise RuntimeError("STO_REQUIRE_DB=1 but STO_DATABASE_URL is not configured")
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    log_path = EVIDENCE / "server.log"
    console_errors: list[str] = []
    with log_path.open("w", encoding="utf-8") as log:
        server = start_server(log)
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                context = browser.new_context(
                    viewport={"width": 1440, "height": 1000}, accept_downloads=True
                )
                page = context.new_page()
                page.on(
                    "console",
                    lambda message: console_errors.append(message.text)
                    if message.type == "error"
                    else None,
                )
                page.goto(URL, wait_until="networkidle")
                expect(
                    page.get_by_role("heading", name="Duration scenario planner")
                ).to_be_visible()

                page.get_by_text("Create a project", exact=True).click()
                page.locator("#project-name").fill("PL14 browser acceptance")
                page.locator("#project-timezone").fill("Australia/Perth")
                page.locator("#create-project button").click()
                expect(page.locator("#status")).to_contain_text("Project created")
                # Opening a project before its first import intentionally asks
                # the planner route for state and receives 409/NoSchedule; the
                # page turns that into the import prompt. Chromium logs the
                # controlled HTTP response as a console error, so account for
                # it here while continuing to fail every later console error.
                unexpected = [
                    message for message in console_errors if "409 (Conflict)" not in message
                ]
                if unexpected:
                    raise AssertionError(
                        "browser console errors before import: " + "; ".join(unexpected)
                    )
                console_errors.clear()

                page.locator("#schedule-file").set_input_files(FIXTURE)
                page.locator("#import-schedule button").click()
                expect(page.locator("#status")).to_contain_text("Schedule imported")
                page.locator("#calculate").click()
                expect(page.locator("#status")).to_contain_text("Baseline calculated")
                expect(page.locator("#mode")).to_have_text("baseline")
                expect(page.locator("#chart .bar.baseline").first).to_be_visible()
                expect(page.locator("#summaries tbody tr").first).to_be_visible()

                page.locator("#activity").select_option(label="1.1 — Isolate equipment")
                expect(page.locator("#duration-hours")).to_have_value("4")
                page.locator("#duration-hours").fill("8")
                page.locator("#apply-scenario").click()
                expect(page.locator("#status")).to_contain_text("Scenario calculated and stored")
                expect(page.locator("#mode")).to_have_text("scenario")
                expect(page.locator('tr[data-movement="edited"]')).to_have_count(1)
                if page.locator('tr[data-movement="downstream"]').count() < 1:
                    raise AssertionError("the rendered task table marks no downstream movement")
                if page.locator('.gantt-row[data-movement="downstream"] .bar.scenario').count() < 1:
                    raise AssertionError("the rendered Gantt shows no downstream scenario band")
                page.screenshot(path=EVIDENCE / "scenario-downstream-movement.png", full_page=True)

                page.locator("#reset-scenario").click()
                expect(page.locator("#status")).to_contain_text("Scenario reset")
                expect(page.locator("#mode")).to_have_text("baseline")
                expect(page.locator("#reset-scenario")).to_be_disabled()
                expect(page.locator("#chart .bar.scenario")).to_have_count(0)

                page.locator("#activity").select_option(label="1.1 — Isolate equipment")
                page.locator("#duration-hours").fill("8")
                page.locator("#apply-scenario").click()
                expect(page.locator("#mode")).to_have_text("scenario")

                # Stop and reconstruct the actual process. The browser keeps no
                # scheduling state; after restart it must recover PostgreSQL.
                stop_server(server)
                server = start_server(log)
                page.reload(wait_until="networkidle")
                expect(page.locator("#mode")).to_have_text("scenario")
                expect(page.locator('tr[data-movement="edited"]')).to_have_count(1)
                if page.locator('tr[data-movement="downstream"]').count() < 1:
                    raise AssertionError("downstream movement did not survive application restart")

                with page.expect_download() as download_info:
                    page.locator("#export-scenario").click()
                export_path = EVIDENCE / "prototype-scenario-state.json"
                download_info.value.save_as(export_path)
                exported = json.loads(export_path.read_text(encoding="utf-8"))
                if exported["format"] != "sto-prototype-scenario-state-1":
                    raise AssertionError("export is not labelled as prototype scenario state")
                for required in (
                    "baseline_version_id",
                    "scenario_version_id",
                    "current_version_id",
                    "change",
                    "calculation",
                ):
                    if not exported.get(required):
                        raise AssertionError(f"export has no {required}")
                page.screenshot(path=EVIDENCE / "scenario-after-restart.png", full_page=True)
                browser.close()
        finally:
            stop_server(server)
    if console_errors:
        raise AssertionError("browser console errors: " + "; ".join(console_errors))
    print("PL14 browser acceptance passed: create/import/calculate/edit/move/reset/restart/export")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
