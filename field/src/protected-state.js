import {clearProtectedPreview} from './photo.js';

// Only transient protected state is cleared. The actor-partitioned durable
// outbox and media drafts remain in encrypted storage for that same actor.
export function clearProtectedFieldState(element, canvas, clearMemory) {
  for (const id of ['connect-form', 'execution', 'message']) element(id).reset();
  for (const id of ['server', 'project', 'token', 'actual-start', 'actual-finish',
    'remaining', 'message-text', 'annotation-text', 'photo-file',
    'trial-evidence-output']) element(id).value = '';
  for (const id of ['outbox', 'media-list', 'committed-notes', 'activity', 'message-choice'])
    element(id).replaceChildren();
  for (const id of ['account', 'freshness', 'connection']) element(id).textContent = '';
  clearProtectedPreview(canvas, element('annotation'));
  clearMemory();
}
