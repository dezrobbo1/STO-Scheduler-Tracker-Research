const permanent = new Set([400, 403, 404, 409, 413, 422]);

function refusal(error) {
  return {status: error?.status, code: error?.code ?? `HTTP_${error?.status ?? 'NETWORK'}`};
}

export class SyncEngine {
  constructor(store, transport, {now = Date.now, jitter = Math.random} = {}) {
    this.store = store;
    this.transport = transport;
    this.now = now;
    this.jitter = jitter;
  }

  async run(actor, project) {
    let authority;
    try { authority = await this.transport.authority(); }
    catch (error) {
      await this.#hold(actor, project, error?.status === 401 ? 'needs_auth' : 'queued',
        refusal(error).code);
      return;
    }
    // A different authenticated account cannot inherit the originating queue.
    if (authority.user_id !== actor) return;
    try { await this.transport.project(project); }
    catch (error) {
      const state = error?.status === 401 ? 'needs_auth' :
        permanent.has(error?.status) ? 'needs_attention' : 'queued';
      await this.#hold(actor, project, state, refusal(error).code);
      return;
    }

    for (const item of await this.store.items(actor, project)) {
      if (!['queued', 'sending', 'needs_auth'].includes(item.state)) continue;
      // A receipt lookup precedes even a delayed retry. This recovers a
      // committed effect whose HTTP acknowledgement was lost across a restart.
      if (item.kind === 'execution' || item.kind === 'message') {
        try {
          const old = item.kind === 'execution'
            ? await this.transport.receipt(project, item.id)
            : await this.transport.messageReceipt(project, item.id);
          if (old) { await this.#accepted(actor, project, item, old); continue; }
        } catch (error) {
          if (error?.status === 401) {
            await this.store.transition(actor, project, item.id, 'needs_auth',
              {errorCode: refusal(error).code});
            break;
          }
          if (error?.status !== 404) {
            await this.#failed(actor, project, item, error); continue;
          }
        }
      }
      if (item.due_at > this.now() && item.state !== 'needs_auth') continue;
      await this.store.transition(actor, project, item.id, 'sending');
      try {
        const outcome = item.kind === 'execution'
          ? await this.transport.submitExecution(project, item.payload)
          : await this.transport.submitMessage(project, item.payload);
        if (outcome?.status >= 400) {
          await this.#failed(actor, project, item, outcome);
        } else {
          await this.#accepted(actor, project, item, outcome);
        }
      } catch (error) { await this.#failed(actor, project, item, error); }
    }

    // Media is independent: a large photo never blocks subsequent commands.
    if (this.transport.uploadMedia) await this.#media(actor, project);
    await this.catchUp(actor, project);
  }

  async #hold(actor, project, state, code) {
    for (const item of await this.store.items(actor, project)) {
      if (['queued', 'sending', 'needs_auth'].includes(item.state))
        await this.store.transition(actor, project, item.id, state, {errorCode: code});
    }
    for (const row of await this.store.allMedia(actor, project)) {
      if (['queued', 'link_pending', 'needs_auth'].includes(row.state)) {
        const media = await this.store.media(actor, project, row.id);
        await this.store.mediaTransition(actor, project, row.id,
          state === 'queued' && media.remote_receipt ? 'link_pending' : state,
          media.remote_receipt, code);
      }
    }
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

  async #media(actor, project) {
    for (const id of await this.store.pendingMedia(actor, project, this.now())) {
      const media = await this.store.media(actor, project, id);
      let uploaded = media.remote_receipt;
      let uploadDone = Boolean(uploaded) || media.state === 'uploaded' ||
        media.state === 'link_pending';
      try {
        if (!uploadDone) {
          uploaded = await this.transport.uploadMedia(project, media);
          uploadDone = true;
        }
        await this.store.mediaTransition(actor, project, id, 'link_pending', uploaded);
        const message = (await this.store.items(actor, project)).find(row => row.id === media.message_id);
        if (!message || message.state !== 'accepted') continue;
        const linked = await this.transport.linkMedia(project, id, media.message_id);
        await this.store.mediaTransition(actor, project, id, 'linked', linked);
      } catch (error) {
        const state = error?.status === 401 ? 'needs_auth' :
          permanent.has(error?.status) ? 'needs_attention' :
          uploadDone ? 'link_pending' : 'queued';
        const attempts = media.attempts + 1;
        const delay = Math.min(60000, 1000 * 2 ** Math.min(attempts - 1, 6));
        await this.store.mediaTransition(actor, project, id, state, uploaded,
          refusal(error).code, attempts,
          state === 'queued' || state === 'link_pending'
            ? this.now() + delay + Math.floor(this.jitter() * 250) : 0);
      }
    }
  }

  async catchUp(actor, project) {
    let cursor = (await this.store.cache(actor, project))?.cursor ?? 0;
    for (let page = 0; page < 100; page++) {
      let batch;
      try { batch = await this.transport.changes(project, cursor, 100); }
      catch (error) {
        if (error?.status === 401 || error?.status === 403 || error?.status === 404)
          await this.#hold(actor, project, error?.status === 401 ? 'needs_auth' :
            'needs_attention', refusal(error).code);
        return;
      }
      for (const event of batch.events) {
        if (event.server_sequence !== cursor + 1) throw new Error('SERVER_CURSOR_GAP');
        cursor = event.server_sequence;
      }
      if (batch.next_cursor !== cursor) throw new Error('SERVER_CURSOR_MISMATCH');
      const head = await this.transport.live(project);
      const activities = this.transport.activities ? await this.transport.activities(project, head) : null;
      await this.store.setCursor(actor, project, cursor, head.version_id,
        head.canonical_hash, activities, this.now());
      if (!batch.has_more) return;
    }
    throw new Error('SERVER_CATCHUP_PAGE_LIMIT');
  }
}
