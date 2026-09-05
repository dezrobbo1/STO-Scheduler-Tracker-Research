# 2026-09-05 — The conformance corpus, copied in and pinned

S3's second outcome, kept out of the forward-pass change on purpose: the
semantic corpus now lives in this repository, and `PR-conformance-suite` is
live. With it S3 is done.

## What was copied, and how it is held

`dezrobbo1/PM-Software`'s `benchmarks/semantic` — the case files, the
catalogue and the corpus's own README — read from commit
`7a58a4f31b74f561c92b8e8534ec698bf6007d12` with `git show`, never from a working
tree, into `src/sto/conformance/corpus/`. `scripts/conformance/pin-corpus.py`
does the copy and writes `src/sto/conformance/MANIFEST.json` with a SHA-256 per
file. Moving the corpus to a later commit means running that script again with
the new commit; there is no other route, and editing a case in place is caught
on the next run.

Two guards, at different grains. `tests/test_conformance_corpus.py` checks the
whole directory against the manifest — a missing file, a changed file and an
unlisted file are reported as three different things because they are fixed
three different ways — and, when a clone is reachable, checks every file
against the pinned commit *in the clone's history*, so a clone that has moved
on still serves as a witness. `sto.conformance.load_case` re-derives the hash
on every read, so a drifted case fails the test that reads it rather than
passing against a different oracle.

## The counts are now derived, not remembered

The roadmap's `conformance` block was written from a hand count on 2026-09-03.
It is now checked against the cases' own fields: a case with no declared
reference forecast is native-only, a case whose expectation includes a resource
order arrives with levelling, everything else is the engine's. The derived
figures match what was written. The block also carries the pinned commit and
the manifest path, and the test holds them equal to the manifest.

## What changed in CI

Until today every conformance test skipped in CI, because the corpus was read
from a clone on one machine. They now run there, all of them, with no
environment to set. `STO_PM_SOFTWARE_DIR` and `STO_REQUIRE_PM` survive for the
one upstream cross-check only.

## Not claimed

The P1 gate's first criterion asks for the executable cases to pass
byte-identically across three processes. The forward pass answers thirty-eight
of them; the float cases wait for S4 and the status cases for S5. Nothing
here moves that criterion.
