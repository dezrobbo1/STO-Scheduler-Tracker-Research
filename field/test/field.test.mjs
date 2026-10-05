import test from 'node:test';
import assert from 'node:assert/strict';
import { DatabaseSync } from 'node:sqlite';
import { FieldStore } from '../src/store.js';
import { SyncEngine } from '../src/sync.js';
import { FieldTransport } from '../src/transport.js';
import {persistCameraResult, recoverRestoredCamera} from '../src/camera-recovery.js';
import {localTrialEvidence} from '../src/trial-evidence.js';

function database(file = ':memory:') {
  const db = new DatabaseSync(file);
  const adapter = {
    async run(sql, params = []) { return db.prepare(sql).run(...params); },
    async all(sql, params = []) { return db.prepare(sql).all(...params); },
    async exec(sql) { db.exec(sql); },
    async transaction(action) {
      db.exec('BEGIN IMMEDIATE');
      try { const result = await action(adapter); db.exec('COMMIT'); return result; }
      catch (error) { db.exec('ROLLBACK'); throw error; }
    },
    close() { db.close(); },
  };
  return adapter;
}

const A = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
const B = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb';
const P = 'cccccccc-cccc-4ccc-8ccc-cccccccccccc';
const V = 'dddddddd-dddd-4ddd-8ddd-dddddddddddd';
const ACT = 'eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee';
const ID = 'ffffffff-ffff-4fff-8fff-ffffffffffff';
const payload = {operation_id: ID, expected_version_id: V, expected_hash: 'a'.repeat(64),
  activity_uid: ACT, actual_start: '2026-01-05T09:00:00', remaining_seconds: 3600};
const executionReceipt = (actor = A, p = payload) => ({operation_id: p.operation_id,
  actor_user_id: actor, project_id: P, status: 'applied', base_version_id: p.expected_version_id,
  execution: {activity_uid: p.activity_uid, actual_start: p.actual_start,
    actual_finish: null, remaining_seconds: p.remaining_seconds}});
const noteReceipt = (id = ID, text = 'Photo') => ({id, actor_user_id: A,
  project_id: P, activity_uid: ACT, text, status: 'accepted'});

test('Android restored Camera result survives process restart with the original actor and note', async () => {
  const file = `/tmp/sto-camera-${crypto.randomUUID()}.db`;
  let db = database(file);
  let store = await FieldStore.open(db);
  await store.enqueueMessage(A, P, {id: ID, activity_uid: ACT, text: 'Original note'});
  const pending = await store.beginCameraCapture(A, P, ID, V);
  assert.equal(pending.activity_uid, ACT);
  db.close();
  db = database(file); store = await FieldStore.open(db);
  const image = {format: 'jpeg', base64String: btoa('original pixels')};
  const restored = await recoverRestoredCamera(store, {pluginId: 'Camera', methodName: 'getPhoto',
    success: true, data: image});
  assert.equal(restored.mediaId, V);
  assert.equal((await store.media(A, P, V)).message_id, ID);
  assert.equal((await store.media(A, P, V)).activity_uid, ACT);
  assert.equal(await store.media(B, P, V), null);
  assert.equal(await store.pendingCameraCapture(), null);
  await assert.rejects(persistCameraResult(store, pending, image), /IDENTITY_CONFLICT/);
  db.close();
  const {unlinkSync} = await import('node:fs'); unlinkSync(file);
});

test('capture cancellation and wrong-owner note fail closed without a media draft', async () => {
  const db = database(); const store = await FieldStore.open(db);
  await store.enqueueMessage(A, P, {id: ID, activity_uid: ACT, text: 'A note'});
  await assert.rejects(store.beginCameraCapture(B, P, ID, V), /NOTE_UNKNOWN/);
  const context = await store.beginCameraCapture(A, P, ID, V);
  await recoverRestoredCamera(store, {pluginId: 'Camera', methodName: 'getPhoto', success: false});
  assert.equal(await store.pendingCameraCapture(), null);
  assert.equal(await store.media(A, P, V), null);
  await assert.rejects(persistCameraResult(store, context, {format: 'png', base64String: btoa('x')}),
    /IDENTITY_CONFLICT/);
  db.close();
});

test('a duplicate local media identity cannot change activity or declared MIME', async () => {
  const db = database(); const store = await FieldStore.open(db);
  const row = {id: V, message_id: ID, activity_uid: ACT, mime: 'image/png',
    original: new Uint8Array([1, 2, 3]), annotations: []};
  await store.saveMedia(A, P, row);
  await assert.rejects(store.saveMedia(A, P, {...row, activity_uid: B}), /IDENTITY_CONFLICT/);
  await assert.rejects(store.saveMedia(A, P, {...row, mime: 'image/jpeg'}), /IDENTITY_CONFLICT/);
  assert.equal((await store.media(A, P, V)).activity_uid, ACT);
  db.close();
});

test('read-only trial return binds actor and frozen payload without bearer or original bytes', async () => {
  const db = database(); const store = await FieldStore.open(db);
  await store.setActiveIdentity({actor: A, project: P, token: 'A-sensitive-token', server: 'https://sto.example'});
  await store.enqueueExecution(A, P, payload);
  await store.enqueueMessage(A, P, {id: V, activity_uid: ACT, text: 'A note'});
  await store.saveMedia(A, P, {id: B, message_id: V, activity_uid: ACT,
    mime: 'image/png', original: new Uint8Array([1, 2, 3]), annotations: []});
  const evidence = await localTrialEvidence(store, {actor: A, project: P, token: 'A-sensitive-token'});
  assert.equal(evidence.execution[0].payload.operation_id, ID);
  assert.equal(evidence.communication[0].activity_uid, ACT);
  assert.equal(evidence.media[0].message_id, V);
  assert.equal(evidence.actor_user_id, A);
  assert.doesNotMatch(JSON.stringify(evidence), /A-sensitive-token|original_base64|"original"/);
  const other = await localTrialEvidence(store, {actor: B, project: P});
  assert.deepEqual([other.execution, other.communication, other.media], [[], [], []]);
  db.close();
});

test('trial return exports successful durable states and errors for execution, notes and media', async () => {
  const db = database(); const store = await FieldStore.open(db);
  await store.enqueueExecution(A, P, payload);
  await store.enqueueMessage(A, P, {id: V, activity_uid: ACT, text: 'A note'});
  await store.saveMedia(A, P, {id: B, message_id: V, activity_uid: ACT,
    mime: 'image/png', original: new Uint8Array([1, 2, 3]), annotations: []});
  await store.transition(A, P, ID, 'applied', {receipt: executionReceipt()});
  await store.transition(A, P, V, 'accepted', {receipt: noteReceipt(V, 'A note')});
  await store.mediaTransition(A, P, B, 'linked', {status: 'linked'});
  let evidence = await localTrialEvidence(store, {actor: A, project: P});
  assert.deepEqual([evidence.execution[0].local_final_state, evidence.communication[0].local_final_state,
    evidence.media[0].local_final_state], ['applied', 'accepted', 'linked']);
  assert.deepEqual([evidence.execution[0].error_code, evidence.communication[0].error_code,
    evidence.media[0].error_code], [null, null, null]);
  await store.transition(A, P, V, 'queued', {errorCode: 'HTTP_503'});
  await store.mediaTransition(A, P, B, 'link_pending', null, 'HTTP_503');
  evidence = await localTrialEvidence(store, {actor: A, project: P});
  assert.deepEqual([evidence.communication[0].local_final_state, evidence.communication[0].error_code,
    evidence.media[0].local_final_state, evidence.media[0].error_code],
  ['queued', 'HTTP_503', 'link_pending', 'HTTP_503']);
  db.close();
});

test('live activity cache requests the matching calculated version, never baseline by default', async () => {
  const original = globalThis.fetch;
  let path;
  globalThis.fetch = async url => {
    path = url;
    return {ok: true, json: async () => ({version_id: V,
      canonical_hash: 'a'.repeat(64), activities: [{activity_uid: ACT}]})};
  };
  try {
    const transport = new FieldTransport('https://sto.example', 'secret');
    assert.deepEqual(await transport.activities(P, {kind: 'live_working', version_id: V,
      canonical_hash: 'a'.repeat(64)}), [{activity_uid: ACT}]);
    assert.match(path, /kind=live_working$/);
    await assert.rejects(transport.activities(P, {kind: 'baseline', version_id: V,
      canonical_hash: 'b'.repeat(64)}), /CALCULATION_HEAD_MOVED/);
  } finally { globalThis.fetch = original; }
});

test('cancelled transport aborts an in-flight request and cannot initiate later old-token requests', async () => {
  const original = globalThis.fetch;
  const calls = [];
  globalThis.fetch = (url, options) => {
    calls.push(options.headers.Authorization);
    return new Promise((resolve, reject) => options.signal.addEventListener('abort',
      () => reject(new DOMException('Aborted', 'AbortError')), {once: true}));
  };
  try {
    const transport = new FieldTransport('https://sto.example', 'old-secret');
    const pending = transport.authority();
    transport.cancelPending();
    await assert.rejects(pending, {name: 'AbortError'});
    await assert.rejects(transport.project(P), {name: 'AbortError'});
    assert.deepEqual(calls, ['Bearer old-secret']);
  } finally { globalThis.fetch = original; }
});

test('aborted subscription never starts another request with the old bearer', async () => {
  const original = globalThis.fetch;
  const calls = [];
  globalThis.fetch = async () => { calls.push('fetch'); throw new Error('unexpected request'); };
  try {
    const transport = new FieldTransport('https://sto.example', 'old-secret');
    const signal = new AbortController();
    signal.abort();
    await assert.rejects(transport.subscribe(P, 0, () => {}, signal.signal), {name: 'AbortError'});
    transport.cancelPending();
    await assert.rejects(transport.subscribe(P, 0, () => {}, new AbortController().signal),
      {name: 'AbortError'});
    assert.deepEqual(calls, []);
  } finally { globalThis.fetch = original; }
});

test('queued success follows durable insert; restart and account switch preserve identity and visibility', async () => {
  const file = `/tmp/sto-field-${crypto.randomUUID()}.db`;
  const db = database(file);
  const store = await FieldStore.open(db);
  await store.enqueueExecution(A, P, payload);
  await store.setCursor(A, P, 7, V, 'a'.repeat(64));
  db.close();
  const reopened = await FieldStore.open(database(file));
  assert.deepEqual((await reopened.items(A, P)).map(x => [x.id, x.state, x.payload]),
    [[ID, 'queued', payload]]);
  assert.deepEqual(await reopened.items(B, P), []);
  assert.equal((await reopened.cache(A, P)).cursor, 7);
  assert.equal(await reopened.cache(B, P), null);
  await assert.rejects(reopened.enqueueExecution(A, P, {...payload, remaining_seconds: 7200}), /IDENTITY_CONFLICT/);
  reopened.db.close();
  const { unlinkSync } = await import('node:fs'); unlinkSync(file);
});

test('failed durable commit produces no queued item and migration keeps pending payload', async () => {
  const db = database();
  db.exec(`CREATE TABLE local_meta (version INTEGER NOT NULL); INSERT INTO local_meta VALUES (1);
    CREATE TABLE outbox (seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT NOT NULL, actor TEXT NOT NULL,
      project TEXT NOT NULL, kind TEXT NOT NULL, payload TEXT NOT NULL, state TEXT NOT NULL,
      attempts INTEGER NOT NULL DEFAULT 0, due_at INTEGER NOT NULL DEFAULT 0,
      receipt TEXT, error_code TEXT, UNIQUE(actor, project, id));
    CREATE TABLE project_cache (actor TEXT NOT NULL, project TEXT NOT NULL, cursor INTEGER NOT NULL,
      version_id TEXT, canonical_hash TEXT, synced_at INTEGER, activities TEXT,
      PRIMARY KEY(actor, project));`);
  db.run('INSERT INTO outbox (id,actor,project,kind,payload,state) VALUES (?,?,?,?,?,?)',
    [ID, A, P, 'execution', JSON.stringify(payload), 'queued']);
  const store = await FieldStore.open(db);
  assert.equal((await store.items(A, P))[0].id, ID);
  assert.equal((await db.all('SELECT version FROM local_meta'))[0].version, 4);
  const originalTransaction = db.transaction;
  db.transaction = action => originalTransaction(async tx => {
    await action(tx);
    throw new Error('power loss');
  });
  await assert.rejects(store.enqueueMessage(A, P, {id: 'bad', activity_uid: ACT, text: 'x'}),
    /power loss/);
  assert.equal((await store.items(A, P)).length, 1);
  db.close();
});

test('v2 to v4 upgrade retains pending execution, media, actor partition and cursor', async () => {
  const db = database();
  const old = await FieldStore.open(db);
  await old.enqueueExecution(A, P, payload);
  await old.saveMedia(A, P, {id: V, message_id: ID, activity_uid: ACT,
    mime: 'image/png', original: new Uint8Array([1, 2]), annotations: []});
  await old.setCursor(A, P, 7, V, 'a'.repeat(64));
  await db.run('UPDATE local_meta SET version=2');
  await db.exec('DROP TABLE committed_trial_events');
  const upgraded = await FieldStore.open(db);
  assert.equal((await db.all('SELECT version FROM local_meta'))[0].version, 4);
  assert.deepEqual((await upgraded.items(A, P))[0].payload, payload);
  assert.equal((await upgraded.media(A, P, V)).message_id, ID);
  assert.equal((await upgraded.cache(A, P)).cursor, 7);
  assert.deepEqual(await upgraded.committedMessages(B, P), []);
  db.close();
});

test('v3 to v4 upgrade retains needs-auth and accepted receipts, message, media link, projection and cursor', async () => {
  const db = database(); const old = await FieldStore.open(db);
  await old.enqueueExecution(A, P, payload);
  await old.transition(A, P, ID, 'needs_auth', {errorCode: 'HTTP_401'});
  await old.enqueueMessage(A, P, {id: V, activity_uid: ACT, text: 'Pending note'});
  await old.transition(A, P, V, 'accepted', {receipt: noteReceipt(V, 'Pending note')});
  await old.saveMedia(A, P, {id: ACT, message_id: V, activity_uid: ACT,
    mime: 'image/png', original: new Uint8Array([1, 2, 3]), annotations: []});
  await old.finalizeMedia(A, P, ACT, []);
  await old.mediaTransition(A, P, ACT, 'link_pending', {id: ACT, status: 'uploaded'});
  await old.commitFeedPage(A, P, [{kind: 'trial_message', id: V, server_sequence: 1,
    activity_uid: ACT, text: 'Pending note'}], 1, V, 'a'.repeat(64));
  await db.run('UPDATE local_meta SET version=3');
  const upgraded = await FieldStore.open(db);
  assert.equal((await db.all('SELECT version FROM local_meta'))[0].version, 4);
  assert.deepEqual((await upgraded.items(A, P)).map(row => [row.state, row.receipt?.id, row.error_code]),
    [['needs_auth', undefined, 'HTTP_401'], ['accepted', V, null]]);
  assert.equal((await upgraded.media(A, P, ACT)).state, 'link_pending');
  assert.equal((await upgraded.media(A, P, ACT)).remote_receipt.id, ACT);
  assert.equal((await upgraded.committedMessages(A, P))[0].activity_uid, ACT);
  assert.equal((await upgraded.cache(A, P)).cursor, 1);
  assert.deepEqual(await upgraded.items(B, P), []);
  db.close();
});

test('lost response retries immutable operation and reconciles one PL4 receipt', async () => {
  const store = await FieldStore.open(database());
  await store.enqueueExecution(A, P, payload);
  let submissions = 0;
  const receipt = {...executionReceipt(), server_sequence: 1,
    result_version_id: V, canonical_hash: 'b'.repeat(64)};
  const transport = {
    async authority() { return {user_id: A}; },
    async project() { return {id: P}; },
    async receipt() { return submissions ? receipt : null; },
    async submitExecution(project, body) { assert.deepEqual(body, payload); submissions++; throw new TypeError('lost response'); },
    async changes(project, after) { const events = submissions && !after ? [receipt] : [];
      return {events, next_cursor: after || (events.length ? 1 : 0), has_more: false}; },
    async live() { return {version_id: V, canonical_hash: receipt.canonical_hash}; },
  };
  const sync = new SyncEngine(store, transport, {now: () => 1000, jitter: () => 0});
  await sync.run(A, P);
  assert.equal((await store.items(A, P))[0].state, 'queued');
  await sync.run(A, P);
  assert.equal(submissions, 1);
  assert.equal((await store.items(A, P))[0].state, 'applied');
  assert.equal((await store.cache(A, P)).cursor, 1);
  store.db.close();
});

test('a project-scoped operation ID collision cannot accept another actor or another command locally', async () => {
  for (const wrong of [executionReceipt(B), {...executionReceipt(),
    execution: {...executionReceipt().execution, remaining_seconds: 7200}}]) {
    const store = await FieldStore.open(database());
    await store.enqueueExecution(A, P, payload);
    let submitted = 0;
    const sync = new SyncEngine(store, {
      async authority() { return {user_id: A}; }, async project() { return {id: P}; },
      async receipt() { return wrong; }, async submitExecution() { submitted++; },
      async changes(project, after) { return {events: [], next_cursor: after, has_more: false}; },
      async live() { return {version_id: V, canonical_hash: 'a'.repeat(64)}; },
    });
    assert.equal((await sync.run(A, P)).status, 'needs_attention');
    assert.equal(submitted, 0);
    assert.equal((await store.items(A, P))[0].state, 'needs_attention');
    store.db.close();
  }
});

test('stale and revoked work remain attributed and never silently rebase or switch accounts', async () => {
  const store = await FieldStore.open(database());
  await store.enqueueExecution(A, P, payload);
  const seen = [];
  const transport = {
    async authority() { return {user_id: A}; }, async project() { return {id: P}; },
    async receipt() { return null; },
    async submitExecution(project, body) { seen.push(body); return {status: 409, code: 'LIVE_STALE_HEAD'}; },
    async changes() { return {events: [], next_cursor: 0, has_more: false}; },
    async live() { return {version_id: 'new', canonical_hash: 'b'.repeat(64)}; },
  };
  const sync = new SyncEngine(store, transport);
  await sync.run(B, P);
  assert.deepEqual(seen, []);
  await sync.run(A, P);
  assert.deepEqual(seen, [payload]);
  assert.deepEqual((await store.items(A, P))[0].payload, payload);
  assert.equal((await store.items(A, P))[0].state, 'needs_attention');
  transport.project = async () => { throw Object.assign(new Error('revoked'), {status: 404}); };
  await sync.run(A, P);
  assert.equal((await store.items(A, P))[0].state, 'needs_attention');
  store.db.close();
});

test('communication and photo metadata persist independently of execution', async () => {
  const store = await FieldStore.open(database());
  const message = {id: ID, activity_uid: ACT, text: 'A-101 finished'};
  await store.enqueueMessage(A, P, message);
  const original = new Uint8Array([0, 1, 2, 3]);
  await store.saveMedia(A, P, {id: V, message_id: ID, activity_uid: ACT,
    mime: 'image/png', original, annotations: [{kind: 'arrow', x: 0, y: 0, toX: 1, toY: 1}]});
  original[0] = 9;
  const media = await store.media(A, P, V);
  assert.deepEqual([...media.original], [0, 1, 2, 3]);
  assert.equal(media.state, 'draft');
  await store.finalizeMedia(A, P, V, [{kind: 'circle', x: 0.5, y: 0.5, radius: 0.2}]);
  assert.equal((await store.media(A, P, V)).state, 'queued');
  assert.deepEqual([...((await store.media(A, P, V)).original)], [0, 1, 2, 3]);
  assert.equal((await store.items(A, P))[0].kind, 'message');
  assert.equal((await store.items(A, P))[0].payload.activity_uid, ACT);
  assert.deepEqual(await store.items(B, P), []);
  assert.equal(await store.media(B, P, V), null);
  store.db.close();
});

test('logout hides protected work but retains encrypted pending records for same-actor reauthentication', async () => {
  const store = await FieldStore.open(database());
  await store.enqueueExecution(A, P, payload);
  await store.setActiveIdentity({actor: A, project: P, token: 'synthetic-a', server: 'https://sto.example'});
  assert.equal((await store.activeIdentity()).actor, A);
  await store.logout();
  assert.equal(await store.activeIdentity(), null);
  assert.equal((await store.items(A, P))[0].state, 'queued');
  await store.setActiveIdentity({actor: B, project: P, token: 'synthetic-b', server: 'https://sto.example'});
  assert.deepEqual(await store.items(B, P), []);
  assert.equal((await store.activeIdentity()).actor, B);
  store.db.close();
});

test('expired credential holds original work; same actor resumes, another actor cannot', async () => {
  const store = await FieldStore.open(database());
  await store.enqueueExecution(A, P, payload);
  let permitted = false, sends = 0;
  const transport = {
    async authority() { if (!permitted) throw Object.assign(new Error('expired'), {status: 401});
      return {user_id: A}; },
    async project() { return {id: P}; }, async receipt() { return null; },
    async submitExecution(project, sent) { assert.deepEqual(sent, payload); sends++;
      return {...executionReceipt(), server_sequence: 1}; },
    async changes(project, after) { return {events: after ? [] : [{server_sequence: 1,
      operation_id: ID}],
      next_cursor: after || 1, has_more: false}; },
    async live() { return {version_id: V, canonical_hash: 'b'.repeat(64)}; },
  };
  const sync = new SyncEngine(store, transport);
  await sync.run(A, P);
  assert.equal((await store.items(A, P))[0].state, 'needs_auth');
  permitted = true;
  await sync.run(B, P);
  assert.equal(sends, 0);
  await sync.run(A, P);
  assert.equal(sends, 1);
  assert.equal((await store.items(A, P))[0].state, 'applied');
  store.db.close();
});

test('revoked membership holds queued work and cannot be bypassed by a later role change', async () => {
  const store = await FieldStore.open(database());
  await store.enqueueExecution(A, P, payload);
  await store.enqueueMessage(A, P, {id: V, activity_uid: ACT, text: 'photo'});
  await store.saveMedia(A, P, {id: ACT, message_id: V, activity_uid: ACT,
    mime: 'image/png', original: new Uint8Array([1, 2]), annotations: []});
  await store.finalizeMedia(A, P, ACT, []);
  let revoked = true, sends = 0;
  const transport = {
    async authority() { return {user_id: A}; },
    async project() { if (revoked) throw Object.assign(new Error('revoked'), {status: 404});
      return {id: P}; },
    async submitExecution() { sends++; },
    async changes(project, after) { return {events: [], next_cursor: after, has_more: false}; },
    async live() { return {version_id: V, canonical_hash: 'a'.repeat(64)}; },
  };
  const sync = new SyncEngine(store, transport);
  await sync.run(A, P);
  assert.equal((await store.items(A, P))[0].state, 'needs_attention');
  assert.equal((await store.items(A, P))[0].error_code, 'HTTP_404');
  assert.equal((await store.media(A, P, ACT)).state, 'needs_attention');
  revoked = false;
  await sync.run(A, P);
  assert.equal(sends, 0);
  assert.equal((await store.media(A, P, ACT)).state, 'needs_attention');
  store.db.close();
});

test('known reauthentication survives offline authority/project checks and resumes only after confirmation', async () => {
  const db = database();
  let store = await FieldStore.open(db);
  await store.enqueueExecution(A, P, payload);
  await store.enqueueMessage(A, P, {id: V, activity_uid: ACT, text: 'await auth'});
  const uploaded = {id: ACT, status: 'uploaded'};
  for (const id of [ACT, B]) {
    await store.saveMedia(A, P, {id, message_id: V, activity_uid: ACT,
      mime: 'image/png', original: new Uint8Array([1, 2]), annotations: []});
    await store.finalizeMedia(A, P, id, []);
  }
  await store.mediaTransition(A, P, ACT, 'link_pending', uploaded);
  const transport = {
    async authority() { throw Object.assign(new Error('expired'), {status: 401}); },
    async project() { throw new TypeError('offline project'); },
  };
  assert.equal((await new SyncEngine(store, transport).run(A, P)).status, 'needs_auth');
  store = await FieldStore.open(db);
  transport.authority = async () => { throw new TypeError('offline authority'); };
  for (const stage of ['authority', 'project']) {
    if (stage === 'project') transport.authority = async () => ({user_id: A});
    assert.equal((await new SyncEngine(store, transport).run(A, P)).status, 'needs_auth');
    assert.deepEqual((await store.items(A, P)).map(row => [row.state, row.error_code]),
      [['needs_auth', 'HTTP_401'], ['needs_auth', 'HTTP_401']]);
    for (const id of [ACT, B]) {
      const row = await store.media(A, P, id);
      assert.equal(row.state, 'needs_auth');
      assert.equal(row.error_code, 'HTTP_401');
      assert.deepEqual(row.remote_receipt, id === ACT ? uploaded : null);
    }
  }
  let sends = 0;
  Object.assign(transport, {
    async project() { return {id: P}; },
    async receipt() { return null; }, async messageReceipt() { return null; },
    async submitExecution(project, sent) { assert.deepEqual(sent, payload); sends++;
      return executionReceipt(); },
    async submitMessage() { sends++; return noteReceipt(V, 'await auth'); },
    async uploadMedia(project, media) { return {id: media.id, status: 'uploaded'}; },
    async linkMedia(project, id) { return {id, status: 'linked'}; },
    async changes(project, after) { return {events: [], next_cursor: after, has_more: false}; },
    async live() { return {version_id: V, canonical_hash: 'a'.repeat(64)}; },
  });
  assert.equal((await new SyncEngine(store, transport).run(A, P)).status, 'confirmed');
  assert.equal(sends, 2);
  assert.deepEqual((await store.items(A, P)).map(row => row.state), ['applied', 'accepted']);
  assert.equal((await store.media(A, P, ACT)).state, 'linked');
  assert.equal((await store.media(A, P, B)).state, 'linked');
  db.close();
});

test('photo transfer lost ack and message pending reconcile without duplicate link', async () => {
  const store = await FieldStore.open(database());
  await store.enqueueMessage(A, P, {id: ID, activity_uid: ACT, text: 'Photograph'});
  await store.saveMedia(A, P, {id: V, message_id: ID, activity_uid: ACT, mime: 'image/png',
    original: new Uint8Array([1, 2, 3]), annotations: []});
  await store.finalizeMedia(A, P, V, [{kind: 'text', x: 0.1, y: 0.2, text: 'valve'}]);
  let now = 1000, uploads = 0, links = 0, messageAttempts = 0;
  const transport = {
    async authority() { return {user_id: A}; }, async project() { return {id: P}; },
    async messageReceipt() { return null; },
    async submitMessage() { messageAttempts++; if (messageAttempts === 1) throw new TypeError('offline');
      return {...noteReceipt(ID, 'Photograph'), server_sequence: 1}; },
    async uploadMedia() { uploads++; if (uploads === 1) throw new TypeError('lost media ack');
      return {id: V, status: 'uploaded'}; },
    async linkMedia() { links++; return {id: V, status: 'linked', message_id: ID}; },
    async changes(project, after) { return {events: [], next_cursor: after, has_more: false}; },
    async live() { return {version_id: V, canonical_hash: 'a'.repeat(64)}; },
  };
  const sync = new SyncEngine(store, transport, {now: () => now, jitter: () => 0});
  await sync.run(A, P);
  assert.equal((await store.media(A, P, V)).state, 'queued');
  now = 3000;
  await sync.run(A, P);
  assert.equal((await store.media(A, P, V)).state, 'linked');
  assert.equal(uploads, 2);
  assert.equal(links, 1);
  assert.deepEqual([...(await store.media(A, P, V)).original], [1, 2, 3]);
  await sync.run(A, P);
  assert.equal(links, 1);
  store.db.close();
});

test('link failure retains durable upload receipt, backs off, and never retransfers original', async () => {
  const store = await FieldStore.open(database());
  await store.enqueueMessage(A, P, {id: ID, activity_uid: ACT, text: 'Photo'});
  await store.transition(A, P, ID, 'accepted', {receipt: {id: ID, status: 'accepted'}});
  await store.saveMedia(A, P, {id: V, message_id: ID, activity_uid: ACT, mime: 'image/png',
    original: new Uint8Array([1, 2, 3]), annotations: []});
  await store.finalizeMedia(A, P, V, []);
  let now = 1000, uploads = 0, links = 0;
  const transport = {
    async authority() { return {user_id: A}; }, async project() { return {id: P}; },
    async messageReceipt() { return {id: ID, status: 'accepted'}; },
    async uploadMedia() { uploads++; return {id: V, status: 'uploaded'}; },
    async linkMedia() { links++; if (links === 1) throw new TypeError('link response lost');
      return {id: V, status: 'linked', message_id: ID}; },
    async changes(project, after) { return {events: [], next_cursor: after, has_more: false}; },
    async live() { return {version_id: V, canonical_hash: 'a'.repeat(64)}; },
  };
  const sync = new SyncEngine(store, transport, {now: () => now, jitter: () => 0});
  await sync.run(A, P);
  assert.equal((await store.media(A, P, V)).state, 'link_pending');
  assert.equal((await store.media(A, P, V)).remote_receipt.id, V);
  await sync.run(A, P);
  assert.equal(links, 1, 'retry must respect media backoff');
  now = 2000;
  await sync.run(A, P);
  assert.equal((await store.media(A, P, V)).state, 'linked');
  assert.equal(uploads, 1);
  assert.equal(links, 2);
  store.db.close();
});

test('cursor gap is refused without persisting a false authoritative position', async () => {
  const store = await FieldStore.open(database());
  const sync = new SyncEngine(store, {
    async changes() { return {events: [{server_sequence: 2}], next_cursor: 2, has_more: false}; },
  });
  await assert.rejects(sync.catchUp(A, P), /SERVER_CURSOR_GAP/);
  assert.equal(await store.cache(A, P), null);
  store.db.close();
});

test('sync outcomes distinguish unavailable authority, expired credentials, revoked project, failed catch-up and confirmation', async () => {
  const store = await FieldStore.open(database());
  const transport = {
    async authority() { throw new TypeError('offline'); },
    async project() { return {id: P}; },
    async changes() { return {events: [], next_cursor: 0, has_more: false}; },
    async live() { return {version_id: V, canonical_hash: 'a'.repeat(64)}; },
  };
  const sync = new SyncEngine(store, transport);
  assert.equal((await sync.run(A, P)).status, 'offline');
  transport.authority = async () => { throw Object.assign(new Error('expired'), {status: 401}); };
  assert.equal((await sync.run(A, P)).status, 'needs_auth');
  await store.enqueueExecution(A, P, payload);
  transport.authority = async () => { throw Object.assign(new Error('disabled'), {status: 403}); };
  assert.equal((await sync.run(A, P)).status, 'needs_attention');
  assert.equal((await store.items(A, P))[0].state, 'needs_attention');
  transport.authority = async () => ({user_id: A});
  transport.project = async () => { throw Object.assign(new Error('revoked'), {status: 404}); };
  assert.equal((await sync.run(A, P)).status, 'needs_attention');
  transport.project = async () => ({id: P});
  transport.changes = async () => { throw new TypeError('offline'); };
  assert.equal((await sync.run(A, P)).status, 'offline');
  assert.equal(await store.cache(A, P), null);
  transport.changes = async () => ({events: [], next_cursor: 0, has_more: false});
  assert.equal((await sync.run(A, P)).status, 'confirmed');
  assert.equal((await store.cache(A, P)).cursor, 0);
  store.db.close();
});

test('receipt lookup failure cannot become a confirmed sync merely because catch-up succeeds', async () => {
  const store = await FieldStore.open(database());
  await store.enqueueExecution(A, P, payload);
  const transport = {
    async authority() { return {user_id: A}; }, async project() { return {id: P}; },
    async receipt() { throw new TypeError('receipt unavailable'); },
    async changes() { return {events: [], next_cursor: 0, has_more: false}; },
    async live() { return {version_id: V, canonical_hash: 'a'.repeat(64)}; },
  };
  assert.equal((await new SyncEngine(store, transport).run(A, P)).status, 'offline');
  assert.equal((await store.items(A, P))[0].state, 'queued');
  store.db.close();
});

test('credential revoked during receipt reconciliation stops further media submissions', async () => {
  const store = await FieldStore.open(database());
  await store.enqueueExecution(A, P, payload);
  await store.saveMedia(A, P, {id: V, message_id: ID, activity_uid: ACT,
    mime: 'image/png', original: new Uint8Array([1, 2]), annotations: []});
  await store.finalizeMedia(A, P, V, []);
  let uploaded = 0;
  const transport = {
    async authority() { return {user_id: A}; }, async project() { return {id: P}; },
    async receipt() { throw Object.assign(new Error('revoked'), {status: 401}); },
    async uploadMedia() { uploaded++; },
    async changes() { throw Object.assign(new Error('revoked'), {status: 401}); },
  };
  const result = await new SyncEngine(store, transport).run(A, P);
  assert.equal(result.status, 'needs_auth');
  assert.equal(uploaded, 0);
  store.db.close();
});

test('cancelled execution sync cannot issue later old-account requests; a new account sync is independent', async () => {
  const store = await FieldStore.open(database());
  await store.enqueueExecution(A, P, payload);
  await store.enqueueMessage(A, P, {id: V, activity_uid: ACT, text: 'A note'});
  await store.enqueueExecution(B, P, {...payload, operation_id: 'bbbbbbbb-1111-4111-8111-bbbbbbbbbbbb'});
  const controller = new AbortController();
  let entered, release;
  const pending = new Promise(resolve => { release = resolve; });
  const started = new Promise(resolve => { entered = resolve; });
  const calls = [];
  const transport = {
    async authority() { calls.push('authority'); entered(); await pending; return {user_id: A}; },
    async project() { calls.push('project'); },
    async receipt() { calls.push('receipt'); },
    async submitExecution() { calls.push('execution'); },
    async submitMessage() { calls.push('message'); },
    async uploadMedia() { calls.push('media'); },
    async changes() { calls.push('changes'); },
  };
  const oldRun = new SyncEngine(store, transport).run(A, P, {signal: controller.signal});
  await started;
  controller.abort();
  release();
  assert.equal((await oldRun).status, 'aborted');
  assert.deepEqual(calls, ['authority']);
  assert.equal((await store.items(A, P))[0].state, 'queued');
  const next = new SyncEngine(store, {
    async authority() { return {user_id: B}; }, async project() { return {id: P}; },
    async receipt() { return null; },
    async submitExecution() { return executionReceipt(B, {...payload,
      operation_id: 'bbbbbbbb-1111-4111-8111-bbbbbbbbbbbb'}); },
    async changes() { return {events: [], next_cursor: 0, has_more: false}; },
    async live() { return {version_id: V, canonical_hash: 'a'.repeat(64)}; },
  });
  assert.equal((await next.run(B, P)).status, 'confirmed');
  assert.equal((await store.items(B, P))[0].state, 'applied');
  assert.equal((await store.items(A, P))[0].state, 'queued');
  store.db.close();
});

test('cancelled media sync cannot begin another old-credential transfer or link', async () => {
  const store = await FieldStore.open(database());
  await store.enqueueMessage(A, P, {id: ID, activity_uid: ACT, text: 'Photo'});
  await store.transition(A, P, ID, 'accepted', {receipt: {id: ID}});
  for (const id of [V, ACT]) {
    await store.saveMedia(A, P, {id, message_id: ID, activity_uid: ACT,
      mime: 'image/png', original: new Uint8Array([1, 2]), annotations: []});
    await store.finalizeMedia(A, P, id, []);
  }
  const controller = new AbortController();
  let entered, release;
  const pending = new Promise(resolve => { release = resolve; });
  const started = new Promise(resolve => { entered = resolve; });
  const calls = [];
  const transport = {
    async authority() { return {user_id: A}; }, async project() { return {id: P}; },
    async messageReceipt() { return {id: ID, status: 'accepted'}; },
    async uploadMedia(project, media) { calls.push(`upload:${media.id}`); entered(); await pending;
      return {id: media.id, status: 'uploaded'}; },
    async linkMedia() { calls.push('link'); },
    async changes() { calls.push('changes'); },
  };
  const run = new SyncEngine(store, transport).run(A, P, {signal: controller.signal});
  await started;
  controller.abort(); release();
  assert.equal((await run).status, 'aborted');
  assert.deepEqual(calls, [`upload:${V}`]);
  store.db.close();
});

test('committed trial note and link project durably before cursor advance and repeat without duplication', async () => {
  const file = `/tmp/sto-field-feed-${crypto.randomUUID()}.db`;
  const db = database(file);
  const store = await FieldStore.open(db);
  const events = [
    {kind: 'trial_message', id: ID, actor_user_id: A, activity_uid: ACT,
      text: 'A: isolation observed', server_sequence: 1, status: 'accepted'},
    {kind: 'trial_media_link', id: V, media_id: V, message_id: ID, server_sequence: 2},
  ];
  const transport = {
    async changes(project, after) { return {events: events.filter(e => e.server_sequence > after),
      next_cursor: 2, has_more: false}; },
    async live() { return {version_id: V, canonical_hash: 'a'.repeat(64)}; },
  };
  const sync = new SyncEngine(store, transport);
  await sync.catchUp(B, P);
  assert.equal((await store.cache(B, P)).cursor, 2);
  assert.deepEqual((await store.committedMessages(B, P)).map(row =>
    [row.id, row.activity_uid, row.text, row.media_ids]),
    [[ID, ACT, 'A: isolation observed', [V]]]);
  assert.deepEqual(await store.committedMessages(A, P), []);
  db.close();
  const reopened = await FieldStore.open(database(file));
  await new SyncEngine(reopened, transport).catchUp(B, P);
  assert.equal((await reopened.committedMessages(B, P)).length, 1);
  assert.equal((await reopened.cache(B, P)).cursor, 2);
  reopened.db.close();
  const {unlinkSync} = await import('node:fs'); unlinkSync(file);
});

test('failed feed projection transaction rolls back both message and cursor', async () => {
  const db = database();
  const store = await FieldStore.open(db);
  const originalTransaction = db.transaction;
  db.transaction = action => originalTransaction(async tx => {
    await action(tx);
    throw new Error('power loss before feed commit');
  });
  await assert.rejects(store.commitFeedPage(A, P,
    [{kind: 'trial_message', id: ID, actor_user_id: B, activity_uid: ACT,
      text: 'remote', server_sequence: 1}], 1, V, 'a'.repeat(64), null, 1000),
  /power loss before feed commit/);
  assert.equal(await store.cache(A, P), null);
  assert.deepEqual(await store.committedMessages(A, P), []);
  db.close();
});
