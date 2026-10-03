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
