"""Execute the actual page's logout handlers while responses remain pending."""

from __future__ import annotations

import os
import shutil
import subprocess
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "src/sto/api/static/app.js"

# DOM/fetch doubles, not copied production functions. Hosted browser acceptance
# separately checks the rendered page; these probes control response ordering.
PROBE = r"""
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const nodes = new Map();
function node(selector) {
  if (!nodes.has(selector)) nodes.set(selector, {
    hidden: false, disabled: false, value: '', textContent: '', dataset: {},
    children: [], handlers: {},
    replaceChildren(...items) { this.children = items; this.value = items[0]?.value ?? ''; },
    append(...items) { this.children.push(...items); },
    addEventListener(event, handler) { this.handlers[event] = handler; },
  });
  return nodes.get(selector);
}
function response(status, body = {}) {
  return {ok: status >= 200 && status < 300, status, statusText: 'synthetic',
    json: async () => body};
}
function deferred() {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return {promise, resolve, reject};
}
const bootstrapRead = deferred(), bootstrapLogout = deferred();
const bootstrapping = process.argv[2] === 'bootstrap-refresh';
const context = vm.createContext({
  document: {querySelector: node}, Headers, console,
  Option: function(text, value) { this.text = text; this.value = value; },
  fetch: (url) => {
    if (!bootstrapping) return Promise.resolve(response(401));
    if (url.endsWith('/session')) return Promise.resolve(response(200, {
      actor: {username: 'synthetic'}, csrf_token: 'captured-csrf',
    }));
    return url.endsWith('/projects') ? bootstrapRead.promise : bootstrapLogout.promise;
  },
});
vm.runInContext(fs.readFileSync(process.argv[1], 'utf8'), context);
const run = (code) => vm.runInContext(code, context);
const controls = ['#login-button', '#login-username', '#login-password', '#login-totp'];
function assertCleared() {
  assert.equal(node('#planner').hidden, true, 'planner must clear before fetch settles');
  assert.equal(node('#account').hidden, true);
  assert.equal(run('currentState'), null);
  assert.equal(run('currentActor'), null);
  assert.equal(run('csrfToken'), null);
  for (const selector of ['#rows tbody', '#chart', '#summaries tbody']) {
    assert.equal(node(selector).children.length, 0, selector);
  }
  assert.equal(node('#project').value, '');
  assert.equal(node('#login-password').value, '', 'password must clear before the login panel is shown');
  assert.equal(node('#login-totp').value, '', 'authenticator code must clear before the login panel is shown');
}
function seed() {
  run("showLogoutOutcome({kind: 'already-invalid'})");
  run(`currentState = {project_id: 'synthetic-project'};
       currentActor = {username: 'synthetic'}; csrfToken = 'captured-csrf';
       refreshGeneration = 20;`);
  node('#project').value = 'synthetic-project';
  for (const selector of ['#rows tbody', '#chart', '#summaries tbody']) {
    node(selector).children = ['synthetic schedule content'];
  }
  node('#planner').hidden = false;
  node('#account').hidden = false;
  node('#auth-status').textContent = '';
  run('setLoginEnabled(true)');
}
(async () => {
  await new Promise(setImmediate); // finish the page's anonymous startup
  if (process.argv[2] === 'pending') {
    for (const outcome of [204, 401, 403, 500, 'network']) {
      seed();
      const pending = deferred();
      const calls = [];
      context.fetch = (url, settings) => { calls.push({url, settings}); return pending.promise; };
      const operation = node('#logout').handlers.click();
      assertCleared();
      assert.equal(run('refreshGeneration'), 21);
      for (const selector of controls) assert.equal(node(selector).disabled, true, selector);
      assert.equal(calls.length, 1);
      assert.equal(calls[0].url, '/api/auth/logout');
      assert.equal(calls[0].settings.headers.get('X-CSRF-Token'), 'captured-csrf');
      await node('#login').handlers.submit({preventDefault() {}});
      assert.equal(calls.length, 1, 'sign-in is refused while revocation is pending');
      assert.doesNotMatch(node('#auth-status').textContent, /server session was revoked/);
      if (outcome === 'network') pending.reject(new TypeError('synthetic network failure'));
      else pending.resolve(response(outcome));
      await operation;
      assertCleared();
      const unconfirmed = outcome === 'network' || outcome === 403 || outcome === 500;
      assert.equal(node('#retry-logout').hidden, !unconfirmed);
      for (const selector of controls) assert.equal(node(selector).disabled, unconfirmed, selector);
      if (unconfirmed) assert.match(node('#auth-status').textContent, /could not be confirmed/);
      else if (outcome === 204) assert.match(node('#auth-status').textContent, /server session was revoked/);
      else assert.match(node('#auth-status').textContent, /already unavailable/);
    }
  } else if (process.argv[2] === 'stale-refresh') {
    seed();
    const reading = deferred(), loggingOut = deferred();
    context.fetch = (url) => url.endsWith('/planner') ? reading.promise : loggingOut.promise;
    const refresh = run("show('synthetic-project')");
    const logout = node('#logout').handlers.click();
    assertCleared();
    reading.resolve(response(200, {project_id: 'synthetic-project'}));
    assert.equal(await refresh, null, 'a pre-logout response must not render');
    assertCleared();
    loggingOut.resolve(response(204));
    await logout;
  } else if (process.argv[2] === 'retry') {
    seed();
    context.fetch = async () => response(500);
    await node('#logout').handlers.click();
    const reading = deferred(), revoking = deferred();
    const calls = [];
    context.fetch = (url, settings) => {
      calls.push({url, csrf: settings.headers.get('X-CSRF-Token')});
      return url.endsWith('/session') ? reading.promise : revoking.promise;
    };
    const retry = node('#retry-logout').handlers.click();
    assertCleared();
    for (const selector of controls) assert.equal(node(selector).disabled, true);
    reading.resolve(response(200, {csrf_token: 'fresh-csrf'}));
    await new Promise(setImmediate);
    assert.equal(calls[1].csrf, 'fresh-csrf');
    assertCleared();
    revoking.resolve(response(204));
    await retry;
    for (const selector of controls) assert.equal(node(selector).disabled, false);
    assert.equal(node('#retry-logout').hidden, true);
  } else if (process.argv[2] === 'login-refresh') {
    for (const outcome of ['success', 'network', 401, 500]) {
      run("showLogoutOutcome({kind: 'already-invalid'})");
      node('#login-username').value = 'synthetic';
      node('#login-password').value = 'synthetic-pending-login-password';
      node('#login-totp').value = '123456';
      const reading = deferred(), loggingOut = deferred();
      const calls = [];
      context.fetch = (url) => {
        calls.push(url);
        if (url.endsWith('/login')) return Promise.resolve(response(200, {
          actor: {username: 'synthetic'}, csrf_token: 'captured-csrf',
        }));
        if (url.endsWith('/projects')) return reading.promise;
        if (url.endsWith('/logout')) return loggingOut.promise;
        throw new Error('stale project list must not trigger a planner request');
      };
      const login = node('#login').handlers.submit({preventDefault() {}});
      await new Promise(setImmediate);
      assert.equal(node('#planner').hidden, false);
      const logout = node('#logout').handlers.click();
      assertCleared();
      if (outcome === 'network') reading.reject(new TypeError('synthetic network failure'));
      else reading.resolve(response(outcome === 'success' ? 200 : outcome,
        [{id: 'synthetic-project', name: 'stale project'}]));
      await login;
      assertCleared();
      for (const selector of controls) assert.equal(node(selector).disabled, true,
        'old login completion must not enable sign-in during logout: ' + selector);
      assert.equal(calls.length, 3);
      assert.match(node('#auth-status').textContent, /Signing out/);
      loggingOut.resolve(response(204));
      await logout;
    }
  } else if (process.argv[2].startsWith('401-')) {
    const phase = process.argv[2].slice(4);
    for (const outcome of [204, 401, 403, 500, 'network']) {
      seed();
      const stale = deferred(), revoking = deferred(), recovering = deferred();
      const calls = [];
      let firstLogout = true;
      context.fetch = (url, settings) => {
        calls.push({url, csrf: settings.headers.get('X-CSRF-Token')});
        if (url.endsWith('/projects')) return stale.promise;
        if (url.endsWith('/session')) return recovering.promise;
        if (url.endsWith('/logout')) {
          if (firstLogout && phase !== 'pending') {
            firstLogout = false;
            return Promise.resolve(response(500));
          }
          return revoking.promise;
        }
        throw new Error('sign-in must not issue a request before logout is confirmed');
      };
      // Start the real authenticated request wrapper before logout, then delay
      // its 401 into each logout phase. Its own failure is observed, not lost.
      const older = run("json('/api/projects').catch(error => error.status)");
      const logout = node('#logout').handlers.click();
      let operation = logout;
      if (phase !== 'pending') await logout;
      if (phase.startsWith('retry-')) {
        operation = node('#retry-logout').handlers.click();
        if (phase === 'retry-revoke') {
          recovering.resolve(response(200, {csrf_token: 'fresh-csrf'}));
          await new Promise(setImmediate);
          assert.equal(calls.at(-1).csrf, 'fresh-csrf');
        }
      }
      const message = node('#auth-status').textContent;
      const retryVisible = !node('#retry-logout').hidden;
      stale.resolve(response(401));
      assert.equal(await older, 401);
      assertCleared();
      for (const selector of controls) assert.equal(node(selector).disabled, true,
        'a delayed 401 must not enable sign-in during ' + phase + ': ' + selector);
      assert.equal(node('#auth-status').textContent, message, 'keep the logout disposition');
      assert.equal(!node('#retry-logout').hidden, retryVisible, 'keep the retry path');
      const count = calls.length;
      await node('#login').handlers.submit({preventDefault() {}});
      assert.equal(calls.length, count, 'no new session request while logout is unresolved');
      // The handler must enforce the state, not only trust one DOM disable.
      node('#login-button').disabled = false;
      await node('#login').handlers.submit({preventDefault() {}});
      assert.equal(calls.length, count);
      run('setLoginEnabled(true)');
      for (const selector of controls) assert.equal(node(selector).disabled, true);
      if (phase === 'unconfirmed') {
        operation = node('#retry-logout').handlers.click();
      }
      if (phase !== 'pending' && phase !== 'retry-revoke') {
        recovering.resolve(response(200, {csrf_token: 'fresh-csrf'}));
        await new Promise(setImmediate);
        assert.equal(calls.at(-1).csrf, 'fresh-csrf');
      }
      // Duplicate/programmatic logout or retry clicks cannot race a second
      // operation against the one that owns the sign-in barrier.
      const inFlightCount = calls.length;
      await node('#logout').handlers.click();
      await node('#retry-logout').handlers.click();
      assert.equal(calls.length, inFlightCount);
      if (outcome === 'network') revoking.reject(new TypeError('synthetic network failure'));
      else revoking.resolve(response(outcome));
      await operation;
      assertCleared();
      const unconfirmed = outcome === 'network' || outcome === 403 || outcome === 500;
      for (const selector of controls) assert.equal(node(selector).disabled, unconfirmed);
      assert.equal(node('#retry-logout').hidden, !unconfirmed);
      if (unconfirmed) assert.match(node('#auth-status').textContent, /could not be confirmed/);
      else if (outcome === 204) assert.match(node('#auth-status').textContent, /server session was revoked/);
      else assert.match(node('#auth-status').textContent, /already unavailable/);
    }
  } else if (bootstrapping) {
    assert.equal(node('#planner').hidden, false);
    const logout = node('#logout').handlers.click();
    assertCleared();
    bootstrapRead.reject(new TypeError('synthetic bootstrap refresh failure'));
    await new Promise(setImmediate);
    assertCleared();
    for (const selector of controls) assert.equal(node(selector).disabled, true);
    assert.match(node('#auth-status').textContent, /Signing out/);
    bootstrapLogout.resolve(response(204));
    await logout;
  } else throw new Error('unknown probe');
  console.log('PASS ' + process.argv[2]);
})().catch(error => { console.error(error); process.exitCode = 1; });
"""


class PendingLogoutTests(unittest.TestCase):
    def probe(self, case: str) -> None:
        node = shutil.which("node") or os.environ.get("CODEX_PRIMARY_RUNTIME_NODE")
        if not node:
            self.skipTest("Node is required to execute the page's JavaScript")
        result = subprocess.run(
            [node, "-e", PROBE, str(SCRIPT), case],
            capture_output=True, text=True, timeout=20,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(f"PASS {case}", result.stdout)

    def test_clear_and_disable_happen_before_every_logout_outcome(self):
        self.probe("pending")

    def test_pre_logout_refresh_cannot_restore_cleared_state(self):
        self.probe("stale-refresh")

    def test_retry_keeps_content_hidden_and_uses_fresh_csrf(self):
        self.probe("retry")

    def test_old_login_refresh_cannot_overwrite_pending_logout(self):
        self.probe("login-refresh")

    def test_delayed_401_cannot_unlock_pending_logout(self):
        self.probe("401-pending")

    def test_delayed_401_cannot_unlock_unconfirmed_logout_or_hide_retry(self):
        self.probe("401-unconfirmed")

    def test_delayed_401_cannot_unlock_retry_session_recovery(self):
        self.probe("401-retry-session")

    def test_delayed_401_cannot_unlock_retry_revocation(self):
        self.probe("401-retry-revoke")

    def test_old_bootstrap_failure_cannot_overwrite_pending_logout(self):
        self.probe("bootstrap-refresh")


if __name__ == "__main__":
    unittest.main()
