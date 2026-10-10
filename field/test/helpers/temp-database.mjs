import {tmpdir} from 'node:os';
import {join} from 'node:path';

export function temporaryDatabasePath(prefix) {
  return join(tmpdir(), `${prefix}-${crypto.randomUUID()}.db`);
}
