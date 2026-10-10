import test from 'node:test';
import assert from 'node:assert/strict';
import {mainHarness, A, B, P, TARGET, FIRST, LINK, settled} from './helpers/main-harness.mjs';

for (const spelling of [P, P.toUpperCase(), `{${P.toUpperCase()}}`]) {
  test(`connection stores canonical project and reconciles receipts for ${spelling}`, async () => {
    const h = await mainHarness({actor: null});
    try {
      await h.connect(A, spelling);
      assert.equal((await h.store.activeIdentity()).project, P);
      assert.ok(await h.store.cache(A, P));
      h.element('message-text').value = 'Synthetic note';
      await h.element('message').emit('submit'); await h.syncNow();
      const items = await h.store.items(A, P);
      assert.equal(items.length, 1);
      assert.equal(items[0].state, 'accepted');
      assert.equal(items[0].error_code, null);
      assert.deepEqual(await h.store.items(A, spelling === P ? B : spelling), []);
    } finally { await h.close(); }
  });
}

test('connection refuses invalid project and authoritative cross-project substitution', async () => {
  const h = await mainHarness({actor: null});
  try {
    await h.connect(A, 'not-a-uuid');
    assert.equal(await h.store.activeIdentity(), null);
    h.setProjectResponse(B);
    await h.connect(A);
    assert.equal(await h.store.activeIdentity(), null);
    assert.equal(h.element('field').hidden, true);
  } finally { await h.close(); }
});

for (const handover of [false, true]) for (const failure of [false, true]) {
  test(`delayed A network status ${failure ? 'rejection' : 'resolution'} cannot render after ${handover ? 'B handover' : 'logout'}`, async () => {
    const h = await mainHarness();
    try {
      const gate = h.pauseNetwork();
      const rendering = h.render(); await gate.entered;
      await h.logout();
      if (handover) { await h.connect(B); await h.syncNow(); }
      const protectedIds = ['account', 'connection', 'freshness', 'activity', 'outbox', 'media-list', 'committed-notes'];
      const before = protectedIds.map(id => ({text: h.element(id).textContent,
        options: h.element(id).options.map(row => row.text), children: [...h.element(id).children]}));
      if (failure) gate.reject(); else gate.resolve();
      await rendering;
      const after = protectedIds.map(id => ({text: h.element(id).textContent,
        options: h.element(id).options.map(row => row.text), children: [...h.element(id).children]}));
      assert.deepEqual(after, before);
      assert.doesNotMatch(JSON.stringify(after), /aaaaaaaa|A first activity|A target activity/);
      if (!handover) {
        assert.equal(h.element('account').textContent, '');
        assert.equal(h.element('freshness').textContent, '');
        assert.deepEqual(h.element('activity').options, []);
      }
    } finally { await h.close(); }
  });
}

test('online deep link selects only a current activity after confirmed sync', async () => {
  const h = await mainHarness();
  try {
    assert.equal(h.element('activity').value, FIRST);
    h.url(LINK); await settled();
    assert.equal(h.element('activity').value, TARGET);
    h.element('activity').value = FIRST;
    h.url(`sto-field://project/${B}/activity/${TARGET}`); await settled();
    assert.equal(h.element('activity').value, FIRST);
    h.url(`sto-field://project/${P}/activity/${B}`); await settled();
    assert.equal(h.element('activity').value, FIRST);
  } finally { await h.close(); }
});

for (const reconnect of ['network', 'resume', 'interval', 'streamNotify']) {
  test(`offline hint is automatically applied by later confirmed ${reconnect} sync`, async () => {
    const h = await mainHarness();
    try {
      h.setOnline(false); h.url(LINK); await settled();
      assert.equal(h.element('activity').value, FIRST);
      h.setOnline(true);
      if (reconnect === 'network') h.network(true); else h[reconnect]();
      await settled();
      assert.equal(h.element('activity').value, TARGET);
      assert.ok(h.requests.some(row => row.path.endsWith('/changes')));
    } finally { await h.close(); }
  });
}

test('signed-out cold-launch hint waits for connection and fresh sync', async () => {
  const h = await mainHarness({actor: null, launchUrl: LINK});
  try {
    assert.equal(h.element('activity').value, '');
    assert.equal(h.requests.length, 0);
    await h.connect(A); await settled();
    assert.equal(h.element('activity').value, TARGET);
  } finally { await h.close(); }
});

test('logout clears A offline hint before B reconnects to the same project', async () => {
  const h = await mainHarness();
  try {
    h.setOnline(false); h.url(LINK); await settled();
    await h.logout(); h.setOnline(true); await h.connect(B); await settled();
    assert.equal(h.element('activity').value, FIRST);
    assert.equal((await h.store.activeIdentity()).actor, B);
  } finally { await h.close(); }
});

for (const boundary of ['cache', 'items', 'allMedia', 'committedMessages']) {
  test(`render cannot mutate a cleared surface after its ${boundary} await`, async () => {
    const h = await mainHarness();
    try {
      const original = h.store[boundary].bind(h.store);
      let enter, release;
      const entered = new Promise(resolve => {enter = resolve;});
      const wait = new Promise(resolve => {release = resolve;});
      h.store[boundary] = async (...args) => {
        const result = await original(...args); enter(); await wait; return result;
      };
      const rendering = h.render(); await entered;
      await h.logout(); release(); await rendering;
      for (const id of ['account', 'freshness', 'connection']) assert.equal(h.element(id).textContent, '');
      for (const id of ['activity', 'outbox', 'media-list', 'committed-notes']) {
        assert.deepEqual(h.element(id).children, []);
        assert.deepEqual(h.element(id).options, []);
      }
    } finally { await h.close(); }
  });
}

test('render completion during pending logout cannot write while identity is still A', async () => {
  const h = await mainHarness();
  try {
    const gate = h.pauseNetwork();
    const rendering = h.render(); await gate.entered;
    let releaseLogout, enteredLogout;
    const wait = new Promise(resolve => {releaseLogout = resolve;});
    const entered = new Promise(resolve => {enteredLogout = resolve;});
    const logout = h.store.logout.bind(h.store);
    h.store.logout = async () => {enteredLogout(); await wait; await logout();};
    const closing = h.logout(); await entered;
    const before = ['connection', 'freshness'].map(id => h.element(id).textContent);
    gate.reject(); await rendering;
    assert.deepEqual(['connection', 'freshness'].map(id => h.element(id).textContent), before);
    releaseLogout(); await closing;
    assert.equal(h.element('freshness').textContent, '');
  } finally { await h.close(); }
});
