# 2026-09-03 — A conflict rule, measured, and withdrawn before it shipped

PR #22 merged carrying a finding from its review: `IdentityMap.resolve` matches
on external UID without comparing GUIDs, so a source that deleted a row and
later reused its UID for a different row would silently conflate the two, and
because the second GUID is bound to the same canonical id the conflation would
persist. Reproduced synthetically. Under the review-boundary rule PR #23 added
to `AGENTS.md` an hour later, that is a blocker — it falsifies the invariant
the PR claims — and this session set out to fix it on `main`.

## The fix that was written first

Compare the incoming GUID against the one bound to the matched row; on a
mismatch, displace the old row (retire its UID, report it missing unless it
reappears rekeyed) and resolve the newcomer on its own evidence. Eight
synthetic tests, all green, including swapped UIDs.

## What the real files said

`sto reconcile` on the BOILER pair went from the recorded 447 matched / 18 new
/ 13 missing to **0 matched / 465 new / 460 missing**. Direct measurement of
the two files: 539 task UIDs are shared, and all 539 carry a different GUID in
the day-5 candidate. Microsoft Project regenerated every task GUID between the
saves. The control — the untouched source against the committed before-fixture
— is 555 of 555 GUIDs identical, so the regeneration is real and not an
artefact of the importer.

Were the 539 the same tasks? 539 of 539 share the same work-order and
operation key (`Text4`, `Text5`); 531 share the same name, and the 8 that
differ are planner edits to the same task — a qualifier dropped from a crane
requirement, a strainer described more briefly, a vendor prefix added. There is
no UID reuse in the only real snapshot pair, and Microsoft Project does not
recycle task UIDs within a file.

So the premise of the finding — that a changed GUID on a matched UID signals a
different row — is false on this site's export path. It is the ordinary case
there. A rule built on it matches nothing. Whether other Project builds or
export routes keep GUIDs is unmeasured; the rule is withdrawn because the one
measurement available contradicts it, not because the opposite is proven.

## What shipped instead

The displacement rule and its tests were discarded. What survives is the part
of the finding that was right: the change must not be invisible. Every
reconciliation entry now says whether its GUID moved and the report counts
them; `sto reconcile` prints the count beside matched/new/rekeyed/missing; the
identity map persists the current GUID per row alongside the full history of
GUIDs it keeps for rekeying, and older maps without that field still load.

Two pinned measurements guard the decision: on the BOILER pair every matched
activity changed GUID; on the untouched-to-before control none did.

## What this means for durable identity

On this site's export path, UID is the durable per-row key and GUID is not.
The rekey-by-GUID fallback only helps when the export path keeps GUIDs, and it
stays in place for the paths that might. The independent rekey signal that *does* hold across these
files is the work-order and operation pair — the activity business key that
`docs/goals/ACTIVE.md` already records as not yet passed to `IdentityMap`.
That gap moved up in importance today.
