# RC01 assignment native matrix V2: frozen input and return contract

Status: **INPUT AND ANALYZER PREDECLARED; GENUINE V2 NATIVE RETURN NOT RUN**.
This is an append-only follow-up to the unchanged V1 record and the failed V1
return receipt. It changes no production scheduler or P1 gate.

## Exact synthetic input

| Field | Fixed value |
|---|---|
| Experiment | `P1-G2-RC01-ASSIGNMENT-ENVELOPE-NATIVE-MATRIX-V2` |
| Committed MSPDI | `tests/fixtures/P1-G2-RC01-ASSIGNMENT-ENVELOPE-NATIVE-MATRIX-V2.xml` |
| Bytes | **20,989** |
| SHA-256 | `f8c0b622e257186ee30c6b933aedebe697841dc41f72b2c3137ba0f77126cb0c` |
| Generator | `scripts/evidence/p1_g2_rc01_assignment_native_v2_generate.py` |
| Return analyzer | `scripts/evidence/p1_g2_rc01_assignment_native_v2.py` |

V2 changes the V1 project name/title to a unique versioned identity while
preserving its scheduling topology and exact A/B/C/D input cases. Four
independent automatic ASAP fixed-units tasks (UIDs 1–4) start at Monday
2026-10-12 08:00; generated Duration and RemainingDuration initially equal
four working hours. Tasks have no explicit calendar, constraints, progress,
predecessors, manual scheduling or levelling delays. EffortDriven and
IgnoreResourceCalendar are both zero. The project calendar works Monday–Friday
08:00–12:00 and 13:00–17:00. Resource calendars UIDs 2–5 inherit that base
and respectively work weekdays AM 08:00–12:00, PM 13:00–17:00, overlap 1
08:00–12:00, overlap 2 08:00–12:00. Four resource UIDs 1–4 link to those
calendar UIDs in order and cannot be levelled (`CanLevel=0`).

| Case | Task UID | Assignment UID → resource UID (XML order) | Task Work | Declared Duration | Existing STO four-hour union prediction | Independent assignment-span prediction |
|---|---:|---|---|---|---|---|
| A | 1 | 101→1 AM, 102→2 PM | 8 h | 4 h | 08:00–12:00 | 08:00–17:00; 8 working hours across project-day interval |
| B | 2 | 103→2 PM, 104→1 AM | 8 h | 4 h | 08:00–12:00 | same as A despite reversed declaration order |
| C | 3 | 105→3 AM, 106→4 AM | 8 h | 4 h | 08:00–12:00 | 08:00–12:00; distinct but overlapping resources |
| D | 4 | 107→1 AM | 4 h | 4 h | 08:00–12:00 | 08:00–12:00; single resource |

Every assignment declares Work `PT4H0M0S`, Units `1`, zero actual work
and delay. The assignment XML declaration order is `101,102,103,104,105,106,107`.
The four-hour task duration is the **declared input** used for STO's current
union placement prediction; V1 proves Project can recalculate it, so returned
Duration and RemainingDuration are **native outputs**. A/B's two assignments
each demand four productive hours on disjoint calendars; their eight-hour
returned Duration and task span to 17:00 distinguish them from four-hour
single-calendar union placement. C and D are controls that must remain four
hours/12:00. A discrepancy in native duration alone without matching
assignment spans and controls is inconclusive.

The importer and migration preserve assignment Work/Units, source assignment
Start/Finish and resource-to-calendar identity; task Type becomes canonical
fixed-units. EffortDriven and IgnoreResourceCalendar survive in the vendor
extension, and the V2 analyzer checks their raw MSPDI fields directly.

## V1-changed field classification, fixed before V2 return

| V1 difference | V2 category | Exact rule |
|---|---|---|
| Project GUID | C identity normalization | accept original or regenerated syntactically valid GUID; project Name, Title, start, calendar UID and all declared scheduling options still match |
| Task GUID, assignment GUID, calendar GUID | A input | exact original GUID by fixed task, assignment or calendar UID |
| Resource GUID | C identity normalization | original GUID or the GUID of that resource's **same pinned calendar UID** only; UID and resource→calendar UID must match |
| Calendar name UIDs 2–5 | C display normalization | original per-UID name or `Unassigned`; UID, GUID, base UID and weekday working intervals stay pinned |
| Calendar weekday representation | C save normalization | weekend rows remain explicitly off or are omitted for resource calendars inheriting project calendar; weekdays 2–6 remain exact |
| Added calendar UID 6 / task UID 0 / resource UID 0 | C inert save rows | only known default/summary/null shapes; no declared assignment may reference them |
| Task CalendarUID absent→`-1` | C no-task-calendar normalization | either absent or `-1`, never a real task calendar |
| Task levelling delay format 7→8 | C formatting normalization | task format 7 or 8; assignment format and all delays, levelling switches and resource CanLevel stay pinned |
| Assignment UID, task/resource UID links, declaration order, Work, Units, actual/remaining Work | A input | exact links, order and Work; Units numeric one; progress zero |
| Task Type, EffortDriven, IgnoreResourceCalendar, Work, Start, progress, constraints, Manual, relationships | A input | exact original values, automatic, no topology edges |
| Calendar working times, exceptions, project start and calendar UID | A input | exact generated semantics; no new exceptions |
| Task Duration and RemainingDuration, Finish, EarlyFinish, late/float/critical values; project FinishDate | B native output | read after inputs validate; require coherent duration/work and controls for support |
| Assignment Start/Finish and timephased Work span; resource PeakUnits/OverAllocated | B native output | each assignment must work its own calendar; one observed save timephased row, if present, must match its UID/span/four-hour Work |
| Project BuildNumber, save metadata and displayed cost/variance fields | C witnessed save output | known metadata fields only; the scheduling options inserted by V1 are checked against witnessed values; unknown options rejected |
| All other unexpected changes | D unknown | fail closed as `V2_INPUT_CONTRACT_VIOLATED` (unexplained calculated outputs are inconclusive) |

`HonorConstraints=0`, `TaskUpdatesResource=1`, and the other Project save
options added in V1 are checked against that observation **when present**.
Original options are pinned. Manual saved Start/Finish/Duration fields, if
present, must equal their automatic calculated counterparts. Newly added
timephased assignment allocations cannot silently replace four hours of work.
No V1 evidence establishes any other normalization rule.

## Predeclared stopping rule

The analyzer checks the semantic inputs and allowed normalization before it
uses returned task or assignment dates. It reads the native BuildNumber,
task Duration/RemainingDuration/Start/Finish/EarlyStart/EarlyFinish, seven
assignment Start/Finish spans and their declared Work/Units. A generated,
unrecalculated input yields `V2_NOT_RUN_UNRECALCULATED_INPUT`.

`V2_ASSIGNMENT_ENVELOPE_SUPPORTED` requires all of these together:

1. A valid input contract and native Project 16.0 build number;
2. each AM assignment 08:00–12:00 and each PM assignment 13:00–17:00,
   with four-hour Work and Units one, checked by UID;
3. A/B each start at their earliest assignment start, finish at the latest
   assignment finish, and EarlyStart/EarlyFinish equal task Start/Finish;
4. A/B have the same task and per-role assignment dates despite reversed XML
   declaration order;
5. C's two independent assignments and task/early spans match the shared
   08:00–12:00 envelope;
6. D's one assignment, task and early coordinates all match 08:00–12:00;
7. A/B finish differs from the 12:00 current four-hour union prediction,
   with returned Duration and RemainingDuration 8h on A/B and 4h on C/D.

With valid controls, identical order twins and a coherent incompatible
separated-case rule, the verdict is `V2_ASSIGNMENT_ENVELOPE_REJECTED`.
Mixed results, failed controls, order dependence, inconsistent duration and
other unexplained outputs are `V2_NATIVE_RESULT_INCONCLUSIVE`. An altered
experiment-defining input is `V2_INPUT_CONTRACT_VIOLATED`, which **does not**
reject the hypothesis. Only supported native evidence permits a **later,
separate diagnostic-only BOILER counterfactual**. No V2 result directly
authorizes production RC01 correction.

## Microsoft Project desktop procedure

1. Download the exact V2 XML above and check its 20,989-byte size and SHA-256.
2. Open it in Microsoft Project desktop; leave its four tasks, calendars,
   resources, assignments and scheduling settings as imported. Do not invoke
   Resource Leveling or edit work or units.
3. Calculate the complete project using **F9** / **Calculate Project**.
4. Save as **Microsoft Project XML (MSPDI)**, with the exact output name
   `P1-G2-RC01-ASSIGNMENT-ENVELOPE-NATIVE-MATRIX-V2-RETURNED.xml`.
5. Return that unedited XML. No screenshot or manually transcribed values
   replace it. Run the frozen analyzer with a **separate** output path:

```bash
python3 scripts/evidence/p1_g2_rc01_assignment_native_v2.py \
  P1-G2-RC01-ASSIGNMENT-ENVELOPE-NATIVE-MATRIX-V2-RETURNED.xml \
  --output /separate/path/p1-g2-rc01-native-v2-result.json
```

Native V2 remains **NOT RUN / REQUIRED**. P1-G2 stays **OPEN**;
P1 remains **4/5 IN PROGRESS** and P2 **NOT STARTED**.
