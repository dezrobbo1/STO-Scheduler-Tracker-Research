import test from 'node:test';
import assert from 'node:assert/strict';
import {DeepLinkInbox} from '../src/deep-link.js';

test('cold launch hint waits for authenticated project and confirmed activity cache', () => {
  const inbox = new DeepLinkInbox();
  inbox.offer('sto-field://project/aaaaaaaa-1111-4111-8111-aaaaaaaaaaaa/activity/bbbbbbbb-2222-4222-8222-bbbbbbbbbbbb');
  assert.equal(inbox.afterConfirmedSync(null, []), null);
  assert.equal(inbox.afterConfirmedSync({project: 'other'}, []), null);
  const actor = {project: 'aaaaaaaa-1111-4111-8111-aaaaaaaaaaaa'};
  assert.equal(inbox.afterConfirmedSync(actor, []), null);
  assert.equal(inbox.afterConfirmedSync(actor, [{value: 'bbbbbbbb-2222-4222-8222-bbbbbbbbbbbb'}]),
    'bbbbbbbb-2222-4222-8222-bbbbbbbbbbbb');
  assert.equal(inbox.afterConfirmedSync(actor, [{value: 'bbbbbbbb-2222-4222-8222-bbbbbbbbbbbb'}]), null);
});

test('logout clears pending link so another account cannot inherit a project hint', () => {
  const inbox = new DeepLinkInbox();
  inbox.offer('sto-field://project/aaaaaaaa-1111-4111-8111-aaaaaaaaaaaa/activity/bbbbbbbb-2222-4222-8222-bbbbbbbbbbbb');
  inbox.clear();
  assert.equal(inbox.afterConfirmedSync({project: 'aaaaaaaa-1111-4111-8111-aaaaaaaaaaaa'},
    [{value: 'bbbbbbbb-2222-4222-8222-bbbbbbbbbbbb'}]), null);
});
