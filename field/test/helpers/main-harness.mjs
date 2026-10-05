// Execute the production entry point with native/HTTP/DOM boundaries controlled.
// Store, sync, transport, teardown and deep-link code remain real.
import {readFile} from 'node:fs/promises';
import {DatabaseSync} from 'node:sqlite';
import {FieldStore} from '../../src/store.js';
import {FieldTransport} from '../../src/transport.js';
import {SyncEngine} from '../../src/sync.js';
import {finishAccountSession, syncStatusMessage, canonicalProjectIdentity} from '../../src/session.js';
import {resumeDraftWithNotice, readSelectedPhoto} from '../../src/photo.js';
import {clearProtectedFieldState} from '../../src/protected-state.js';
import {DeepLinkInbox} from '../../src/deep-link.js';
import {persistCameraResult, recoverRestoredCamera} from '../../src/camera-recovery.js';
import {localTrialEvidence} from '../../src/trial-evidence.js';

export const A = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
export const B = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb';
export const P = 'cccccccc-cccc-4ccc-8ccc-cccccccccccc';
export const V = 'dddddddd-dddd-4ddd-8ddd-dddddddddddd';
export const TARGET = 'eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee';
export const FIRST = 'ffffffff-ffff-4fff-8fff-ffffffffffff';
export const LINK = `sto-field://project/${P}/activity/${TARGET}`;
export const identity = actor => ({actor, project: P, server: 'https://sto.example', token: `synthetic-${actor}`});
export const tick = () => new Promise(resolve => setImmediate(resolve));
export async function settled() { for (let i = 0; i < 20; i++) await tick(); }

class Control {
  textContent = ''; hidden = false; options = []; children = []; listeners = new Map();
  #value = '';
  constructor(select = false) { this.select = select; }
  get value() { return this.select ? this.options.find(row => row.value === this.#value)?.value ?? this.options[0]?.value ?? '' : this.#value; }
  set value(value) { this.#value = value; }
  addEventListener(name, action) { this.listeners.set(name, action); }
  async emit(name, event = {}) { return this.listeners.get(name)?.({preventDefault() {}, target: this, ...event}); }
  replaceChildren(...rows) { this.children = rows; this.options = []; this.#value = ''; }
  append(...rows) { this.children.push(...rows); }
  add(row) { this.options.push(row); }
  reset() { this.#value = ''; }
  getContext() { return {clearRect() {}}; }
}

export async function mainHarness({actor = A, launchUrl = null} = {}) {
  const db = new DatabaseSync(':memory:');
  const adapter = {
    async run(sql, params = []) { return db.prepare(sql).run(...params); },
    async all(sql, params = []) { return db.prepare(sql).all(...params); },
    async exec(sql) { db.exec(sql); },
    async transaction(action) {
      db.exec('BEGIN IMMEDIATE');
      try { const result = await action(adapter); db.exec('COMMIT'); return result; }
      catch (error) { db.exec('ROLLBACK'); throw error; }
    },
  };
  const store = await FieldStore.open(adapter);
  const activities = user => [
    {activity_uid: FIRST, disposition: 'scheduled', name: `${user} first activity`, code: '1'},
    {activity_uid: TARGET, disposition: 'scheduled', name: `${user} target activity`, code: '2'},
  ];
  for (const user of [A, B]) await store.commitFeedPage(user, P, [], 0, V, 'a'.repeat(64), activities(user), Date.now());
  if (actor) await store.setActiveIdentity(identity(actor));
  const controls = new Map();
  const element = id => {
    if (!controls.has(id)) controls.set(id, new Control(['activity', 'message-choice'].includes(id)));
    return controls.get(id);
  };
  const document = {getElementById: element, createElement: () => new Control()};
  const appHandlers = new Map(), networkHandlers = new Map(), intervals = [];
  let online = true, projectResponse = P, statusGate = null, streamController = null;
  const Network = {
    addListener(name, action) { networkHandlers.set(name, action); },
    async getStatus() {
      if (statusGate) {
        const gate = statusGate; statusGate = null; gate.enter(); return gate.wait;
      }
      return {connected: online};
    },
  };
  const App = {addListener(name, action) { appHandlers.set(name, action); },
    async getLaunchUrl() { return launchUrl ? {url: launchUrl} : undefined; }};
  const originalFetch = globalThis.fetch;
  const requests = [];
  globalThis.fetch = async (url, options = {}) => {
    const path = new URL(url).pathname;
    const user = options.headers.Authorization === `Bearer synthetic-${B}` ? B : A;
    requests.push({path, user, method: options.method ?? 'GET'});
    if (!online) throw new TypeError('Offline');
    if (path.endsWith('/changes/stream')) {
      const body = new ReadableStream({start(controller) {
        streamController = controller;
        options.signal.addEventListener('abort', () => controller.close(), {once: true});
      }});
      return new Response(body, {headers: {'Content-Type': 'text/event-stream'}});
    }
    if (path.endsWith('/api/auth/session')) return Response.json({actor: {user_id: user}});
    const rawProject = decodeURIComponent(path.split('/')[3] ?? '');
    if (rawProject.replace(/^\{(.*)\}$/, '$1').toLowerCase() !== P)
      return Response.json({detail: {code: 'PROJECT_INVALID'}}, {status: 422});
    if (path.endsWith('/changes')) return Response.json({events: [], next_cursor: 0, has_more: false});
    if (path.endsWith('/live')) return Response.json({version_id: V, canonical_hash: 'a'.repeat(64), kind: 'baseline'});
    if (path.endsWith('/calculations/latest')) return Response.json({version_id: V, canonical_hash: 'a'.repeat(64), activities: activities(user)});
    if (path.includes('/trial-messages/')) return Response.json({}, {status: 404});
    if (path.endsWith('/trial-messages') && options.method === 'POST') {
      const payload = JSON.parse(options.body);
      return Response.json({...payload, actor_user_id: user, project_id: P, status: 'accepted'});
    }
    if (path.split('/').length === 4) return Response.json({id: projectResponse, name: 'Synthetic', timezone: 'UTC', baseline: null});
    throw new Error(`Unexpected harness request: ${path}`);
  };
  const dependencies = {App, Camera: {}, CameraResultType: {}, CameraSource: {}, Network,
    FieldStore: {open: async () => store}, openNativeDb: async () => adapter, FieldTransport, SyncEngine,
    finishAccountSession, syncStatusMessage, canonicalProjectIdentity, resumeDraftWithNotice, readSelectedPhoto,
    clearProtectedFieldState, DeepLinkInbox, persistCameraResult, recoverRestoredCamera, localTrialEvidence,
    document, Option: class {constructor(text, value) {this.text = text; this.value = value;}},
    setInterval: action => {intervals.push(action);}, Image: class {}};
  const source = (await readFile(new URL('../../src/main.js', import.meta.url), 'utf8'))
    .replace(/^import[\s\S]*?;\n/gm, '');
  const AsyncFunction = Object.getPrototypeOf(async function() {}).constructor;
  const entry = new AsyncFunction(...Object.keys(dependencies), source + '\nreturn {render, syncNow};');
  const entrypoint = await entry(...Object.values(dependencies));
  await entrypoint.syncNow(); await settled();
  return {
    store, element, requests, ...entrypoint,
    setOnline(value) { online = value; },
    setProjectResponse(value) { projectResponse = value; },
    async connect(user, project = P) {
      element('server').value = 'https://sto.example'; element('project').value = project;
      element('token').value = `synthetic-${user}`;
      await element('connect-form').emit('submit'); await settled();
    },
    logout: () => element('logout').emit('click'),
    url: url => appHandlers.get('appUrlOpen')({url}),
    network: connected => { online = connected; networkHandlers.get('networkStatusChange')({connected}); },
    resume: () => appHandlers.get('appStateChange')({isActive: true}),
    interval: () => intervals[0](),
    streamNotify: () => streamController.enqueue(new TextEncoder().encode('id: 1\n\n')),
    pauseNetwork() {
      let release, enter;
      const wait = new Promise(resolve => {release = resolve;});
      const entered = new Promise(resolve => {enter = resolve;});
      statusGate = {wait, enter};
      return {entered, resolve: () => release({connected: true}), reject: () => release(Promise.reject(new Error('Status unavailable')))};
    },
    async close() {
      await element('logout').emit('click');
      appHandlers.get('appStateChange')({isActive: false});
      await settled(); globalThis.fetch = originalFetch; db.close();
    },
  };
}
