export async function finishAccountSession({streamAbort, transport, syncing, store}) {
  streamAbort?.abort();
  transport?.cancelPending();
  await syncing?.catch(() => {});
  await store.logout();
}

export function syncStatusMessage(result) {
  switch (result?.status) {
    case 'confirmed': return 'Synchronisation checked. Server receipts and cursor are authoritative.';
    case 'needs_auth': return 'Sign in again to check server authority. Queued work remains local.';
    case 'needs_attention': return 'Current project access or queued work needs attention; check server refusal.';
    case 'offline': return 'Still cached locally; server synchronisation unavailable.';
    case 'aborted': return null;
    default: return 'Still cached locally; server synchronisation was not confirmed.';
  }
}

function normalisedUuid(value) {
  if (typeof value !== 'string') throw new Error('PROJECT_IDENTITY_INVALID');
  const plain = value.replace(/^urn:uuid:/i, '').replace(/^\{(.*)\}$/, '$1');
  if (!/^(?:[0-9a-f]{32}|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$/i.test(plain))
    throw new Error('PROJECT_IDENTITY_INVALID');
  const hex = plain.replaceAll('-', '').toLowerCase();
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

// Bind the entered UUID to the authenticated row before choosing a durable partition.
export function canonicalProjectIdentity(proposed, project) {
  const canonical = normalisedUuid(project?.id);
  if (project.id !== canonical || normalisedUuid(proposed) !== canonical)
    throw new Error('PROJECT_IDENTITY_MISMATCH');
  return project.id;
}
