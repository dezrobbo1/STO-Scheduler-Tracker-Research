#!/usr/bin/env python3
"""Exercise PL14 behind PL2 authentication in Chromium and PostgreSQL."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from urllib.request import urlopen

import pyotp
from cryptography.fernet import Fernet
from playwright.sync_api import expect, sync_playwright

from sto.api.auth import AuthConfig, AuthService
from sto.persistence.db import connect

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "synthetic-workspace-chain.mspdi.xml"
EVIDENCE = ROOT / "artifacts" / "pl2-browser"
PORT = 8092
URL = f"http://127.0.0.1:{PORT}"


def wait_for_server() -> None:
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        try:
            with urlopen(URL + "/healthz", timeout=1) as response:  # noqa: S310
                if response.status == 200:
                    return
        except OSError:
            time.sleep(0.2)
    raise RuntimeError("the PL14 application did not become ready")


def start_server(log, master_key: str) -> subprocess.Popen:
    process = subprocess.Popen(
        [sys.executable, "-m", "sto.cli", "serve", "--host", "127.0.0.1", "--port", str(PORT)],
        cwd=ROOT,
        env={
            **os.environ,
            "PYTHONPATH": str(ROOT / "src"),
            "STO_AUTH_MASTER_KEY": master_key,
        },
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
    password = "synthetic-browser-password"
    master_key = Fernet.generate_key().decode("ascii")
    service = AuthService(connect=connect, config=AuthConfig(master_key=master_key.encode()))
    user, totp_secret, _ = service.bootstrap_admin(
        username="browser-planner", password=password, display_name="Browser Planner"
    )

    def otp_after_consumed() -> str:
        with connect() as conn:
            last = conn.execute(
                "SELECT last_totp_counter FROM users WHERE id=%s", (user["id"],)
            ).fetchone()["last_totp_counter"]
        # A long browser run may span multiple TOTP steps, while a very fast
        # one may still be inside the consumed step. Wait only when necessary
        # and submit the real current code rather than manufacturing one from
        # a future counter.
        current = int(time.time()) // 30
        if current <= last:
            time.sleep((last + 1) * 30 - time.time() + 0.1)
        return pyotp.TOTP(totp_secret).now()

    with log_path.open("w", encoding="utf-8") as log:
        server = start_server(log, master_key)
        try:
            with sync_playwright() as playwright:
                executable = os.environ.get("STO_BROWSER_EXECUTABLE")
                browser = playwright.chromium.launch(
                    headless=True,
                    executable_path=executable,
                )
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
                expect(page.get_by_role("heading", name="Sign in")).to_be_visible()
                anonymous_status = page.evaluate(
                    "async () => (await fetch('/api/projects')).status"
                )
                if anonymous_status != 401:
                    raise AssertionError("project API was available before login")
                unexpected = [
                    message for message in console_errors if "401 (Unauthorized)" not in message
                ]
                if unexpected:
                    raise AssertionError(
                        "browser console errors while logged out: " + "; ".join(unexpected)
                    )
                console_errors.clear()

                page.locator("#login-username").fill(user["username"])
                page.locator("#login-password").fill(password)
                page.locator("#login-totp").fill(pyotp.TOTP(totp_secret).now())
                page.locator("#login-button").click()
                expect(page.locator("#account")).to_be_visible()
                expect(page.locator("#actor-name")).to_have_text("Browser Planner")
                expect(page.locator("#planner")).to_be_visible()
                expect(page.locator("#login-password")).to_have_value("")
                expect(page.locator("#login-totp")).to_have_value("")

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
                expect(page.locator("#provenance")).to_contain_text("Forward profile")
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
                before_restart = page.evaluate(
                    """async () => {
                      const project = document.querySelector('#project').value;
                      return (await fetch('/api/projects/' + project + '/planner')).json();
                    }"""
                )
                expected_provenance = {
                    "current_version_id": before_restart["current_version_id"],
                    "canonical_hash": before_restart["scenario"]["canonical_hash"],
                    "calculation_id": before_restart["scenario"]["calculation_id"],
                    "fingerprint": before_restart["scenario"]["fingerprint"],
                }

                # Stop and reconstruct the actual process. The browser keeps no
                # scheduling state; after restart it must recover PostgreSQL.
                stop_server(server)
                server = start_server(log, master_key)
                page.reload(wait_until="networkidle")
                expect(page.locator("#mode")).to_have_text("scenario")
                expect(page.locator('tr[data-movement="edited"]')).to_have_count(1)
                if page.locator('tr[data-movement="downstream"]').count() < 1:
                    raise AssertionError("downstream movement did not survive application restart")
                after_restart = page.evaluate(
                    """async () => {
                      const project = document.querySelector('#project').value;
                      return (await fetch('/api/projects/' + project + '/planner')).json();
                    }"""
                )
                recovered_provenance = {
                    "current_version_id": after_restart["current_version_id"],
                    "canonical_hash": after_restart["scenario"]["canonical_hash"],
                    "calculation_id": after_restart["scenario"]["calculation_id"],
                    "fingerprint": after_restart["scenario"]["fingerprint"],
                }
                if recovered_provenance != expected_provenance:
                    raise AssertionError(
                        "restart changed scenario provenance: "
                        f"{expected_provenance!r} != {recovered_provenance!r}"
                    )

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
                exported_provenance = {
                    "current_version_id": exported["current_version_id"],
                    "canonical_hash": exported["calculation"]["canonical_hash"],
                    "calculation_id": exported["calculation"]["id"],
                    "fingerprint": exported["calculation"]["fingerprint"],
                }
                if exported_provenance != expected_provenance:
                    raise AssertionError(
                        "export changed scenario provenance: "
                        f"{expected_provenance!r} != {exported_provenance!r}"
                    )
                # Logout failures must clear the rendered schedule without
                # claiming the server session was revoked. Recovery reads a
                # fresh session-bound CSRF value before retrying the mutation.
                logout_outcomes = iter(("network", 403, 500, "continue"))

                def intercept_logout(route):
                    outcome = next(logout_outcomes)
                    if outcome == "network":
                        route.abort("connectionfailed")
                    elif isinstance(outcome, int):
                        route.fulfill(
                            status=outcome,
                            content_type="application/json",
                            body=json.dumps({"detail": "synthetic logout failure"}),
                        )
                    else:
                        route.continue_()

                page.route("**/api/auth/logout", intercept_logout)
                page.locator("#logout").click()
                expect(page.get_by_role("heading", name="Sign in")).to_be_visible()
                expect(page.locator("#planner")).to_be_hidden()
                expect(page.locator("#retry-logout")).to_be_visible()
                expect(page.locator("#login-button")).to_be_disabled()
                expect(page.locator("#login-username")).to_be_disabled()
                expect(page.locator("#login-password")).to_be_disabled()
                expect(page.locator("#login-totp")).to_be_disabled()
                expect(page.locator("#auth-status")).to_contain_text(
                    "could not be confirmed"
                )
                self_status = page.evaluate(
                    "async () => (await fetch('/api/auth/session')).status"
                )
                if self_status != 200:
                    raise AssertionError("network logout failure revoked the session")
                console_errors.clear()  # the deliberately aborted request

                page.locator("#retry-logout").click()
                expect(page.locator("#auth-status")).to_contain_text(
                    "could not be confirmed"
                )
                if page.evaluate(
                    "async () => (await fetch('/api/auth/session')).status"
                ) != 200:
                    raise AssertionError("403 logout failure revoked the session")
                console_errors.clear()  # the deliberate 403 response

                page.locator("#retry-logout").click()
                expect(page.locator("#auth-status")).to_contain_text(
                    "could not be confirmed"
                )
                if page.evaluate(
                    "async () => (await fetch('/api/auth/session')).status"
                ) != 200:
                    raise AssertionError("500 logout failure revoked the session")
                console_errors.clear()  # the deliberate 500 response

                page.locator("#retry-logout").click()
                expect(page.locator("#auth-status")).to_contain_text(
                    "server session was revoked"
                )
                expect(page.locator("#retry-logout")).to_be_hidden()
                expect(page.locator("#login-button")).to_be_enabled()
                expect(page.locator("#login-username")).to_be_enabled()
                expect(page.locator("#login-password")).to_be_enabled()
                expect(page.locator("#login-totp")).to_be_enabled()
                page.unroute("**/api/auth/logout")
                logged_out_status = page.evaluate(
                    "async () => (await fetch('/api/projects')).status"
                )
                if logged_out_status != 401:
                    raise AssertionError("project API remained available after logout")
                console_errors[:] = [
                    message for message in console_errors if "401 (Unauthorized)" not in message
                ]

                page.locator("#login-username").fill(user["username"])
                page.locator("#login-password").fill(password)
                page.locator("#login-totp").fill(otp_after_consumed())
                page.locator("#login-button").click()
                expect(page.locator("#mode")).to_have_text("scenario")

                stop_server(server)
                server = start_server(log, master_key)
                page.reload(wait_until="networkidle")
                expect(page.locator("#actor-name")).to_have_text("Browser Planner")
                expect(page.locator("#mode")).to_have_text("scenario")
                expect(page.locator('tr[data-movement="edited"]')).to_have_count(1)
                persisted = page.evaluate(
                    """async () => {
                      const project = document.querySelector('#project').value;
                      return (await fetch('/api/projects/' + project + '/planner')).json();
                    }"""
                )
                if persisted["current_version_id"] != expected_provenance["current_version_id"]:
                    raise AssertionError("authenticated scenario did not survive the final restart")
                page.screenshot(path=EVIDENCE / "scenario-after-restart.png", full_page=True)
                browser.close()
        finally:
            stop_server(server)
    # Chromium can report an in-flight resource fetch as connection-refused
    # while this acceptance test deliberately stops the application process.
    # The post-restart page/API/provenance assertions above still prove that
    # both reconstructed processes became usable; retain every other console
    # error as a failure.
    unexpected_console_errors = [
        message
        for message in console_errors
        if message != "Failed to load resource: net::ERR_CONNECTION_REFUSED"
    ]
    if unexpected_console_errors:
        raise AssertionError(
            "browser console errors: " + "; ".join(unexpected_console_errors)
        )
    print(
        "PL2 browser acceptance passed: logged-out refusal/login/PL14 workflow/"
        "logout/relogin/restart/export"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
