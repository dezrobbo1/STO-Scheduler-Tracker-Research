import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile, unlink} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {dirname} from 'node:path';
import {DatabaseSync} from 'node:sqlite';
import {prepareMainSource} from './helpers/main-source.mjs';
import {temporaryDatabasePath} from './helpers/temp-database.mjs';

const AsyncFunction = Object.getPrototypeOf(async function() {}).constructor;
for (const [name, newline] of [['LF', '\n'], ['CRLF', '\r\n']]) {
  test(`main harness evaluates imports removed from ${name} source`, async () => {
    const source = [
      "import {App} from '@capacitor/app';",
      'import {',
      '  FieldStore,',
      "} from './store.js';",
      'return await Promise.resolve(42);',
      '',
    ].join(newline);
    const prepared = prepareMainSource(source);
    assert.doesNotMatch(prepared, /^import/m);
    assert.equal(await new AsyncFunction(prepared)(), 42);
    const production = await readFile(new URL('../src/main.js', import.meta.url), 'utf8');
    const normalized = production.replace(/\r?\n/g, newline);
    assert.doesNotThrow(() => new AsyncFunction(prepareMainSource(normalized)));
  });
}

test('temporary SQLite paths use the OS directory and preserve data across reopen', async () => {
  const file = temporaryDatabasePath('sto-portability');
  assert.equal(dirname(file), tmpdir());
  assert.notEqual(file, temporaryDatabasePath('sto-portability'));
  let db;
  try {
    db = new DatabaseSync(file);
    db.exec("CREATE TABLE evidence (value TEXT); INSERT INTO evidence VALUES ('durable')");
    db.close(); db = undefined;
    db = new DatabaseSync(file);
    assert.equal(db.prepare('SELECT value FROM evidence').get().value, 'durable');
  } finally {
    db?.close();
    await unlink(file);
  }
});
