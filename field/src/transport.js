const encode = encodeURIComponent;

export class FieldTransport {
  constructor(server, token) {
    this.server = server.replace(/\/$/, '');
    this.token = token;
    this.pending = new AbortController();
  }

  cancelPending() { this.pending.abort(); }

  async #request(path, options = {}) {
    if (this.pending.signal.aborted || options.signal?.aborted)
      throw new DOMException('Transport cancelled', 'AbortError');
    const controller = new AbortController();
    const abort = () => controller.abort();
    this.pending.signal.addEventListener('abort', abort, {once: true});
    options.signal?.addEventListener('abort', abort, {once: true});
    const timeout = setTimeout(abort, 20000);
    try {
      const response = await fetch(this.server + path, {
        ...options, signal: controller.signal, headers: {'Authorization': `Bearer ${this.token}`,
          ...(options.body ? {'Content-Type': 'application/json'} : {})},
        cache: 'no-store',
      });
      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        const error = new Error(data.detail?.code ?? `HTTP_${response.status}`);
        error.status = response.status;
        error.code = data.detail?.code ?? `HTTP_${response.status}`;
        throw error;
      }
      return await response.json();
    } finally {
      clearTimeout(timeout);
      this.pending.signal.removeEventListener('abort', abort);
      options.signal?.removeEventListener('abort', abort);
    }
  }

  authority(options) { return this.#request('/api/auth/session', options).then(result => result.actor); }
  project(project, options) { return this.#request(`/api/projects/${encode(project)}`, options); }
  async receipt(project, id, options) {
    try { return await this.#request(`/api/projects/${encode(project)}/execution-operations/${encode(id)}`, options); }
    catch (error) { if (error.status === 404) return null; throw error; }
  }
  submitExecution(project, payload, options = {}) {
    return this.#request(`/api/projects/${encode(project)}/execution-operations`,
      {...options, method: 'POST', body: JSON.stringify(payload)});
  }
  async messageReceipt(project, id, options) {
    try { return await this.#request(`/api/projects/${encode(project)}/trial-messages/${encode(id)}`, options); }
    catch (error) { if (error.status === 404) return null; throw error; }
  }
  submitMessage(project, payload, options = {}) {
    return this.#request(`/api/projects/${encode(project)}/trial-messages`,
      {...options, method: 'POST', body: JSON.stringify(payload)});
  }
  changes(project, after, limit, options) {
    return this.#request(`/api/projects/${encode(project)}/changes?after=${after}&limit=${limit}`, options);
  }
  live(project, options) { return this.#request(`/api/projects/${encode(project)}/live`, options); }
  activities(project, head, options) {
    return this.#request(`/api/projects/${encode(project)}/calculations/latest?kind=${encode(head.kind)}`, options)
      .then(result => {
        if (result.version_id !== head.version_id || result.canonical_hash !== head.canonical_hash)
          throw new Error('CALCULATION_HEAD_MOVED');
        return result.activities;
      });
  }
  async uploadMedia(project, media, options = {}) {
    let binary = '';
    for (let i = 0; i < media.original.length; i += 8192)
      binary += String.fromCharCode(...media.original.subarray(i, i + 8192));
    const base64 = btoa(binary);
    return this.#request(`/api/projects/${encode(project)}/trial-media`, {...options, method: 'POST',
      body: JSON.stringify({id: media.id, activity_uid: media.activity_uid,
        mime: media.mime, base64, sha256: media.sha256, annotations: media.annotations})});
  }
  linkMedia(project, id, messageId, options = {}) {
    return this.#request(`/api/projects/${encode(project)}/trial-media/${encode(id)}/link`,
      {...options, method: 'POST', body: JSON.stringify({message_id: messageId})});
  }

  async subscribe(project, after, notify, signal) {
    if (signal.aborted || this.pending.signal.aborted)
      throw new DOMException('Subscription cancelled', 'AbortError');
    const response = await fetch(this.server +
      `/api/projects/${encode(project)}/changes/stream?after=${after}`, {
      headers: {Authorization: `Bearer ${this.token}`}, cache: 'no-store', signal,
    });
    if (!response.ok || !response.body) {
      const error = new Error(`STREAM_${response.status}`);
      error.status = response.status;
      throw error;
    }
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    try {
      while (!signal.aborted) {
        const {value, done} = await reader.read();
        if (done) return;
        buffer += decoder.decode(value, {stream: true});
        for (let cut = buffer.indexOf('\n\n'); cut >= 0; cut = buffer.indexOf('\n\n')) {
          const frame = buffer.slice(0, cut);
          buffer = buffer.slice(cut + 2);
          if (frame.startsWith('id: ')) await notify();
        }
        if (buffer.length > 1024 * 1024) throw new Error('STREAM_FRAME_TOO_LARGE');
      }
    } finally { await reader.cancel().catch(() => {}); }
  }
}
