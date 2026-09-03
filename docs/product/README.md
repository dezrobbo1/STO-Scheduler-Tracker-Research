# Product contracts

Stack-independent contracts that outlived the repositories they were written in.
They describe behaviour the product owes, not how any one implementation
provides it, and they are copied here rather than rewritten — verbatim except
for an editor's note at the top and the removal of customer task names, which
this repository does not carry.

| Document | Origin |
|---|---|
| `docs/product/project-progress-field-contract.md` | `dezrobbo1/Shutdown-Tracker-Claude`, `origin/main` at `135218f`, blob `a5432ce096a7c5c720168dab304632f7273de438` |

`project-progress-field-contract.md` is the specification for the proven
Microsoft Project completion transaction — the full field set Project itself
writes for a 100%-complete assigned task, derived from a native round trip. It
is the acceptance criterion for the writer, and until this copy existed it was
reachable only from a remote branch of a frozen repository. Its own backticked
paths refer to that repository, not to this one — the note at its top says so.

Copied 2026-09-03. The diff against the source should show only the note and
the one sanitised rollup line:

```bash
git -C ../Shutdown-Tracker-Claude show origin/main:docs/product/project-progress-field-contract.md \
  | diff - docs/product/project-progress-field-contract.md
```
