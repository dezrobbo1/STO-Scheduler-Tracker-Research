// The native SQLite adapter and the test adapter share this small async SQL contract.
// No pending operation is evicted. All reads require the signed-in actor partition.
const V1 = `CREATE TABLE IF NOT EXISTS local_meta (version INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS outbox (
  seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT NOT NULL, actor TEXT NOT NULL,
  project TEXT NOT NULL, kind TEXT NOT NULL, payload TEXT NOT NULL, state TEXT NOT NULL,
  attempts INTEGER NOT NULL DEFAULT 0, due_at INTEGER NOT NULL DEFAULT 0,
  receipt TEXT, error_code TEXT, UNIQUE(actor, project, id));
CREATE INDEX IF NOT EXISTS outbox_actor_project ON outbox(actor, project, seq);
CREATE TABLE IF NOT EXISTS project_cache (
  actor TEXT NOT NULL, project TEXT NOT NULL, cursor INTEGER NOT NULL,
  version_id TEXT, canonical_hash TEXT, synced_at INTEGER, activities TEXT,
  PRIMARY KEY(actor, project));`;

const V2 = `CREATE TABLE IF NOT EXISTS trial_media (
  id TEXT NOT NULL, actor TEXT NOT NULL, project TEXT NOT NULL,
  message_id TEXT NOT NULL, activity_uid TEXT NOT NULL, mime TEXT NOT NULL,
  original_base64 TEXT NOT NULL, sha256 TEXT NOT NULL, annotations TEXT NOT NULL,
  state TEXT NOT NULL, remote_receipt TEXT, error_code TEXT,
  attempts INTEGER NOT NULL DEFAULT 0, due_at INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY(actor, project, id));
CREATE TABLE IF NOT EXISTS active_identity (
  singleton INTEGER PRIMARY KEY CHECK(singleton=1), actor TEXT NOT NULL,
  project TEXT NOT NULL, token TEXT NOT NULL, server TEXT NOT NULL);`;

const V3 = `CREATE TABLE IF NOT EXISTS committed_trial_events (
  actor TEXT NOT NULL, project TEXT NOT NULL, server_sequence INTEGER NOT NULL,
  kind TEXT NOT NULL, source_id TEXT NOT NULL, payload TEXT NOT NULL,
  PRIMARY KEY(actor, project, server_sequence));`;

const decode = value => value === null ? null : JSON.parse(value);
const encode = value => JSON.stringify(value);
const bytesToBase64 = bytes => {
  let result = '';
  for (let index = 0; index < bytes.length; index += 8192) {
    result += String.fromCharCode(...bytes.subarray(index, index + 8192));
  }
  return btoa(result);
};
const base64ToBytes = value => Uint8Array.from(atob(value), letter => letter.charCodeAt(0));
const digest = async bytes => [...new Uint8Array(await crypto.subtle.digest('SHA-256', bytes))]
  .map(byte => byte.toString(16).padStart(2, '0')).join('');

export class FieldStore {
  constructor(db) { this.db = db; }

  static async open(db) {
    const store = new FieldStore(db);
    await db.transaction(async tx => {
      await tx.exec('CREATE TABLE IF NOT EXISTS local_meta (version INTEGER NOT NULL)');
      const rows = await tx.all('SELECT version FROM local_meta');
      let version = rows[0]?.version ?? 0;
      if (version > 3) throw new Error('LOCAL_SCHEMA_NEWER_THAN_APP');
      if (version < 1) {
        await tx.exec(V1);
        await tx.run('INSERT INTO local_meta(version) VALUES (1)');
        version = 1;
      }
      if (version < 2) {
        await tx.exec(V2);
        await tx.run('UPDATE local_meta SET version=2');
        version = 2;
      }
      if (version < 3) {
        await tx.exec(V3);
        await tx.run('UPDATE local_meta SET version=3');
      }
    });
    return store;
  }

  async enqueueExecution(actor, project, payload) {
    if (!payload.operation_id || !payload.expected_version_id || !payload.expected_hash ||
        !payload.activity_uid) throw new Error('EXECUTION_PAYLOAD_INCOMPLETE');
    return this.#enqueue(actor, project, payload.operation_id, 'execution', payload);
  }

  async enqueueMessage(actor, project, payload) {
    if (!payload.id || !payload.activity_uid || !payload.text?.trim())
      throw new Error('MESSAGE_PAYLOAD_INCOMPLETE');
    return this.#enqueue(actor, project, payload.id, 'message', payload);
  }

  async #enqueue(actor, project, id, kind, payload) {
    return this.db.transaction(async tx => {
      const rows = await tx.all('SELECT kind,payload FROM outbox WHERE actor=? AND project=? AND id=?',
        [actor, project, id]);
      if (rows.length) {
        if (rows[0].kind !== kind || rows[0].payload !== encode(payload))
          throw new Error('LOCAL_OPERATION_IDENTITY_CONFLICT');
        return id;
      }
      await tx.run(`INSERT INTO outbox(id,actor,project,kind,payload,state)
        VALUES(?,?,?,?,?,'queued')`, [id, actor, project, kind, encode(payload)]);
      return id;
    });
  }

  async items(actor, project) {
    const rows = await this.db.all('SELECT * FROM outbox WHERE actor=? AND project=? ORDER BY seq',
      [actor, project]);
    return rows.map(row => ({...row, payload: decode(row.payload), receipt: decode(row.receipt)}));
  }

  async setActiveIdentity({actor, project, token, server}) {
    if (!actor || !project || !token || !/^https:\/\//.test(server))
      throw new Error('LOCAL_IDENTITY_INVALID');
    await this.db.transaction(async tx => {
      await tx.run('DELETE FROM active_identity WHERE singleton=1');
      await tx.run('INSERT INTO active_identity VALUES(1,?,?,?,?)',
        [actor, project, token, server.replace(/\/$/, '')]);
    });
  }

  async activeIdentity() {
    return (await this.db.all('SELECT actor,project,token,server FROM active_identity WHERE singleton=1'))[0] ?? null;
  }

  async logout() {
    // The outbox stays encrypted and attributed. The protected UI clears at
    // once; the same actor must present a fresh credential to recover it.
    await this.db.run('DELETE FROM active_identity WHERE singleton=1');
  }

  async transition(actor, project, id, state, {receipt = null, errorCode = null,
    attempts = null, dueAt = null} = {}) {
    const rows = await this.db.all('SELECT attempts,due_at FROM outbox WHERE actor=? AND project=? AND id=?',
      [actor, project, id]);
    if (!rows.length) throw new Error('LOCAL_OPERATION_UNKNOWN');
    await this.db.run(`UPDATE outbox SET state=?,receipt=?,error_code=?,attempts=?,due_at=?
      WHERE actor=? AND project=? AND id=?`, [state, encode(receipt), errorCode,
      attempts ?? rows[0].attempts, dueAt ?? rows[0].due_at, actor, project, id]);
  }

  async cache(actor, project) {
    const row = (await this.db.all('SELECT * FROM project_cache WHERE actor=? AND project=?',
      [actor, project]))[0];
    return row ? {...row, activities: decode(row.activities)} : null;
  }

  async setCursor(actor, project, cursor, versionId, canonicalHash, activities = null,
    now = Date.now()) {
    await this.db.transaction(async tx => {
      await this.#setCursorTx(tx, actor, project, cursor, versionId, canonicalHash, activities, now);
    });
  }

  async #setCursorTx(tx, actor, project, cursor, versionId, canonicalHash, activities, now) {
    const row = (await tx.all('SELECT * FROM project_cache WHERE actor=? AND project=?',
      [actor, project]))[0];
    const existing = row ? {...row, activities: decode(row.activities)} : null;
    if (existing && cursor < existing.cursor) throw new Error('LOCAL_CURSOR_REGRESSION');
    await tx.run(`INSERT INTO project_cache(actor,project,cursor,version_id,canonical_hash,synced_at,activities)
      VALUES(?,?,?,?,?,?,?) ON CONFLICT(actor,project) DO UPDATE SET
      cursor=excluded.cursor,version_id=excluded.version_id,
      canonical_hash=excluded.canonical_hash,synced_at=excluded.synced_at,
      activities=excluded.activities`,
    [actor, project, cursor, versionId, canonicalHash, now,
      encode(activities ?? existing?.activities ?? [])]);
  }

  async commitFeedPage(actor, project, events, cursor, versionId, canonicalHash,
    activities = null, now = Date.now()) {
    await this.db.transaction(async tx => {
      for (const event of events) {
        const sourceId = event.operation_id ?? event.id;
        if (!sourceId || !event.kind || !Number.isSafeInteger(event.server_sequence))
          throw new Error('LOCAL_FEED_EVENT_INVALID');
        const previous = (await tx.all(`SELECT kind,source_id,payload FROM committed_trial_events
          WHERE actor=? AND project=? AND server_sequence=?`,
        [actor, project, event.server_sequence]))[0];
        if (previous) {
          if (previous.kind !== event.kind || previous.source_id !== sourceId ||
              previous.payload !== encode(event)) throw new Error('LOCAL_FEED_IDENTITY_CONFLICT');
        } else {
          await tx.run(`INSERT INTO committed_trial_events
            (actor,project,server_sequence,kind,source_id,payload) VALUES(?,?,?,?,?,?)`,
          [actor, project, event.server_sequence, event.kind, sourceId, encode(event)]);
        }
      }
      await this.#setCursorTx(tx, actor, project, cursor, versionId, canonicalHash, activities, now);
    });
  }

  async committedMessages(actor, project) {
    const rows = await this.db.all(`SELECT kind,payload FROM committed_trial_events
      WHERE actor=? AND project=? ORDER BY server_sequence`, [actor, project]);
    const messages = new Map();
    const links = [];
    for (const row of rows) {
      const event = decode(row.payload);
      if (row.kind === 'trial_message') messages.set(event.id, {...event, media_ids: []});
      if (row.kind === 'trial_media_link') links.push(event);
    }
    for (const link of links) {
      if (messages.has(link.message_id)) messages.get(link.message_id).media_ids.push(link.media_id);
    }
    return [...messages.values()];
  }

  async saveMedia(actor, project, {id, message_id, activity_uid, mime, original, annotations}) {
    if (!id || !message_id || !activity_uid || !mime?.startsWith('image/') ||
        !(original instanceof Uint8Array) || !original.length || original.length > 5 * 1024 * 1024)
      throw new Error('LOCAL_MEDIA_INVALID');
    const sha256 = await digest(original);
    const encoded = bytesToBase64(original);
    await this.db.transaction(async tx => {
      const rows = await tx.all('SELECT sha256,message_id,annotations FROM trial_media WHERE actor=? AND project=? AND id=?',
        [actor, project, id]);
      if (rows.length) {
        if (rows[0].sha256 !== sha256 || rows[0].message_id !== message_id ||
            rows[0].annotations !== encode(annotations)) throw new Error('LOCAL_MEDIA_IDENTITY_CONFLICT');
        return;
      }
      await tx.run(`INSERT INTO trial_media
        (id,actor,project,message_id,activity_uid,mime,original_base64,sha256,annotations,state)
        VALUES(?,?,?,?,?,?,?,?,?,'draft')`,
      [id, actor, project, message_id, activity_uid, mime, encoded, sha256, encode(annotations)]);
    });
  }

  async finalizeMedia(actor, project, id, annotations) {
    if (!Array.isArray(annotations) || annotations.length > 30) throw new Error('LOCAL_ANNOTATION_INVALID');
    await this.db.transaction(async tx => {
      const row = (await tx.all('SELECT state FROM trial_media WHERE actor=? AND project=? AND id=?',
        [actor, project, id]))[0];
      if (!row || row.state !== 'draft') throw new Error('LOCAL_MEDIA_NOT_DRAFT');
      await tx.run("UPDATE trial_media SET annotations=?,state='queued' WHERE actor=? AND project=? AND id=?",
        [encode(annotations), actor, project, id]);
    });
  }

  async allMedia(actor, project) {
    return this.db.all('SELECT id,message_id,activity_uid,state,error_code FROM trial_media WHERE actor=? AND project=? ORDER BY rowid',
      [actor, project]);
  }

  async media(actor, project, id) {
    const row = (await this.db.all('SELECT * FROM trial_media WHERE actor=? AND project=? AND id=?',
      [actor, project, id]))[0];
    if (!row) return null;
    const original = base64ToBytes(row.original_base64);
    if (await digest(original) !== row.sha256) throw new Error('LOCAL_MEDIA_CORRUPT');
    return {...row, original, annotations: decode(row.annotations),
      remote_receipt: decode(row.remote_receipt)};
  }

  async pendingMedia(actor, project, now = Date.now()) {
    return (await this.db.all("SELECT id FROM trial_media WHERE actor=? AND project=? AND state IN ('queued','link_pending','needs_auth') AND due_at<=? ORDER BY rowid",
      [actor, project, now])).map(row => row.id);
  }

  async mediaTransition(actor, project, id, state, receipt = null, errorCode = null,
    attempts = null, dueAt = 0) {
    await this.db.run(`UPDATE trial_media SET state=?,remote_receipt=?,error_code=?,
      attempts=COALESCE(?,attempts),due_at=? WHERE actor=? AND project=? AND id=?`,
    [state, encode(receipt), errorCode, attempts, dueAt, actor, project, id]);
  }
}
