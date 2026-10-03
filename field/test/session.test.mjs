import test from 'node:test';
import assert from 'node:assert/strict';
import {finishAccountSession, syncStatusMessage} from '../src/session.js';
import {resumeDraftWithNotice, clearProtectedPreview} from '../src/photo.js';

test('sign-out aborts stream and requests, waits for sync settlement before clearing identity', async () => {
  let released, entered;
  const wait = new Promise(resolve => { released = resolve; });
  const started = new Promise(resolve => { entered = resolve; });
  let cancelled = false, loggedOut = false, streamStopped = false;
  const syncing = (async () => { entered(); await wait; })();
  await started;
  const closing = finishAccountSession({
    streamAbort: {abort() { streamStopped = true; }},
    transport: {cancelPending() { cancelled = true; }}, syncing,
    store: {async logout() { loggedOut = true; }},
  });
  assert.equal(streamStopped, true);
  assert.equal(cancelled, true);
  assert.equal(loggedOut, false);
  released(); await closing;
  assert.equal(loggedOut, true);
});

test('only confirmed catch-up produces an authoritative-success notice', () => {
  assert.match(syncStatusMessage({status: 'confirmed'}), /receipts and cursor are authoritative/);
  for (const status of ['offline', 'needs_auth', 'needs_attention'])
    assert.doesNotMatch(syncStatusMessage({status}), /authoritative/);
  assert.equal(syncStatusMessage({status: 'aborted'}), null);
});

test('resume draft reports missing identity and missing or corrupt media without an unhandled error', async () => {
  const notices = [];
  const notice = message => notices.push(message);
  const store = {async media() { return null; }};
  assert.equal(await resumeDraftWithNotice(store, null, 'photo', notice, () => {}), false);
  assert.match(notices.at(-1), /sign in/i);
  assert.equal(await resumeDraftWithNotice(store, {actor: 'a', project: 'p'}, 'photo', notice, () => {}), false);
  assert.match(notices.at(-1), /LOCAL_MEDIA_UNKNOWN/);
  store.media = async () => { throw new Error('LOCAL_MEDIA_CORRUPT'); };
  assert.equal(await resumeDraftWithNotice(store, {actor: 'a', project: 'p'}, 'photo', notice, () => {}), false);
  assert.match(notices.at(-1), /LOCAL_MEDIA_CORRUPT/);
});

test('logout clears protected photo pixels and hides annotation before another account opens', () => {
  const canvas = {width: 100, height: 80};
  const annotation = {hidden: false};
  clearProtectedPreview(canvas, annotation);
  assert.equal(canvas.width, 0);
  assert.equal(canvas.height, 0);
  assert.equal(annotation.hidden, true);
});
