import test from 'node:test';
import assert from 'node:assert/strict';
import { DatabaseSync } from 'node:sqlite';
import { FieldStore } from '../src/store.js';
import { SyncEngine } from '../src/sync.js';
import { FieldTransport } from '../src/transport.js';

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
  assert.equal((await db.all('SELECT version FROM local_meta'))[0].version, 2);
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

test('lost response retries immutable operation and reconciles one PL4 receipt', async () => {
  const store = await FieldStore.open(database());
  await store.enqueueExecution(A, P, payload);
  let submissions = 0;
  const receipt = {operation_id: ID, status: 'applied', server_sequence: 1,
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
      return {operation_id: ID, status: 'applied', server_sequence: 1}; },
    async changes(project, after) { return {events: after ? [] : [{server_sequence: 1}],
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
  revoked = false;
  await sync.run(A, P);
  assert.equal(sends, 0);
  store.db.close();
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
      return {id: ID, status: 'accepted', server_sequence: 1}; },
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
