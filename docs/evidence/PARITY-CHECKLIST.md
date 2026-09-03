# Cut-over parity checklist

`dezrobbo1/Shutdown-Tracker-Claude` stays deployed and unmodified until this
repository can do everything below, driven through the interface rather than
demonstrated by a test. Extracted from the frozen consolidation plan (§C.3, P12)
so that the four documents citing it can cite a path rather than a paragraph.

Record a completed run as `docs/evidence/cutover-<date>.md`, naming who drove it
and on what data.

## The checklist

- [ ] Import an MSPDI schedule.
- [ ] Import a native `.mpp` schedule.
- [ ] Accept an import snapshot.
- [ ] Task table shows imported work with resource groups.
- [ ] Field progress captured offline reaches the server when connectivity returns.
- [ ] Supervisor review, then planner review, of that progress.
- [ ] Export: preview, approve, generate, download.
- [ ] Return a candidate schedule and see its delta classified.
- [ ] Raise a problem offline and see it arrive.
- [ ] Upload evidence against a task.
- [ ] Submit a critical update against a work package.
- [ ] Manage users and project memberships through the interface.
- [ ] Every route requires authentication; no trusted-header path exists.
- [ ] Migration drift guard green against a fresh database.
- [ ] The field app updates in place on a device that already had the old one
      installed, at the same URL.

## Data

No data migration. The deployed database holds synthetic review data by the
deployment's own rule. Keep it read-only for thirty days after cut-over, then
drop it.
