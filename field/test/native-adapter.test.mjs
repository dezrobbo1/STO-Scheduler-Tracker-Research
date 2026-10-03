import test from 'node:test';
import assert from 'node:assert/strict';
import { DatabaseSync } from 'node:sqlite';
import { NativeDb } from '../src/native-db.js';
import { FieldStore } from '../src/store.js';

test('native adapter excludes other readers until the durable queue transaction commits', async () => {
  const sqlite = new DatabaseSync(':memory:');
  let holdCommit = false, release, entered;
  const barrier = new Promise(resolve => { release = resolve; });
  const inTransaction = new Promise(resolve => { entered = resolve; });
  const connection = {
    async beginTransaction() { sqlite.exec('BEGIN IMMEDIATE'); },
    async commitTransaction() { if (holdCommit) { entered(); await barrier; } sqlite.exec('COMMIT'); },
    async rollbackTransaction() { sqlite.exec('ROLLBACK'); },
    async run(sql, values) { sqlite.prepare(sql).run(...values); },
    async query(sql, values) { return {values: sqlite.prepare(sql).all(...values)}; },
    async execute(sql) { sqlite.exec(sql); },
  };
  const store = await FieldStore.open(new NativeDb(connection));
  holdCommit = true;
  const queued = store.enqueueExecution('a', 'p', {
    operation_id: 'x', expected_version_id: 'v', expected_hash: 'h', activity_uid: 'u',
  });
  await inTransaction;
  let readFinished = false;
  const read = store.items('a', 'p').then(rows => { readFinished = true; return rows; });
  await new Promise(resolve => setTimeout(resolve, 0));
  assert.equal(readFinished, false);
  release();
  await queued;
  assert.equal((await read)[0].id, 'x');
  sqlite.close();
});
