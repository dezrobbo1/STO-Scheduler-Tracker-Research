"""Execute authentication transitions across startup, logout and a later login.

The real page script runs in a fresh VM for each ordering. DOM/fetch doubles
control response completion; these are not browser-cookie integration tests.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "src/sto/api/static/app.js"
PROBE = r"""
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(process.argv[1], 'utf8');
const tick = () => new Promise(setImmediate);
function deferred() {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return {promise, resolve, reject};
}
function response(status, body = {}) {
  return {ok: status >= 200 && status < 300, status, statusText: 'synthetic',
    json: async () => body};
}
function settle(request, status, body) {
  if (status === 'network') request.reject(new TypeError('synthetic network failure'));
  else request.resolve(response(status, body));
}
function session(username) {
  return {actor: {username}, csrf_token: username + '-csrf'};
}
function page() {
  const nodes = new Map(), pending = [], calls = [];
  function node(selector) {
    if (!nodes.has(selector)) nodes.set(selector, {
      hidden: ['#planner', '#account'].includes(selector), disabled: false,
      value: '', textContent: '', dataset: {}, children: [], handlers: {},
      replaceChildren(...items) { this.children = items; this.value = items[0]?.value ?? ''; },
      append(...items) { this.children.push(...items); },
      addEventListener(event, handler) { this.handlers[event] = handler; },
    });
    return nodes.get(selector);
  }
  const context = vm.createContext({
    document: {querySelector: node}, Headers, console,
    Option: function(text, value) { this.text = text; this.value = value; },
    fetch(url, settings) {
      const request = {...deferred(), url, settings};
      pending.push(request); calls.push(request);
      return request.promise;
    },
  });
  const run = code => vm.runInContext(code, context);
  run(source);
  const take = url => {
    const index = pending.findIndex(request => request.url === url);
    assert.notEqual(index, -1, 'expected request: ' + url);
    return pending.splice(index, 1)[0];
  };
  const fill = () => {
    node('#login-username').value = 'new-user';
    node('#login-password').value = 'synthetic-new-password';
    node('#login-totp').value = '123456';
  };
  const assertTyped = () => {
    assert.equal(node('#login-password').value, 'synthetic-new-password');
    assert.equal(node('#login-totp').value, '123456');
  };
  const assertSecretsCleared = () => {
    assert.equal(node('#login-password').value, '');
    assert.equal(node('#login-totp').value, '');
  };
  const login = () => {
    fill();
    return node('#login').handlers.submit({preventDefault() {}});
  };
  const acceptLogin = async () => {
    settle(take('/api/auth/login'), 200, session('new-user'));
    await tick();
    assert.equal(run('currentActor?.username'), 'new-user', 'accept the new session');
    settle(take('/api/projects'), 200, []);
  };
  const assertAuthenticated = () => {
    assert.equal(run('currentActor?.username'), 'new-user');
    assert.equal(run('csrfToken'), 'new-user-csrf');
    assert.equal(node('#planner').hidden, false);
    assert.equal(node('#login-section').hidden, true);
    assert.doesNotMatch(node('#auth-status').textContent, /Signed out|expired/);
    assertSecretsCleared();
  };
  return {node, run, pending, calls, take, fill, assertTyped,
    assertSecretsCleared, login, acceptLogin, assertAuthenticated};
}
async function boot(p, authenticated = false) {
  settle(p.take('/api/auth/session'), authenticated ? 200 : 401, session('old-user'));
  await tick();
  if (authenticated) { settle(p.take('/api/projects'), 200, []); await tick(); }
}
async function logout(p, retry, result) {
  const operation = p.node('#logout').handlers.click();
  settle(p.take('/api/auth/logout'), retry ? 500 : result);
  await operation;
  if (retry) {
    const recovery = p.node('#retry-logout').handlers.click();
    settle(p.take('/api/auth/session'), 200, session('old-user'));
    await tick();
    const revocation = p.take('/api/auth/logout');
    assert.equal(revocation.settings.headers.get('X-CSRF-Token'), 'old-user-csrf');
    settle(revocation, result);
    await recovery;
  }
  assert.equal(p.node('#login-button').disabled, false);
}
(async () => {
  const kind = process.argv[2];
  if (kind === 'post-logout-401') {
    for (const retry of [false, true]) for (const result of [204, 401]) {
      for (const phase of ['typing', 'login', 'projects', 'authenticated']) {
        const p = page(); await boot(p, true);
        const old = p.run("json('/api/health').catch(error => error.status)");
        const oldRequest = p.take('/api/health');
        await logout(p, retry, result);
        p.fill();
        let signingIn;
        if (phase !== 'typing') signingIn = p.login();
        if (['projects', 'authenticated'].includes(phase)) {
          settle(p.take('/api/auth/login'), 200, session('new-user'));
          await tick();
        }
        if (phase === 'authenticated') {
          settle(p.take('/api/projects'), 200, []); await signingIn;
        }
        const generation = p.run('refreshGeneration');
        const status = p.node('#auth-status').textContent;
        const disabled = p.node('#login-button').disabled;
        settle(oldRequest, 401); assert.equal(await old, 401);
        assert.equal(p.run('refreshGeneration'), generation, phase + ': ignore retired-session 401');
        assert.equal(p.node('#auth-status').textContent, status);
        assert.equal(p.node('#login-button').disabled, disabled);
        if (['typing', 'login'].includes(phase)) p.assertTyped();
        if (phase === 'typing') signingIn = p.login();
        if (['typing', 'login'].includes(phase)) await p.acceptLogin();
        if (phase === 'projects') settle(p.take('/api/projects'), 200, []);
        await signingIn; p.assertAuthenticated();
        assert.equal(p.calls.filter(call => call.url === '/api/auth/login').length, 1);
      }
    }
  } else if (kind === 'bootstrap-typing') {
    for (const status of [401, 500, 'network']) {
      const p = page(); p.fill();
      settle(p.take('/api/auth/session'), status); await tick();
      p.assertTyped();
      assert.equal(p.node('#login-button').disabled, false);
      assert.equal(p.node('#planner').hidden, true);
      const signingIn = p.login(); await p.acceptLogin(); await signingIn;
      p.assertAuthenticated();
    }
  } else if (kind === 'bootstrap-new-login') {
    for (const status of [200, 401, 500, 'network']) {
      for (const phase of ['login', 'authenticated']) {
        const p = page(), oldBootstrap = p.take('/api/auth/session');
        const signingIn = p.login();
        if (phase === 'authenticated') { await p.acceptLogin(); await signingIn; }
        const generation = p.run('refreshGeneration');
        settle(oldBootstrap, status, session('old-user')); await tick();
        assert.equal(p.run('refreshGeneration'), generation, 'bootstrap cannot invalidate a new login');
        if (phase === 'login') {
          assert.equal(p.node('#login-button').disabled, true);
          assert.match(p.node('#auth-status').textContent, /Signing in/);
          await p.acceptLogin(); await signingIn;
        }
        p.assertAuthenticated();
        assert.equal(p.calls.filter(call => call.url === '/api/projects').length, 1);
      }
    }
  } else if (kind === 'bootstrap-body') {
    const p = page(), body = deferred();
    p.take('/api/auth/session').resolve({ok: true, status: 200, json: () => body.promise});
    await tick();
    const signingIn = p.login(); await p.acceptLogin(); await signingIn;
    body.resolve(session('old-user')); await tick();
    p.assertAuthenticated();
    assert.equal(p.calls.filter(call => call.url === '/api/projects').length, 1);
  } else if (kind === 'old-login-finally') {
    for (const status of [200, 401, 500, 'network']) {
      const p = page(); await boot(p);
      const firstLogin = p.login();
      settle(p.take('/api/auth/login'), 200, session('old-user')); await tick();
      const oldProjects = p.take('/api/projects');
      await logout(p, false, 204);
      p.fill();
      settle(oldProjects, status, []); await firstLogin;
      p.assertTyped();
      assert.equal(p.node('#login-button').disabled, false);
      const signingIn = p.login(); await p.acceptLogin(); await signingIn;
      p.assertAuthenticated();
    }
  } else if (kind === 'current-session-401') {
    const p = page(); await boot(p, true);
    const first = p.run("json('/api/health').catch(error => error.status)");
    const second = p.run("json('/api/projects').catch(error => error.status)");
    const firstRequest = p.take('/api/health'), secondRequest = p.take('/api/projects');
    // Ordinary project refreshes do not retire the authenticated session.
    p.run('beginRefresh(); beginRefresh()');
    settle(firstRequest, 401); assert.equal(await first, 401);
    assert.equal(p.run('currentActor'), null);
    assert.equal(p.node('#planner').hidden, true);
    assert.equal(p.node('#login-button').disabled, false);
    const signingIn = p.login();
    settle(secondRequest, 401); assert.equal(await second, 401);
    await p.acceptLogin(); await signingIn; p.assertAuthenticated();
  } else if (kind === 'failed-login-retry') {
    for (const status of [401, 500, 'network']) {
      const p = page(); await boot(p);
      const failed = p.login(); settle(p.take('/api/auth/login'), status); await failed;
      p.assertSecretsCleared();
      assert.equal(p.node('#login-button').disabled, false);
      assert.equal(p.node('#planner').hidden, true);
      const retry = p.login(); await p.acceptLogin(); await retry; p.assertAuthenticated();
    }
  } else throw new Error('unknown probe');
  console.log('PASS ' + kind);
})().catch(error => { console.error(error); process.exitCode = 1; });
"""


class AuthenticationLifecycleTests(unittest.TestCase):
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

    def test_old_session_401_cannot_interrupt_login_after_logout_or_retry(self):
        self.probe("post-logout-401")

    def test_anonymous_startup_preserves_entered_credentials(self):
        self.probe("bootstrap-typing")

    def test_startup_response_cannot_replace_a_new_authentication_attempt(self):
        self.probe("bootstrap-new-login")

    def test_startup_response_body_is_checked_after_it_settles(self):
        self.probe("bootstrap-body")

    def test_retired_login_finally_cannot_erase_new_credentials(self):
        self.probe("old-login-finally")

    def test_current_session_401_still_clears_after_project_refresh(self):
        self.probe("current-session-401")

    def test_failed_login_clears_its_secrets_and_allows_retry(self):
        self.probe("failed-login-retry")


if __name__ == "__main__":
    unittest.main()
