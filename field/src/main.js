import { App } from '@capacitor/app';
import { Camera, CameraResultType, CameraSource } from '@capacitor/camera';
import { Network } from '@capacitor/network';
import { FieldStore } from './store.js';
import { openNativeDb } from './native-db.js';
import { FieldTransport } from './transport.js';
import { SyncEngine } from './sync.js';
import {finishAccountSession, syncStatusMessage} from './session.js';
import {resumeDraftWithNotice, clearProtectedPreview} from './photo.js';

const element = id => document.getElementById(id);
const store = await (async () => FieldStore.open(await openNativeDb()))().catch(error => {
  element('connection').textContent = 'Native encrypted storage unavailable';
  element('notice').textContent = error.message;
  return null;
});

let identity = store ? await store.activeIdentity() : null;
let transport = identity ? new FieldTransport(identity.server, identity.token) : null;
let engine = transport ? new SyncEngine(store, transport) : null;
let syncing = null;
let syncAbort = null;
let streamAbort = null;
let signingOut = false;
let active = true;
let photo = null;
let photoUrl = null;
let annotations = [];
let tool = 'circle';
let arrowStart = null;

function notice(message) { element('notice').textContent = message; }
function showIdentity() {
  element('signin').hidden = !store || !!identity;
  element('field').hidden = !identity;
  element('account').textContent = identity ? `Account ${identity.actor.slice(0, 8)} · project ${identity.project.slice(0, 8)}` : '';
}

function label(state) {
  return ({queued: 'Queued locally', sending: 'Sending / awaiting receipt',
    accepted: 'Server accepted', applied: 'Applied to live schedule',
    needs_auth: 'Sign in again', needs_attention: 'Needs attention',
    draft: 'Photo saved locally; finish annotation', link_pending: 'Photo uploaded; link pending',
    linked: 'Photo linked', rejected: 'Rejected'})[state] ?? state;
}

async function render() {
  showIdentity();
  if (!identity || !store) return;
  const current = identity;
  const cache = await store.cache(current.actor, current.project);
  if (identity !== current) return;
  const online = (await Network.getStatus().catch(() => ({connected: false}))).connected;
  element('connection').textContent = online ? 'Connected or checking' : 'Offline';
  element('freshness').textContent = cache
    ? `Cached field state · last confirmed ${new Date(cache.synced_at).toLocaleString()} · ${online ? 'checking current server state' : 'offline'}`
    : 'No field cache yet. Connect before recording activity work.';
  const activity = element('activity');
  const selected = activity.value;
  activity.replaceChildren();
  for (const row of cache?.activities ?? []) {
    if (row.disposition !== 'scheduled') continue;
    activity.add(new Option(`${row.code ?? ''} ${row.name ?? ''}`.trim(), row.activity_uid));
  }
  if ([...activity.options].some(option => option.value === selected)) activity.value = selected;
  const items = await store.items(current.actor, current.project);
  if (identity !== current) return;
  const list = element('outbox'); list.replaceChildren();
  const messageChoice = element('message-choice'); messageChoice.replaceChildren();
  for (const item of items) {
    const li = document.createElement('li');
    const heading = document.createElement('strong');
    heading.textContent = `${item.kind === 'execution' ? 'Execution' : 'Note'} · ${label(item.state)}`;
    const detail = document.createElement('small');
    detail.textContent = `${item.payload.activity_uid} · ${item.id}${item.error_code ? ` · ${item.error_code}` : ''}`;
    li.append(heading, detail); list.append(li);
    if (item.kind === 'message') messageChoice.add(new Option(
      `${item.payload.text.slice(0, 40)} · ${label(item.state)}`, item.id));
  }
  const mediaList = element('media-list'); mediaList.replaceChildren();
  const mediaRows = await store.allMedia(current.actor, current.project);
  if (identity !== current) return;
  for (const entry of mediaRows) {
    const li = document.createElement('li');
    li.textContent = `${label(entry.state)} · ${entry.id}${entry.error_code ? ` · ${entry.error_code}` : ''}`;
    if (entry.state === 'draft') {
      const resume = document.createElement('button');
      resume.textContent = 'Finish annotation';
      resume.addEventListener('click', () => { void resumePhoto(entry.id); });
      li.append(' ', resume);
    }
    mediaList.append(li);
  }
  const committed = element('committed-notes'); committed.replaceChildren();
  for (const event of await store.committedMessages(current.actor, current.project)) {
    if (identity !== current) return;
    const li = document.createElement('li');
    const heading = document.createElement('strong');
    heading.textContent = 'Server accepted note';
    const detail = document.createElement('small');
    detail.textContent = `${event.activity_uid} · ${event.text}${event.media_ids.length ? ` · ${event.media_ids.length} linked photo` : ''}`;
    li.append(heading, detail); committed.append(li);
  }
}

async function syncNow() {
  if (!identity || !active || !store || signingOut) return;
  if (syncing) return syncing;
  const current = identity;
  const controller = new AbortController();
  syncAbort = controller;
  syncing = (async () => {
    try {
      const result = await engine.run(current.actor, current.project, {signal: controller.signal});
      const message = syncStatusMessage(result);
      if (identity === current && !signingOut && message) notice(message);
    } catch (error) {
      if (identity === current && !signingOut) notice(`Still cached locally; sync unavailable: ${error.message}`);
    } finally {
      syncing = null; syncAbort = null;
      if (identity === current && !signingOut) await render();
    }
  })();
  return syncing;
}

async function streamLoop(current, controller) {
  while (identity === current && active && !controller.signal.aborted) {
    try {
      await syncNow();
      if (controller.signal.aborted || signingOut || identity !== current) return;
      const cursor = (await store.cache(current.actor, current.project))?.cursor ?? 0;
      if (controller.signal.aborted || signingOut || identity !== current) return;
      await transport.subscribe(current.project, cursor, () => syncNow(), controller.signal);
    } catch { /* durable catch-up on the timer/resume is the recovery path */ }
    if (controller.signal.aborted || identity !== current) return;
    await new Promise(resolve => setTimeout(resolve, 2000));
  }
}

function startLive() {
  streamAbort?.abort();
  if (!identity || !active || signingOut) return;
  streamAbort = new AbortController();
  void streamLoop(identity, streamAbort);
}

element('connect-form').addEventListener('submit', async event => {
  event.preventDefault();
  if (!store || signingOut) return;
  const proposed = {server: element('server').value.trim().replace(/\/$/, ''),
    project: element('project').value.trim(), token: element('token').value.trim()};
  try {
    const next = new FieldTransport(proposed.server, proposed.token);
    const actor = await next.authority();
    await next.project(proposed.project);
    const verified = {...proposed, actor: actor.user_id};
    await store.setActiveIdentity(verified);
    identity = verified; transport = next; engine = new SyncEngine(store, next);
    element('token').value = '';
    await render(); await syncNow(); startLive();
  } catch (error) { notice(`Connection not confirmed: ${error.message}`); }
});

element('logout').addEventListener('click', async () => {
  if (signingOut || !identity) return;
  signingOut = true;
  syncAbort?.abort();
  try { await finishAccountSession({streamAbort, transport, syncing, store}); }
  catch {
    transport = new FieldTransport(identity.server, identity.token);
    engine = new SyncEngine(store, transport);
    signingOut = false;
    startLive();
    notice('Local sign-out failed. The account is still active; retry before handing over the device.');
    return;
  }
  identity = null; transport = null; engine = null;
  element('field').hidden = true;
  element('outbox').replaceChildren(); element('media-list').replaceChildren();
  element('committed-notes').replaceChildren();
  element('activity').replaceChildren(); element('message-choice').replaceChildren();
  element('message-text').value = '';
  if (photoUrl) URL.revokeObjectURL(photoUrl);
  photoUrl = null;
  photo = null; image = null; annotations = [];
  clearProtectedPreview(canvas, element('annotation'));
  notice('Signed out locally. Pending work is retained for the original account; revoke the device token on the server if the device is lost.');
  showIdentity();
  signingOut = false;
});

element('execution').addEventListener('submit', async event => {
  event.preventDefault();
  if (!identity) return;
  const cache = await store.cache(identity.actor, identity.project);
  if (!cache?.version_id || !cache?.canonical_hash || !element('activity').value) {
    notice('Synchronise a schedule and select an activity first.'); return;
  }
  const actualStart = element('actual-start').value;
  const actualFinish = element('actual-finish').value;
  const hours = Number(element('remaining').value);
  const remaining = Math.round(hours * 3600);
  if (!Number.isSafeInteger(remaining) || remaining < 0) { notice('Enter a valid remaining duration.'); return; }
  const payload = {operation_id: crypto.randomUUID(), expected_version_id: cache.version_id,
    expected_hash: cache.canonical_hash, activity_uid: element('activity').value,
    actual_start: actualStart || null, actual_finish: actualFinish || null,
    remaining_seconds: remaining};
  try {
    await store.enqueueExecution(identity.actor, identity.project, payload);
    element('execution').reset(); notice('Execution queued locally. Server validation is pending.');
    await render(); void syncNow();
  } catch (error) { notice(`Could not save the report: ${error.message}`); }
});

element('message').addEventListener('submit', async event => {
  event.preventDefault();
  if (!identity || !element('activity').value) return;
  const payload = {id: crypto.randomUUID(), activity_uid: element('activity').value,
    text: element('message-text').value};
  try {
    await store.enqueueMessage(identity.actor, identity.project, payload);
    element('message').reset(); notice('Note queued locally; it does not change the schedule.');
    await render(); void syncNow();
  } catch (error) { notice(`Could not save the note: ${error.message}`); }
});

const canvas = element('photo-canvas');
const ctx = canvas.getContext('2d');
let image = null;
function draw() {
  if (!image) return;
  const width = Math.min(image.width, 1000);
  canvas.width = width; canvas.height = Math.round(width * image.height / image.width);
  ctx.drawImage(image, 0, 0, canvas.width, canvas.height);
  ctx.strokeStyle = '#ffcd30'; ctx.fillStyle = '#ffcd30'; ctx.lineWidth = 4;
  for (const item of annotations) {
    const x = item.x * canvas.width, y = item.y * canvas.height;
    if (item.kind === 'arrow') {
      const toX = item.toX * canvas.width, toY = item.toY * canvas.height;
      const angle = Math.atan2(toY - y, toX - x);
      ctx.beginPath(); ctx.moveTo(x, y); ctx.lineTo(toX, toY); ctx.stroke();
      ctx.beginPath(); ctx.moveTo(toX, toY);
      ctx.lineTo(toX - 18 * Math.cos(angle - 0.5), toY - 18 * Math.sin(angle - 0.5));
      ctx.moveTo(toX, toY);
      ctx.lineTo(toX - 18 * Math.cos(angle + 0.5), toY - 18 * Math.sin(angle + 0.5)); ctx.stroke();
    } else if (item.kind === 'circle') {
      ctx.beginPath(); ctx.arc(x, y, item.radius * canvas.width, 0, 2 * Math.PI); ctx.stroke();
    } else { ctx.font = '22px system-ui'; ctx.fillText(item.text, x, y); }
  }
}

async function resumePhoto(id) {
  const currentIdentity = identity;
  return resumeDraftWithNotice(store, currentIdentity, id, notice, current => {
    if (identity !== currentIdentity) throw new Error('Account changed before photo opened');
    photo = current; annotations = current.annotations;
    const blob = new Blob([current.original], {type: current.mime});
    if (photoUrl) URL.revokeObjectURL(photoUrl);
    const url = URL.createObjectURL(blob);
    photoUrl = url;
    const preview = new Image();
    image = preview;
    preview.onload = () => {
      URL.revokeObjectURL(url);
      if (photoUrl === url) photoUrl = null;
      if (identity !== currentIdentity || image !== preview || photo?.id !== id) return;
      draw(); element('annotation').hidden = false;
    };
    preview.onerror = () => {
      URL.revokeObjectURL(url);
      if (photoUrl === url) photoUrl = null;
      if (identity === currentIdentity) notice('Photo preview could not be loaded. Original remains saved locally.');
    };
    preview.src = url;
  });
}

async function capture(bytes, mime) {
  if (!identity || !element('message-choice').value) { notice('Queue a note before adding a photo.'); return; }
  try {
    const id = crypto.randomUUID();
    const messageId = element('message-choice').value;
    const note = (await store.items(identity.actor, identity.project)).find(row => row.id === messageId);
    await store.saveMedia(identity.actor, identity.project, {id, message_id: messageId,
      activity_uid: note.payload.activity_uid, mime, original: bytes, annotations: []});
    // Native capture has returned; the immutable original is already durable
    // before editing, previewing or claiming the image was saved.
    if (await resumePhoto(id)) notice('Original photo saved locally. Finish annotation to queue transfer.');
    await render();
  } catch (error) { notice(`Photo not saved: ${error.message}`); }
}

element('camera').addEventListener('click', async () => {
  try {
    const result = await Camera.getPhoto({source: CameraSource.Camera,
      resultType: CameraResultType.Base64, quality: 75});
    const original = Uint8Array.from(atob(result.base64String), letter => letter.charCodeAt(0));
    await capture(original, result.format === 'png' ? 'image/png' : 'image/jpeg');
  } catch (error) { notice(`Capture unavailable: ${error.message}`); }
});
element('photo-file').addEventListener('change', async event => {
  const file = event.target.files?.[0];
  if (file) await capture(new Uint8Array(await file.arrayBuffer()), file.type);
  event.target.value = '';
});
for (const name of ['arrow', 'circle', 'text-tool']) element(name).addEventListener('click', () => {
  tool = name === 'text-tool' ? 'text' : name; arrowStart = null;
});
canvas.addEventListener('pointerup', event => {
  if (!photo) return;
  const rect = canvas.getBoundingClientRect();
  const x = Math.max(0, Math.min(1, (event.clientX - rect.left) / rect.width));
  const y = Math.max(0, Math.min(1, (event.clientY - rect.top) / rect.height));
  if (tool === 'arrow') {
    if (!arrowStart) { arrowStart = {x, y}; notice('Tap arrow tip.'); return; }
    annotations.push({kind: 'arrow', ...arrowStart, toX: x, toY: y}); arrowStart = null;
  } else if (tool === 'circle') annotations.push({kind: 'circle', x, y, radius: 0.08});
  else if (element('annotation-text').value.trim())
    annotations.push({kind: 'text', x, y, text: element('annotation-text').value.trim()});
  draw();
});
element('save-photo').addEventListener('click', async () => {
  if (!identity || !photo) return;
  try {
    await store.finalizeMedia(identity.actor, identity.project, photo.id, annotations);
    photo = null; image = null; annotations = []; element('annotation').hidden = true;
    notice('Photo and annotation queued locally. Transfer can recover after reconnect.');
    await render(); void syncNow();
  } catch (error) { notice(`Annotation not queued: ${error.message}`); }
});

Network.addListener('networkStatusChange', status => { if (status.connected) void syncNow(); else void render(); });
App.addListener('appStateChange', event => {
  active = event.isActive;
  if (!active) streamAbort?.abort();
  else { void syncNow(); startLive(); }
});
App.addListener('appUrlOpen', async event => {
  // The URI is a hint only. Authentication, catch-up and activity selection
  // use current permitted server state, never content carried in the link.
  const match = /^sto-field:\/\/project\/([0-9a-f-]+)\/activity\/([0-9a-f-]+)$/i.exec(event.url);
  if (!match || !identity || match[1] !== identity.project) return;
  await syncNow();
  if ([...element('activity').options].some(option => option.value === match[2]))
    element('activity').value = match[2];
});
setInterval(() => { if (active) void syncNow(); }, 5000);
await render();
if (identity) { void syncNow(); startLive(); }
