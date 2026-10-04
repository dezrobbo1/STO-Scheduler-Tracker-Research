import { Capacitor } from '@capacitor/core';
import { CapacitorSQLite, SQLiteConnection } from '@capacitor-community/sqlite';

// A serialized connection makes a transaction exclusive across UI and sync
// callers. The plugin's native SQLCipher passphrase lives in its secure store.
export class NativeDb {
  #tail = Promise.resolve();
  constructor(connection) { this.connection = connection; }

  async #exclusive(action) {
    const prior = this.#tail;
    let release;
    this.#tail = new Promise(resolve => { release = resolve; });
    await prior;
    try { return await action(); } finally { release(); }
  }

  #direct() {
    const db = this.connection;
    return {
      async run(sql, params = []) { return db.run(sql, params, false); },
      async all(sql, params = []) { return (await db.query(sql, params)).values ?? []; },
      async exec(sql) { return db.execute(sql, false); },
    };
  }

  async run(sql, params = []) { return this.#exclusive(() => this.#direct().run(sql, params)); }
  async all(sql, params = []) { return this.#exclusive(() => this.#direct().all(sql, params)); }
  async exec(sql) { return this.#exclusive(() => this.#direct().exec(sql)); }

  async transaction(action) {
    return this.#exclusive(async () => {
      await this.connection.beginTransaction();
      try {
        const result = await action(this.#direct());
        await this.connection.commitTransaction();
        return result;
      } catch (error) {
        try { await this.connection.rollbackTransaction(); }
        catch { /* A failed rollback must not replace the initiating failure. */ }
        throw error;
      }
    });
  }
}

export async function openNativeDb() {
  if (!Capacitor.isNativePlatform()) throw new Error('NATIVE_STORAGE_REQUIRED');
  const sqlite = new SQLiteConnection(CapacitorSQLite);
  if (!(await sqlite.isSecretStored()).result) {
    const bytes = crypto.getRandomValues(new Uint8Array(32));
    const secret = [...bytes].map(byte => byte.toString(16).padStart(2, '0')).join('');
    await sqlite.setEncryptionSecret(secret);
  }
  const name = 'sto_field_trial';
  const existing = await sqlite.isConnection(name, false);
  const connection = existing.result
    ? await sqlite.retrieveConnection(name, false)
    : await sqlite.createConnection(name, true, 'secret', 1, false);
  await connection.open();
  return new NativeDb(connection);
}
