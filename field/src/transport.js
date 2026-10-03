const encode = encodeURIComponent;

export class FieldTransport {
  constructor(server, token) {
    this.server = server.replace(/\/$/, '');
    this.token = token;
  }

  async #request(path, options = {}) {
    const response = await fetch(this.server + path, {
      ...options, headers: {'Authorization': `Bearer ${this.token}`,
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
    return response.json();
  }

  authority() { return this.#request('/api/auth/session').then(result => result.actor); }
  project(project) { return this.#request(`/api/projects/${encode(project)}`); }
  async receipt(project, id) {
    try { return await this.#request(`/api/projects/${encode(project)}/execution-operations/${encode(id)}`); }
    catch (error) { if (error.status === 404) return null; throw error; }
  }
  submitExecution(project, payload) {
    return this.#request(`/api/projects/${encode(project)}/execution-operations`,
      {method: 'POST', body: JSON.stringify(payload)});
  }
  async messageReceipt(project, id) {
    try { return await this.#request(`/api/projects/${encode(project)}/trial-messages/${encode(id)}`); }
    catch (error) { if (error.status === 404) return null; throw error; }
  }
  submitMessage(project, payload) {
    return this.#request(`/api/projects/${encode(project)}/trial-messages`,
      {method: 'POST', body: JSON.stringify(payload)});
  }
  changes(project, after, limit) {
    return this.#request(`/api/projects/${encode(project)}/changes?after=${after}&limit=${limit}`);
  }
  live(project) { return this.#request(`/api/projects/${encode(project)}/live`); }
  activities(project, head) {
    return this.#request(`/api/projects/${encode(project)}/calculations/latest?kind=${encode(head.kind)}`)
      .then(result => {
        if (result.version_id !== head.version_id || result.canonical_hash !== head.canonical_hash)
          throw new Error('CALCULATION_HEAD_MOVED');
        return result.activities;
      });
  }
  async uploadMedia(project, media) {
    let binary = '';
    for (let i = 0; i < media.original.length; i += 8192)
      binary += String.fromCharCode(...media.original.subarray(i, i + 8192));
    const base64 = btoa(binary);
    return this.#request(`/api/projects/${encode(project)}/trial-media`, {method: 'POST',
      body: JSON.stringify({id: media.id, activity_uid: media.activity_uid,
        mime: media.mime, base64, sha256: media.sha256, annotations: media.annotations})});
  }
  linkMedia(project, id, messageId) {
    return this.#request(`/api/projects/${encode(project)}/trial-media/${encode(id)}/link`,
      {method: 'POST', body: JSON.stringify({message_id: messageId})});
  }

  async subscribe(project, after, notify, signal) {
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
