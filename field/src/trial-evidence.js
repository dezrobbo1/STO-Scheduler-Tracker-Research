// User-initiated synthetic-trial return, scoped to the currently authenticated
// actor. Never export the bearer credential, encrypted database, or photo bytes.
export async function localTrialEvidence(store, identity) {
  const {actor, project} = identity;
  const [cache, items, mediaRows] = await Promise.all([
    store.cache(actor, project), store.items(actor, project), store.allMedia(actor, project),
  ]);
  const media = [];
  for (const row of mediaRows) {
    const saved = await store.media(actor, project, row.id);
    media.push({id: saved.id, actor_user_id: actor, message_id: saved.message_id,
      activity_uid: saved.activity_uid, original_sha256: saved.sha256,
      annotations: saved.annotations, state: saved.state,
      local_final_state: saved.state, error_code: saved.error_code,
      remote_receipt: saved.remote_receipt});
  }
  return {actor_user_id: actor, project_id: project,
    authority_evidence: {user_id: actor},
    cursor: cache?.cursor ?? null, version_id: cache?.version_id ?? null,
    canonical_hash: cache?.canonical_hash ?? null,
    execution: items.filter(row => row.kind === 'execution').map(row => ({
      operation_id: row.id, actor_user_id: actor, activity_uid: row.payload.activity_uid,
      payload: row.payload, local_final_state: row.state, error_code: row.error_code,
      receipt: row.receipt})),
    communication: items.filter(row => row.kind === 'message').map(row => ({
      id: row.id, actor_user_id: actor, activity_uid: row.payload.activity_uid,
      text: row.payload.text, local_final_state: row.state, error_code: row.error_code, receipt: row.receipt})), media};
}
