const permanent = new Set([400, 403, 404, 409, 413, 422]);

function refusal(error) {
  return {status: error?.status, code: error?.code ?? `HTTP_${error?.status ?? 'NETWORK'}`};
}

function outcome(error) {
  return error?.status === 401 ? 'needs_auth' : permanent.has(error?.status)
    ? 'needs_attention' : 'offline';
}

function active(signal) {
  if (signal?.aborted) throw new DOMException('Sync aborted', 'AbortError');
}

export class SyncEngine {
  constructor(store, transport, {now = Date.now, jitter = Math.random} = {}) {
    this.store = store;
    this.transport = transport;
    this.now = now;
    this.jitter = jitter;
  }

  async run(actor, project, {signal} = {}) {
    try { return await this.#run(actor, project, signal); }
    catch (error) { if (signal?.aborted) return {status: 'aborted'}; throw error; }
  }

  async #run(actor, project, signal) {
    let authority;
    try { active(signal); authority = await this.transport.authority({signal}); active(signal); }
    catch (error) {
      active(signal);
      const needsAuth = await this.#hold(actor, project, error?.status === 401 ? 'needs_auth' :
        permanent.has(error?.status) ? 'needs_attention' : 'queued', refusal(error).code);
      return {status: needsAuth ? 'needs_auth' : outcome(error)};
    }
    // A different authenticated account cannot inherit the originating queue.
    if (authority.user_id !== actor) return {status: 'needs_attention'};
    try { active(signal); await this.transport.project(project, {signal}); active(signal); }
    catch (error) {
      active(signal);
      const state = error?.status === 401 ? 'needs_auth' :
        permanent.has(error?.status) ? 'needs_attention' : 'queued';
      const needsAuth = await this.#hold(actor, project, state, refusal(error).code);
      return {status: needsAuth ? 'needs_auth' : outcome(error)};
    }

    let pendingOutcome = 'confirmed';
    for (const item of await this.store.items(actor, project)) {
      active(signal);
      if (!['queued', 'sending', 'needs_auth'].includes(item.state)) continue;
      // A receipt lookup precedes even a delayed retry. This recovers a
      // committed effect whose HTTP acknowledgement was lost across a restart.
      if (item.kind === 'execution' || item.kind === 'message') {
        try {
          const old = item.kind === 'execution'
            ? await this.transport.receipt(project, item.id, {signal})
            : await this.transport.messageReceipt(project, item.id, {signal});
          active(signal);
          if (old) { await this.#accepted(actor, project, item, old); continue; }
        } catch (error) {
          active(signal);
          if (error?.status === 401) {
            await this.store.transition(actor, project, item.id, 'needs_auth',
              {errorCode: refusal(error).code});
            pendingOutcome = 'needs_auth';
            break;
          }
          if (error?.status !== 404) {
            await this.#failed(actor, project, item, error);
            pendingOutcome = outcome(error);
            continue;
          }
        }
      }
      if (item.due_at > this.now() && item.state !== 'needs_auth') continue;
      await this.store.transition(actor, project, item.id, 'sending');
      try {
        active(signal);
        const outcome = item.kind === 'execution'
          ? await this.transport.submitExecution(project, item.payload, {signal})
          : await this.transport.submitMessage(project, item.payload, {signal});
        active(signal);
        if (outcome?.status >= 400) {
          await this.#failed(actor, project, item, outcome);
          pendingOutcome = outcome.status === 401 ? 'needs_auth' :
            permanent.has(outcome.status) ? 'needs_attention' : 'offline';
        } else {
          await this.#accepted(actor, project, item, outcome);
        }
      } catch (error) {
        active(signal);
        await this.#failed(actor, project, item, error);
        pendingOutcome = outcome(error);
      }
    }

    // Media is independent: a large photo never blocks subsequent commands.
    if (this.transport.uploadMedia && pendingOutcome !== 'needs_auth') {
      const mediaOutcome = await this.#media(actor, project, signal);
      if (mediaOutcome !== 'confirmed') pendingOutcome = mediaOutcome;
    }
    const caughtUp = await this.catchUp(actor, project, {signal});
    return {status: caughtUp.status === 'confirmed' ? pendingOutcome : caughtUp.status};
  }

  async #hold(actor, project, state, code) {
    let needsAuth = state === 'needs_auth';
    for (const item of await this.store.items(actor, project)) {
      // An unavailable check is no evidence that expired credentials recovered.
      if (state === 'queued' && item.state === 'needs_auth') {
        needsAuth = true;
        continue;
      }
      if (['queued', 'sending', 'needs_auth'].includes(item.state))
        await this.store.transition(actor, project, item.id, state, {errorCode: code});
    }
    for (const row of await this.store.allMedia(actor, project)) {
      if (state === 'queued' && row.state === 'needs_auth') {
        needsAuth = true;
        continue;
      }
      if (['queued', 'link_pending', 'needs_auth'].includes(row.state)) {
        const media = await this.store.media(actor, project, row.id);
        await this.store.mediaTransition(actor, project, row.id,
          state === 'queued' && media.remote_receipt ? 'link_pending' : state,
          media.remote_receipt, code);
      }
    }
    return needsAuth;
  }

  async #accepted(actor, project, item, receipt) {
    if (receipt.operation_id && receipt.operation_id !== item.id ||
        receipt.id && receipt.id !== item.id) throw new Error('RECEIPT_IDENTITY_MISMATCH');
    await this.store.transition(actor, project, item.id,
      item.kind === 'execution' && receipt.status === 'applied' ? 'applied' : 'accepted',
      {receipt, errorCode: null, dueAt: 0});
  }

  async #failed(actor, project, item, error) {
    const {status, code} = refusal(error);
    const state = status === 401 ? 'needs_auth' : permanent.has(status)
      ? 'needs_attention' : 'queued';
    const attempts = item.attempts + 1;
    const delay = Math.min(60000, 1000 * 2 ** Math.min(attempts - 1, 6));
    await this.store.transition(actor, project, item.id, state, {
      errorCode: code, attempts,
      dueAt: state === 'queued' ? this.now() + delay + Math.floor(this.jitter() * 250) : 0,
    });
  }

  async #media(actor, project, signal) {
    let pendingOutcome = 'confirmed';
    for (const id of await this.store.pendingMedia(actor, project, this.now())) {
      active(signal);
      const media = await this.store.media(actor, project, id);
      let uploaded = media.remote_receipt;
      let uploadDone = Boolean(uploaded) || media.state === 'uploaded' ||
        media.state === 'link_pending';
      try {
        if (!uploadDone) {
          uploaded = await this.transport.uploadMedia(project, media, {signal});
          active(signal);
          uploadDone = true;
        }
        await this.store.mediaTransition(actor, project, id, 'link_pending', uploaded);
        const message = (await this.store.items(actor, project)).find(row => row.id === media.message_id);
        if (!message || message.state !== 'accepted') continue;
        active(signal);
        const linked = await this.transport.linkMedia(project, id, media.message_id, {signal});
        active(signal);
        await this.store.mediaTransition(actor, project, id, 'linked', linked);
      } catch (error) {
        active(signal);
        pendingOutcome = outcome(error);
        const state = error?.status === 401 ? 'needs_auth' :
          permanent.has(error?.status) ? 'needs_attention' :
          uploadDone ? 'link_pending' : 'queued';
        const attempts = media.attempts + 1;
        const delay = Math.min(60000, 1000 * 2 ** Math.min(attempts - 1, 6));
        await this.store.mediaTransition(actor, project, id, state, uploaded,
          refusal(error).code, attempts,
          state === 'queued' || state === 'link_pending'
            ? this.now() + delay + Math.floor(this.jitter() * 250) : 0);
        if (state === 'needs_auth') break;
      }
    }
    return pendingOutcome;
  }

  async catchUp(actor, project, {signal} = {}) {
    let cursor = (await this.store.cache(actor, project))?.cursor ?? 0;
    for (let page = 0; page < 100; page++) {
      let batch;
      try { active(signal); batch = await this.transport.changes(project, cursor, 100, {signal}); active(signal); }
      catch (error) {
        active(signal);
        if (error?.status === 401 || error?.status === 403 || error?.status === 404)
          await this.#hold(actor, project, error?.status === 401 ? 'needs_auth' :
            'needs_attention', refusal(error).code);
        return {status: outcome(error)};
      }
      for (const event of batch.events) {
        if (event.server_sequence !== cursor + 1) throw new Error('SERVER_CURSOR_GAP');
        cursor = event.server_sequence;
      }
      if (batch.next_cursor !== cursor) throw new Error('SERVER_CURSOR_MISMATCH');
      active(signal);
      let head, activities;
      try {
        head = await this.transport.live(project, {signal});
        active(signal);
        activities = this.transport.activities ?
          await this.transport.activities(project, head, {signal}) : null;
        active(signal);
      } catch (error) { active(signal); return {status: outcome(error)}; }
      await this.store.commitFeedPage(actor, project, batch.events.map(event =>
        ({...event, kind: event.kind ?? (event.operation_id ? 'execution' : null)})),
      cursor, head.version_id, head.canonical_hash, activities, this.now());
      if (!batch.has_more) return {status: 'confirmed'};
    }
    throw new Error('SERVER_CATCHUP_PAGE_LIMIT');
  }
}
