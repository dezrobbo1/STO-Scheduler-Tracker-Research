> **Status.** The approved consolidation plan, written 2026-09-02 and approved
> the same day. Phase 0 is built (see `docs/goals/ACTIVE.md` for live status);
> everything after it is design, not yet implemented. Sections A, C and B are the
> engine, platform and interchange designs; D is the phase sequence and its
> gates; E is the session-handoff work. Where this document and
> `docs/goals/ACTIVE.md` disagree about what is done, ACTIVE.md is right.

# STO: from four repos to one scheduler-centred product

## Context

**The ask.** STO is to become its own scheduler — not a clone of P6 or Microsoft Project — that
imports from a CMMS (SAP PM, IBM Maximo, Oracle EAM, others), from Primavera P6, or from Microsoft
Project; tracks, manages and schedules shutdown/turnaround work in real time; and exports back to
any of them. The question: how to get there from the current state of all `dezrobbo1` repos.

**Why now.** The 2 Sep 2026 estate review found four repos attacking the same problem with no
cross-referencing: ST-Claude's next deliverable was invalidated by evidence sitting in a sibling
repo; ST-Claude's agent contract pointed at deleted files; the no-CPM boundary one repo treats as
inviolable is unknown to the two repos building CPM; four MSPDI parsers with no cross-check. The
user has decided to consolidate around STO-Scheduler-Tracker-Research and reaffirmed the
own-scheduler direction after hearing the caution against it.

**Decisions already taken (user, 2 Sep 2026):**
1. CMMS: one canonical work-order model + a configurable mapped-file (Excel/CSV) adapter FIRST,
   then named SAP PM, Maximo, Oracle EAM adapters; live APIs later. Oracle EAM and "other" CMMSs
   are explicitly in scope.
2. Interchange: Python core + Java MPXJ sidecar (reuse ST-Claude `services/project-worker`).
3. Real time (v1): offline-capable field progress lands in the live schedule and the affected
   chain reschedules within seconds; single planner editing.
4. Repos: `STO-Scheduler-Tracker-Research` becomes the monorepo; `Shutdown-Tracker-Claude` and
   `Shutdown-Tracker` are frozen as reference; `PM-Software` stays research.

**Working constraints.** Solo developer with AI agents. Both STO's and PM-Software's `AGENTS.md`
enforce a capability-first rule — every slice must add something demonstrable; hardening, docs
and refactors are supporting work. The plan below is sequenced as capability slices for that
reason. No "fourth reset": ST-Claude stays deployed and untouched until parity.

## Verified starting state (2 Sep 2026)

| Asset | Where | State | Disposition |
|---|---|---|---|
| CPM engine (forward, FS-only, ASAP-only, no float/progress/levelling) | STO `src/sto_scheduler_core/calculation_*.py` | Works; 46 fail-closed reason codes; BOILER 282/460 eligible, 0 diffs vs stored dates | **Frame** for new engine (calendar model, eligibility, provenance) |
| Reference CPM kernel (FS/SS/FF/SF, signed lag on successor calendar, SNET/FNET, actuals, retained-logic/progress-override, restricted float) | PM `src/deterministic_scheduling_core/cpm/kernel.py` | Works; corpus-locked to 49 cases; integer time | **Lift semantics**, not code wholesale |
| Calendar interval arithmetic (incl. reverse lag shift) | PM `calendars/arithmetic.py` | Clean, general | **Lift** |
| Independent result validator (13 checks, separate representation) | PM `validation/result_validator.py` | Works | **Lift pattern** |
| 50 semantic conformance cases | PM `benchmarks/semantic/` | Pass 49/50; runner hard-wired to PM kernel | **Adopt cases**, write new runner |
| CP-SAT resource-constrained formulation | PM `gate1_experiment.py` | Works on 18 activities; throwaway structure | **Lift formulation** for levelling stage |
| Canonical schema v0.1.3 (resources w/ capacity types, exec modes, 11 operational-constraint classes, forecast/scenario/governance envelope) | PM `schemas/canonical-schedule.schema.json` | Schema+validator; no executable semantics | **Vocabulary** for unified model |
| MSPDI importer (hand-rolled, opaque retention) | STO `mspdi*.py` | Works on BOILER | **Oracle only**, then retire |
| MPXJ 16.4 worker (UniversalProjectReader → reads MPP/MSPDI/XER/PMXML) | ST-Claude `services/project-worker` | Works; thin extraction; MSPDI-DOM writer of the *disproved* 3-field set | **Reuse + widen**; replace writer field set |
| Proven Project completion transaction + fail-closed profiles + bulk composition + 3-category delta classifier | Shutdown-Tracker `src/*.js`, ST-Claude `docs/product/project-progress-field-contract.md` | Project-verified (builds .20188 single, .20186 bulk 13) | **Port** into Java writer; docs verbatim |
| Native evidence register discipline | Shutdown-Tracker `docs/NATIVE-EVIDENCE.md` | 3 entries, hashes + build numbers, untouched-source control | **Product-grade deliverable**, generalise to P6 + CMMS |
| Execution model (6 state machines, 3-queue review chain, idempotency pattern, 9 roles × 24 capabilities, problems/actions/evidence/handover, critical watch) | ST-Claude `services/api/**`, `infra/migrations/V001–V015` | Works, deployed, Java | **Port domain to Python**; adapt migrations |
| Offline field queue + shell-only service worker | ST-Claude `apps/mobile-pwa/src/*` | Works | **Move**, repoint at new API |
| Console + field React apps, TS api-client | ST-Claude `apps/*`, `packages/api-client` | Work | **Move**, repoint |
| 10 stack-independent product contracts | ST-Claude `docs/product/*.md` | Authoritative | **Move verbatim** |
| Prototype 0 workspace (in-memory, one scenario, full recompute) | STO `workspace*.py` | Works, loopback | **Replace** with persistent API |
| Dead duplicate UI | STO `workspace_web/` | Unwired | **Delete** |
| Deployment (Caddy + Cloudflare tunnel, systemd, header-trust identity) | `/home/dez/shutdown-tracker-deploy/` | Live | Keep until parity; then Compose + real auth |

**Office.js ceiling (verified 2 Sep):** Common API only, Windows desktop only, no assignment or
timephased API — the add-in cannot write the proven completion transaction. Interchange stays
file-based (MSPDI/PMXML/XER via MPXJ); the add-in spike is a side experiment, not a path.

---

## A. Canonical model and scheduling engine

### A.0 Decisions
| Decision | Choice | Why |
|---|---|---|
| Engine base | New package `sto.core.engine`, lifting from both STO and PM | STO's forward pass (`calculation_engine.py:262-299`) is FS/ASAP-only with a validator that hard-rejects anything else; PM's kernel is corpus-locked and its `earliest_span` scans every integer coordinate. Neither survives as a frame; both have precise liftable pieces. |
| Time | Wall-clock naive local datetimes at rest (ISO-8601, integer seconds); integer-second offsets from a per-run epoch inside the engine | MSPDI/XER/CMMS all store project-local wall-clock; the engine gets PM's integer arithmetic; PM's 50 cases bridge via `origin + unit × value`. |
| Typing | stdlib frozen `@dataclass(slots=True)` + `Enum`, hand-written `to_dict/from_dict`, JSON Schema *generated* and checked in with a drift test | Core stays stdlib-only (STO constraint); canonical hashing stays under our control (keep PM `canonical_json.py`'s raise-on-float + NFC). Pydantic only at the API boundary package. |
| Calendar for the engine | `CompiledCalendar` = sorted half-open `(start_s, finish_s)` intervals over the horizon, compiled from STO's weekly pattern + base inheritance **with exceptions applied** | Makes PM `arithmetic.py` reusable verbatim; exceptions become interval subtraction at compile time. |
| Levelling | Separate optional stage `sto.core.levelling` (extra `[levelling]`, OR-Tools pinned), output `LevellingResult` layered on an unchanged `CpmResult` | Keeps the deterministic CPM claim clean; mirrors P6 levelling delay / MS `LevelingDelay`. |
| Identity | UUIDv5 from `(schedule_id, source_system, entity_kind, external_uid)` on first sight, persisted in an `IdentityMap`; re-import reconciles exact → GUID → business key → mint | Two imports of one file hash identically; a later snapshot keeps the same UUIDs. `schedule_id` = MS project GUID / P6 `proj_id`+`proj_short_name`. |

### A.1 Canonical model v1 (`src/sto/core/model/`)
Files: `enums.py`, `ids.py`, `entities.py`, `execution.py`, `results.py`, `codec.py`, `schema_gen.py`, `validate.py`, `migrate/sto_v011.py`, `migrate/pm_v013.py`. Every entity carries `uid`, `external_refs: tuple[ExternalRef]`, `source_fields` (preserved raw values).

- **Provenance:** `ExternalRef(system{MicrosoftProject, PrimaveraP6, SAP_PM, Maximo, OracleEAM, STO}, kind, uid, id, guid, snapshot_sha256)`; `SourceSnapshot(format{MSPDI,MPP,XER,PMXML,CSV,API}, file_sha256, importer_profile, inventory)`; `IdentityMap` + `ReconciliationReport{matched,new,missing,rekeyed}`.
- **Schedule root:** `Schedule(schema_version="sto-canonical-1.0", project: ProjectSettings, snapshots, wbs_nodes, activities, relationships, calendars, resources, roles, assignments, curves, activity_code_types/values, udf_definitions, baselines, vendor_extensions, compatibility)`.
- **`ProjectSettings`:** start, status_date (MS StatusDate / P6 data_date), `progress_policy{none, retained_logic, progress_override, actual_dates}`, schedule_direction, default_calendar_ref, must_finish_by, `lag_calendar_policy{predecessor, successor, project, elapsed_24h}`, critical_float_threshold_s, `milestone_snap_policy{none, next_working}`, minutes_per_day/week, days_per_month.
- **`WbsNode`:** first-class P6 hierarchy (parent_ref, code, name, seq, level) with `ms_projection{task_uid, ...}` so MS summary tasks round-trip and P6 WBS can be written as MS summaries.
- **`Activity`:** wbs_ref, code, name, `kind{task, start_milestone, finish_milestone, level_of_effort, wbs_summary, hammock}`, active, manual, `duration_type{fixed_duration_units, fixed_duration_units_per_time, fixed_units, fixed_work}`, effort_driven, planned/remaining/actual duration_s, `percent_complete{type{duration, physical, units, work}, value_permille}`, actual_start/finish, suspend/resume, calendar_ref, primary/secondary `Constraint{type{asap, alap, snet, snlt, fnet, fnlt, mso, mfo}, date}`, deadline, expected_finish, priority, levelling_delay_s, activity_codes, udfs, notes, `source_observations{start, finish, early/late dates, total/free float, critical}` (read-only, for the file oracle).
- **`Relationship`:** pred/succ, `type{FS,SS,FF,SF}`, lag_s signed, `lag_calendar{predecessor, successor, project, elapsed_24h, inherit_project_policy}` (MS LagFormat elapsed codes → `elapsed_24h`), cross_project, source codes.
- **`Calendar`:** `type{global, project, resource, shift, base}`, base_ref, 7-day week of intervals, `exceptions: tuple[CalendarException(from, to, working, intervals)]`, hours_per_day/week/month. STO `DayType 0` special days become exceptions at import.
- **`Resource`:** code, name, `type{labor, nonlabor, material}`, `scheduling_class{renewable, exclusive, cumulative, non_renewable}` (PM vocabulary), max_units_permille, calendar_ref, parent_ref, skills, location, inactive. `Role` (P6).
- **`Assignment`:** activity/resource/role refs, `units{budgeted, actual, remaining, at_completion}`, `work_s{budgeted, actual, remaining}`, curve_ref, start/finish, timephased_ref (opaque blob), percent_work_complete. `ResourceCurve` (P6 curves + MS WorkContour 0..8 as named curves).
- **Codes/UDFs:** `ActivityCodeType(scope)`, `ActivityCodeValue`, `UdfDefinition(owner_kind, data_type, ms_field_id, p6_udf_type_id)`.
- **`Baseline`:** typed sets (`kind{ms_baseline0..10, p6_project_baseline, sto_snapshot}`, per-activity/assignment states) — replaces STO's key-value bags.
- **Results (never inputs, `results.py`):** `CpmResult(input_hash, engine_version, epoch, project_finish, activities→ActivityDates{early/late, remaining_early_start, floats, critical, driving_preds}, wbs_rollup, assumptions, excluded, topological_order_sha256)`; `LevellingResult(cpm_result_id, SolverIdentity, delays, resource_order, verifier_status)`.
- **Execution layer (`execution.py`, append-only, correction by supersession):** `ExecutionEvent` base (offline_local_id, idempotency_key, supersedes_ref) → `ProgressUpdate` carrying ST-Claude's four state machines 1:1 (execution / progress-review / planner-review / export states); `Problem`, `Action`, `EvidenceRef`, `HandoverNote`. **`ExecutionProjection`** folds accepted updates into per-activity actuals + status_date — the only path execution reaches the engine. Feed policy per project: `live_forecast_feed = submitted`, `export_feed = supervisor_accepted + planner_approved`.
- **Migration:** `migrate/sto_v011.py` (dict → v1: `lag_tenths_minutes`→`lag_s`×6, `*_source`→`source_observations`, MS Type 0/1/2→duration_type, summary tasks→`WbsNode.ms_projection`); `migrate/pm_v013.py` (case schedule → v1: origin as epoch, explicit compiled calendars, snet/fnet, `demand`→units). Old profile strings retired; historical evidence under `docs/history/`.

### A.2 Engine slices (`src/sto/core/{calendar,engine,execution,levelling,operational}/`, `src/sto/conformance/`)
| # | Capability demonstrated | Lifted from | Oracle | Days |
|---|---|---|---|---|
| **S1** Model v1 + MSPDI→v1 + identity | `sto import boiler.xml` → typed v1; two imports hash identically; original BOILER then `~/BOILER-WG110-day5-candidate.mspdi.xml` reconcile with same UUIDs (expect 555 matched, 7 new). Delete `workspace_web/`. | STO `mspdi*.py`, `opaque.py`, `duration.py`, `provenance.py`; PM `canonical_json.py` rules | hash equality; schema drift test; `from_dict(to_dict(x))==x`; reconciliation counts | 4 |
| **S2** Calendar compile + arithmetic | All 45 BOILER calendars (40 exceptions, 65 special days) compile; `add/sub_working`, `next/prev_working` O(log n) via bisect | STO `_CalendarResolver` + fingerprint; PM `arithmetic.py` (`shift_working_time` reverse = backward-pass primitive); rewrite PM `earliest_span` | differential test vs STO `_add_working_seconds` (10k pairs); PM SEM-CAL-021..030; BOILER exception days non-working | 3 |
| **S3** Forward pass: FS/SS/FF/SF, signed lag w/ lag calendar, SNET/FNET, milestones | early dates for **all** not-started leaves; PM REL+NET+CAL+MIL+CON-035/036 (36 cases) pass via new runner `conformance/semantic_suite.py` | PM kernel bound formula (`_calculate_candidate`); STO Kahn order `(seq, uid)` | 36 PM cases byte-identical; BOILER file oracle **without** self-consistency gate, every diff classified, zero `UNEXPLAINED` | 4 |
| **S4** Backward pass, float, critical, ALAP/SNLT/FNLT/MSO/MFO/deadline | late dates, total/free float, driving preds; compare 562 stored `LateStart/LateFinish/TotalSlack/FreeSlack/Critical` | PM `_add_restricted_float`; STO `compare_source_coordinates` extended to 5 fields | SEM-FLT-047/048; BOILER late/float; pre-register KVD sub-codes (`KVD-MS-SLACK-CALENDAR`, `KVD-MS-OPEN-END`) | 4 |
| **S5** Status date, actuals, remaining, retained-logic / progress-override, out-of-sequence, %-complete types | schedule day5-candidate (StatusDate 2025-05-09T17:00, 8 progressed tasks) and reproduce stored dates; PM STA-039..044, 046 | PM kernel progress rules | 7 PM STA cases; day5 file oracle; **genuine Project-recalc oracle**: ST-Claude `fixtures/project-files/boiler/boiler-before-no-progress.xml` → `boiler-after-native-progress.xml` (UIDs 43/318/319) and `boiler-roundtrip-project-saved-task43.xml` | 4 |
| **S6** WBS rollup, eligibility re-partition, independent validator | 460/460 BOILER leaves get a disposition (computed / pinned-with-assumption / excluded); summaries roll up; validator re-derives on a separate representation | STO 46 reason codes; PM `IndependentResultValidator` | validator `pass` on BOILER + 47 PM cases; rollup vs 95 BOILER summaries | 3 |
| **S7** Execution layer + incremental reschedule + live workspace | `POST /progress` with idempotency key → `ProgressUpdate` → affected chain reschedules → `ScheduleDiff`; replay is a no-op; 5k activities / 8k rels update &lt;100 ms, full &lt;1 s | ST-Claude state machines + supersession rules; STO scenario-copy discipline | property test `incremental(state,Δ) == full(apply(state,Δ))` on 1k random DAGs; latency bench | 5 |
| **S8** MSPDI writer + proven progress transaction + round-trip register | export accepted by Project; completed-task field set == proven transaction (task 10 fields, assignment 6, timephased Type 1→2) | ST-Claude `project-progress-field-contract.md`; Shutdown-Tracker `project-result-semantics.js` field sets → Python classifier | field-for-field diff vs `boiler-roundtrip-project-saved-task43.xml`, zero `unexpected_difference`; native reopen = manual register entry | 4 |
| **S9** Resource levelling (CP-SAT) | per-activity delays, verifier confirms no capacity violation, byte-identical across 3 processes, `CpmResult` hash unchanged | PM `gate1_experiment.py` formulation + `build_baseline` + `feasibility_errors`; PM 7-level objective | SEM-DET-049/050; Gate-1 sample 48h→38h; BOILER 32 resources | 5 |
| **S10** Operational constraints (differentiator) | permit windows, isolation states, SIMOPS, workface occupancy honoured by levelling; hard violations enumerated | PM 11 constraint classes → CP-SAT (`no_overlap`, `cumulative`, windows) | synthetic fixtures with known optimum; zero violations | 5 |
| **S11** CMMS work-order CSV (first cut; full design in B) | SAP order/operation CSV → activities under functional-location WBS; actual hours back as CSV | — | blocked on a real sample | 3 |

**Eligibility re-partition (S6)** — from "exclude" to "schedule with `Assumption`" for `ESTIMATED_DURATION`, `DURATION_FORMAT`, `MULTIPLE_RESOURCE_CALENDARS` (schedule on task/project calendar, flag), `WORK_UNITS_INCONSISTENT`, `ASSIGNMENT_CONTOUR`, `REMAINING_DURATION_MISMATCH`, `EFFORT_DRIVEN`, `IGNORE_RESOURCE_CALENDAR_*`; `INELIGIBLE_PREDECESSOR` **replaced** by pinning the excluded predecessor to source dates (`PREDECESSOR_PINNED_TO_SOURCE`) so 219 BOILER successors stop cascading out; pin-to-source for `ACTIVITY_MANUAL`, `CROSS_PROJECT`, `EXTERNAL_TASK`; hard exclusions kept for inactive/null/recurring/subproject, bad durations, structural calendar errors, bad endpoints; the four comparison-only codes (`SOURCE_START_OUTSIDE_WORKING_TIME`, `SOURCE_SPAN_MISMATCH`, `SOURCE_COORDINATE_MISSING`, `SOURCE_DATETIME_UNSUPPORTED`) removed from eligibility and moved to the comparison taxonomy.

**Incremental reschedule (S7):** resident `ScheduleGraph` (adjacency, topo index, compiled calendars cached by fingerprint, last `CpmResult`). On change set Δ: forward-propagate along successors in topo order with early-exit when recomputed bounds equal previous; if any sink's early finish changed → project finish changed → full backward pass, else backward-propagate from changed nodes with early-exit. Diff derived from two hashed results, never from the propagation.

**Conformance ladder:** (1) PM 50 cases copied verbatim into `benchmarks/semantic/` with SHA-256 pins, new runner; (2) file oracle `conformance/file_oracle.py` — BOILER both snapshots (Start/Finish/Late/Slack/Critical) and any XER's `early_*/late_*/total_float_hr_cnt/free_float_hr_cnt` (**first real XER is a hard dependency**); (3) MPXJ parse oracle (section B); (4) native round-trip register per target/build.
**Unified difference taxonomy** (`conformance/taxonomy.py`): STO's six — `IMPORT_DEFECT`, `CALCULATION_DEFECT`, `UNSUPPORTED_SEMANTIC`, `KNOWN_VENDOR_DIFFERENCE`, `SOURCE_INCONSISTENCY`, `UNEXPLAINED` — plus Shutdown-Tracker's `SERIALIZATION_NORMALIZATION` and `TARGET_CALCULATED_CONSEQUENCE`. Rule kept: no semantic declared `Full` while any `UNEXPLAINED` remains.
**Determinism:** canonical hash at every stage boundary (v1 doc → `EngineInput` → `CpmResult` → `LevellingResult` → export bytes); levelling isolated with `num_search_workers=1`, `random_seed=0`, `max_deterministic_time`, pinned `ortools`, `SolverIdentity` recorded, claim text "reproducible under pinned runtime; not part of the deterministic CPM claim".

**Stated hypotheses to verify, not facts:** P6 lag calendar is project-wide; MS non-elapsed lag uses the successor calendar; which calendar MS measures `TotalSlack` in (fit from BOILER in S4). Partial-progress `Stop/Resume` unevidenced → `Assumption: SUSPEND_RESUME_IGNORED` until a sample exists.

---

_Sections are ordered A (model + engine) → C (platform, real-time loop, migration) → B (interchange + CMMS) → D (unified roadmap and verification); B follows C because its export slices depend on C's export lifecycle._

## C. Platform, real-time loop, migration

### C.0 Host facts that fix the design (verified on this box, 2 Sep 2026)
No Docker. Postgres 16.2 from embedded binaries as `shutdown-tracker-postgres.service` on 127.0.0.1:5433. Java API on 8090; MPXJ worker already a service on 8091 with shared-secret header auth. Caddy `:80` (`admin off`) + Cloudflare tunnel; deploy config outside git in `/home/dez/shutdown-tracker-deploy/`. Python 3.13.5 (no `pip3`), Node 22, JDK 21, Maven 3.9.9, psql 17. `/home/dez/Shutdown-Tracker` is a **stale pre-reset clone** (delete after consolidation). `/home/dez/FieldTrack` is a fifth React prototype — frozen; absorb two ideas (dead-letter after N non-4xx failures >24 h, hours-weighted crew progress).

### C.1 Stack decisions
| Area | Decision | Why |
|---|---|---|
| Runtime | Python **3.12+**, `uv` (env + lockfile; `uv sync --frozen` in redeploy) | No pip3 on host; one binary |
| Core purity | `sto.core.*` and the Python MSPDI importer stay **stdlib-only**, enforced by an import test | Preserves STO's hash/fail-closed discipline; engine testable without DB |
| Web | **FastAPI + uvicorn, 1 worker**, on **8090** (same port as the Java API → Caddyfile `/api/*` unchanged at cut-over); pydantic v2 only in `sto.api.schemas`, mapped to core dataclasses | OpenAPI → TS types; async for SSE fan-out |
| Live updates | **SSE** `/api/projects/{id}/events` with durable `project_events` outbox + `Last-Event-ID` resume; Caddy `flush_interval -1`; no WebSocket in v1 | Server→client only; writes stay plain idempotent POSTs |
| Background work | asyncio in-process; engine in `asyncio.to_thread`; durable `jobs` table (`FOR UPDATE SKIP LOCKED`) for sidecar parse/export | One process, one box; survives restart |
| Persistence | PostgreSQL 16 on the existing 5433 instance, new DB `sto`; **psycopg 3 + hand SQL**, no ORM | ST-Claude's SQL and tests transfer directly |
| Migrations | Flyway-style `V###__.sql` + ST-Claude `scripts/db/{apply-migrations,check-schema-drift,backfill-migration-log}.sh` **verbatim**; no Alembic | Proven tooling; drift guard already exists |
| Enums | **TEXT + CHECK**, never PG enums; test asserts CHECK list == Python `Enum` | V015's enum rebuild is the lesson |
| Schedule storage | `schedule_versions(id, project_id, kind, parent_id, canonical_hash, engine_profile, cause_type, cause_id, document JSONB nullable, delta JSONB)`, `schedule_heads(project_id, kind → version_id)`, `schedule_task_projection(version_id, activity_ref, es, ef, ls, lf, total_float, critical, pct, remaining)`; full document every 50th version or on kind change, deltas between | Immutable versions + movable head = working copy without mutation; projection table gives SQL joins for queues |
| Working model | In-memory `WorkingSchedule` per project (evolution of STO `WorkspaceSession`), rebuilt on boot from last full doc + deltas, `asyncio.Lock` per project | Sub-second reschedule needs the graph resident; single writer is the product decision |
| Frontend | Keep React/Vite console + field; `openapi-typescript` generates `packages/api-client/src/generated.ts`; hand-written functions stay | Type drift is the real risk |
| Gantt | Port STO's vanilla Gantt to `packages/gantt` (dependency-free SVG, virtualized rows); revisit >10k tasks by ADR | No licence; avoids drifting to a P6 look-alike |
| Auth | **Built-in argon2id password + TOTP**, server sessions in Postgres, HttpOnly SameSite cookie + CSRF double-submit; field PWA gets 30-day rotating device refresh tokens (IndexedDB), exchanged for a session at flush; admin bootstrap via `uv run sto admin create-user`; OIDC later via `users.external_subject` (already in V008) | Keycloak = another service on a Docker-less box; TOTP may be waived per project policy for field roles (ADR) |
| Sidecar auth | Existing shared-secret header, secret from `/etc/sto/env` | Already in `WorkerAuthFilter` |
| Deployment | systemd units in-repo (`infra/deploy/`), Caddy + tunnel unchanged, `redeploy.sh` semantics kept; `infra/compose/` for dev/CI only | Docker absent |
| CI | `ruff`, `pyright` (strict new / basic moved), `pytest` (collects the 14 existing unittest modules unchanged, Postgres service), `mvn test` (worker only), `npm test && npm run build`, `validate-migrations.sh`, engine conformance job over the 50 PM cases | Mirrors what each repo already proves |

### C.2 Monorepo tree (`STO-Scheduler-Tracker-Research` → rename `STO` at cut-over; GitHub redirects)
```
AGENTS.md  README.md  pyproject.toml (package "sto", uv.lock)  pom.xml (worker + 2 contract modules)  package.json (npm workspaces)
src/sto/
  core/model/        canonical schedule (A.1); stdlib dataclasses
  core/engine/       CPM + incremental (A.2)
  core/calendar/     compile + arithmetic (A.2)
  core/execution/    pure states, events, ExecutionProjection (A.1)
  core/hashing.py    from STO provenance.py + PM canonical_json rules
  core/levelling/  core/operational/
  interchange/mspdi/ STO Python importer (moved) + writer + progress_transaction
  interchange/xer/   pure-Python XER reader (file oracle)
  interchange/mpxj/  worker_client.py (sidecar), crosscheck.py
  interchange/profiles.py  export_policy.py       from Shutdown-Tracker JS + ST-Claude V007 rules
  cmms/              work-order model + mapped-file adapter + named adapters (B)
  scheduling/        working_schedule.py, live.py, forecast.py, leases.py, scenarios.py
  execution/         progress.py, review.py, export_binding.py, problems.py, evidence.py, handover.py, critical.py  (DB-backed services)
  identity/          roles.py, capabilities.py, authorization.py, auth/{passwords,totp,sessions,devices}.py
  audit/recorder.py  persistence/ (psycopg repos, blobs.py, events_outbox.py, jobs.py)  api/ (FastAPI, routers/, events.py, codegen.py)
  conformance/       semantic_suite.py, file_oracle.py, taxonomy.py, roundtrip_register.py
services/project-worker/   Java 21 MPXJ sidecar, moved verbatim (+ import/export contract modules)
apps/console/  apps/field/ (base=/mobile/)  packages/api-client/  packages/design-tokens/  packages/gantt/
infra/migrations/V001…  infra/deploy/ (Caddyfile, sto-*.service, redeploy.sh, env.example)  infra/compose/
scripts/db/  docs/adr/ (+LEGACY-INDEX.md)  docs/product/  docs/evidence/{microsoft-project,p6,cmms,field}/ + register.json
docs/goals/ACTIVE.md  docs/research/ (STO phase docs, PHASE-0 audit, results)  fixtures/  benchmarks/semantic/  tests/
```
**Moved verbatim:** ST-Claude `docs/product/*` (+ `project-progress-field-contract.md` from GitHub main — missing locally), `docs/architecture/audit-event-schema.md`, `fixtures/**`, `services/project-worker/**`, both contract packages, `packages/design-tokens`, PWA offline files (`offlineQueue.ts`, `indexedDbQueueStore.ts`, `serviceWorkerPolicy.ts`, `sw.ts`), `scripts/db/*.sh`, V002/V004/V008 SQL, `Capability` grant table as data; STO engine/importer/hashing/fixtures/results; Shutdown-Tracker `docs/NATIVE-EVIDENCE.md` → `docs/evidence/microsoft-project/`; PM 50 cases.
**Ported (Java/JS → Python):** `TaskProgressService`, `ProjectAuthorizationService`, review/export/problem/evidence domain; V005/V006/V009/V010/V012/V013/V014 (→ `activity_ref`, TEXT+CHECK); `transaction-profiles.js`, `bulk-planned-completion.js`, `project-result-semantics.js`; STO Gantt → React.
**Retired:** STO `workspace_web/`, `workspace_server.py` (after P1); Shutdown-Tracker JS parser; ST-Claude `services/api` (240 files); V007's 1,300-line trigger policy (re-expressed as `export_policy.py` + unique constraints, by ADR); V015 (fresh schema starts at surviving lifecycle); review-demo seeder + `RESET_REVIEW_DATA` (→ `sto admin` CLI + fixtures); build-time actor env vars.

### C.3 Platform slices (P-numbered; interleaved with engine S-slices in section D)
| # | Capability | Key work | Verify | Days |
|---|---|---|---|---|
| **P1** Persistent multi-project workspace | Import two MSPDI files into two projects; restart; both persist with hashes; legacy Gantt served from `apps/console-legacy/` against `/api/projects/{id}/schedule/live` | `git mv sto_scheduler_core/* → src/sto/**` (history kept); FastAPI on 8090; `V001` = ST-Claude V002 verbatim + `schedule_versions/heads/task_projection`; `uv`, ruff, pyright, pytest; delete `workspace_web/` | import→restart→same `canonical_hash`; pytest green; drift guard on fresh DB | 4 |
| **P2** Real login and roles | Planner logs in (password+TOTP) and imports; viewer gets 403 naming the capability; header-trust path gone | `V002` = ST-Claude V008 verbatim + `user_credentials`, `sessions`, `device_sessions`; port `Capability`/`ProjectRole`/`ProjectAuthorizationService`; `require(Capability.X)` dependency; `identity.ts` **generated** from the Python enum, CI fails on drift; login screens; remove `VITE_*_ACTOR_*` | httpx auth tests; parity table; test that no route accepts `X-Shutdown-Tracker-Actor-Id` | 4 |
| **P3** Sidecar absorbed + import cross-check | Upload `.mpp` → MPXJ → canonical; upload MSPDI → Python importer **and** MPXJ both parse → cross-check report (counts, UID set, date/duration disagreements) | subtree/copy `services/project-worker` + contracts with `PROVENANCE.md`; `interchange/mpxj/worker_client.py`, `crosscheck.py`; exclude `DataSourceAutoConfiguration` in the build not the unit | `mvn test` (75 tests) in CI; synthetic fixtures give empty cross-check diff | 3 |
| **P4** Live execution loop v1 | `POST /progress` with idempotency key → within 1 s the SSE-subscribed Gantt moves the affected chain; replay returns original; new version has hash + `cause` | `V003` = ST-Claude V009 adapted (`activity_ref`, TEXT+CHECK, `applied_schedule_version_id`); `execution/progress.py` (port `submit`); `scheduling/live.py`; `persistence/schedule_versions.py`; `api/events.py` + outbox; `V004` = ST-Claude V004 audit verbatim | 200 posts on BOILER-shaped fixture, p95 POST→SSE < 1 s; idempotent replay; replaying the update log from baseline reproduces head hash | 5 |
| **P5** Field app ported and offline | Airplane mode: report 3 tasks; go online; they land, chain reschedules, My Work reorders live | `apps/field/` = `apps/mobile-pwa` moved; offline files verbatim; `vite.config.ts` `base: "/mobile/"`; device-session auth; `useProjectEvents.ts` (bounded REST refresh on reconnect gap); FieldTrack dead-letter + hours-weighted progress | existing 49 mobile tests + Playwright offline script recorded in `docs/evidence/field/` | 5 |
| **P6** Review chain as export governance | Live Gantt shows unreviewed progress hatched; supervisor accepts, planner approves → **approved_forecast** updates only then; toggle between versions | port `supervisorReview`/`plannerReview`/3 queues → `execution/review.py` (409 on wrong state, `producesExportCandidate` rule kept); `ExportBatchProgressBinding` → `export_binding.py`; `scheduling/forecast.py`; console review zones ported | state-machine tests ported from Java; forecast rebuild test | 4 |
| **P7** Planner editing, lease, scenarios; React console replaces legacy | One planner holds the edit lease (heartbeat 30 s / TTL 90 s / admin break); second sees read-only; scenario branched from live, compared, promoted or discarded | `schedule_edit_leases`, `planner_edit_sets` (append-only); `packages/gantt` React port; `apps/console` gains Schedule zone; delete `console-legacy` | lease contention tests; scenario promote/discard tests | 5 |
| **P8** Export to Project with fail-closed profiles + evidence register | From approved_forecast: preview → approve → generate MSPDI via sidecar under a named profile; a profile without a `docs/evidence/` entry **cannot be selected**; batch records which updates it carried | `V005` = ST-Claude V005 + V007's three freeze-history triggers verbatim; V007 policy suite retired → `export_policy.py` (ADR); `interchange/profiles.py` from `transaction-profiles.js`; bulk reporting-cut + 3-category classifier ported; V014 candidate return (content-hash idempotency) | test binds profile registry to `docs/evidence/register.json`; export lifecycle tests | 5 |
| **P9** Problems, actions, evidence, handover | Raise a blocking problem offline → task shows blocked in live schedule, engine treats remaining as suspended from data date; close → chain reschedules | V010+V012+V013 adapted; `persistence/blobs.py` (`/var/lib/sto/evidence`); console zones ported | state tests; blocked→suspend→reschedule test | 5 |
| **P10** Critical watch + reporting periods | Critical updates against work packages on a reporting policy | V006 adapted; fix `critical_updates.idempotency_key` to partial unique | ported tests | 4 |
| **P11** CMMS mapped-file seam | `POST /imports?source=cmms-mapped-file` → same cross-check report as P3 | `sto/cmms/` boundary (internals in B) | fixture round-trip | 2 |
| **P12** Cut-over | New stack passes the parity checklist; ports swap in one redeploy; frozen repos banner'd and archived | `infra/deploy/` in git (Caddyfile + `flush_interval -1`, `sto-api/-project-worker/-postgres.service`, `redeploy.sh` with drift guard, `env.example`; secrets in `/etc/sto/env`); trial period: new API on 8092 served at `/sto/`, then swap to 8090 | **Parity checklist** (recorded in `docs/evidence/cutover-<date>.md`): import MSPDI + .mpp; accept snapshot; task table w/ resource groups; field progress offline→online; supervisor + planner review; export preview→approve→generate→download; candidate return + delta; problem offline; evidence upload; critical update; users/memberships in UI; login required everywhere; drift guard green; `/mobile/` PWA updates in place on a device with the old one installed. No data migration (old DB is synthetic review data); keep 30 days read-only, then drop | 3 |

### C.4 Real-time loop (the product's core behaviour)
**Version kinds per project:** `baseline` (accepted import, immutable) → `approved_forecast` (baseline logic + planner-published edits + **reviewed** progress; what exports/reports read) → `live_working` (approved_forecast + **all** reported progress marked unreviewed + planner's in-progress edits; what Gantt and My Work show) → `scenario` (planner what-if; promote or discard).
**Flow:** (1) device enqueues offline with `idempotencyKey` + `offlineLocalId`; (2) on `online`, sequential flush, device token → session, `POST /progress`; (3) authn + `require(SUBMIT_TASK_PROGRESS)`; validate against current live version (leaf, legal transition, reason for paused/blocked); stale → **409 `STALE_SCHEDULE`** (add 409 to the queue's non-permanent set); (4) **Txn 1 ≤150 ms:** lookup-before-insert on `(project_id, idempotency_key)`; insert update (`submitted`/`not_required`/`not_eligible`); supersede prior; upsert execution state; audit; outbox `progress.submitted`; 201 → SYNCED; (5) under project lock, `live.apply(update, policy)` (retained_logic default / progress_override / actual_dates; status date advanced by control or hourly auto); (6) `engine.reschedule_incremental(affected)`; full recompute if closure > 40 %; (7) **Txn 2 ≤100 ms:** new `schedule_versions` row (kind=live_working, delta, `canonical_hash` over full in-memory doc), move head, refresh projection rows, set `applied_schedule_version_id`, outbox `schedule.version{changed:[…, review:'unreviewed']}`; (8) SSE pushes; console patches bars (hatched = unreviewed), field re-sorts My Work (blocked → in progress → not started → done) via `project_resource_links`; (9) governance in parallel: supervisor accept → `needs_planner_review` if leaf + whitelisted field; planner approve → `eligible` + `forecast.rebuild()` → new approved_forecast; correction/reject → supersede + `live.revert`; (10) export preview claims eligible updates, builds from **approved_forecast** under a named profile; (11) planner edits under the same lock, each a version with `cause=planner_edit_set`; "publish" copies logic changes into approved_forecast.
**Latency budget** (p95, 5k activities): store 150 + apply/reschedule 300 + persist 100 + SSE 50 + render 100 ≈ **0.7 s**; hard ceiling 3 s then "recalculating".

### C.5 Governance
- **One `AGENTS.md`:** Shutdown-Tracker's forward-progress test + STO's productive-line clause + ST-Claude's safety/validation/migration/fixture rules, **minus** "no CPM / Project is the authority", replaced by: STO is the scheduler; imported sources immutable, every export a separate candidate; profiles labelled baseline/diagnostic/native-evidence-derived and fail closed; the three claims (approved inputs correct / target produced a result / planner adopted) never conflated; append-only audit + supersession; **the live schedule may change automatically, the exported forecast only through review.**
- **ADRs restart at 001** with `docs/adr/LEGACY-INDEX.md` mapping `STC-ADR-001…011`, `ST-ADR-001…012` (cite repo+commit; the accepted pre-reset ADR-012 no longer exists on main), and STO/PM phase docs → superseded / carried / withdrawn. First ten: 001 monorepo + frozen repos; 002 Python core / Java sidecar boundary; 003 schedule-version envelope; 004 live-vs-approved governance; 005 auth model; 006 TEXT+CHECK; 007 SSE; 008 Gantt port; 009 retire V007 trigger policy; 010 deployment (systemd, no Docker). **Resolves the ADR-012 collision.**
- **`docs/evidence/` is a first-class deliverable:** `register.json` (profile → target → build → date → hashes → status); test binds profile registry to it; `redeploy.sh` prints the count of native-evidence-derived profiles.
- **One `docs/goals/ACTIVE.md`**, updated in the same PR as each merged slice; CI check: a PR touching `src/` must touch `ACTIVE.md` or carry `no-goal-change`.
- Frozen repos: README banner "Superseded by dezrobbo1/STO (commit …)", `AGENTS.md` → one-paragraph freeze notice, GitHub archive.

### C.6 Risks
Java+Python for one person → sidecar stateless behind `worker_client.py`, touched only for XER work. Enum churn → TEXT+CHECK from V001. Losing the deployed field app → ST-Claude untouched until parity; `/mobile/` preserved. P6-parity creep → engine profile boundary + fail-closed `unsupported`; 50-case suite defines "done". Memory on large MSPDI → working model excludes vendor extensions; raw file on disk. Single-process state → bounded rebuild (last full doc + ≤50 deltas), documented v1 constraint. Importer-generation hash drift → cross-check in CI on every fixture. Auth lockout on headless box → `sto admin reset-password` over SSH.

---

## B. Interchange (P6 / Microsoft Project) and CMMS

### B.0 Verified facts and decisions
- MPXJ 16.4.0 jar on this box (`~/.m2/.../mpxj-16.4.0.jar`, checked with `javap`): `UniversalProjectWriter(FileFormat{JSON, MPX, MSPDI, PLANNER, PMXML, XER, SDEF})`; `MSPDIWriter.setWriteTimephasedData/setGenerateMissingTimephasedData/setMicrosoftProjectCompatibleOutput`; `PrimaveraPMFileWriter.setWriteBaselines`; `PrimaveraXERFileWriter.setCharset`; readers expose `getActivityCodes()`, `getUserDefinedFields()`, `getBaselines()`, `getRawTimephased*Work()`, `getCalendarExceptions()/getExpandedCalendarExceptions()/getWorkWeeks()`, `getRelationshipLagCalendar()`, `getStatusDate()`. **Cannot write `.mpp`.**
- `MspdiCandidateDifference.approvedFieldsFor` (`:190-203`) only understands `Task[uid]` paths — it cannot yet explain an approved change inside `<Assignment>`; must be extended for the proven transaction.
- The four BOILER proof fixtures exist on ST-Claude `origin/main` (`26a6a6e`) under `fixtures/project-files/boiler/`, not in the local clone.
- `~/BOILER-WG110-day5-candidate.mspdi.xml` custom-field aliases give the **site link convention**: `Text4 = "Work Order No."` (e.g. `WO<redacted>`), `Text5 = "Operation No."`, `Text15 = "Operation Description"`, `Text11 = "Work Group"`, `Text30 = "Assigned Department"`. Task UID 43 in that file is a live specimen of the disproved 3-field state.
- **Keep Spring Boot** in the sidecar (bearer filter, storage confinement, actuator, strict Jackson, 17 test classes already there); remove `spring-boot-starter-jdbc`, `flyway-*`, `postgresql` from `services/project-worker/pom.xml`. Rename env prefix `SHUTDOWN_TRACKER_*` → `STO_WORKER_*`. Python process manager generates the shared secret per boot.
- **Time:** adapters never convert; wall-clock naive ISO strings; the schedule carries an IANA zone stamped from the site profile.
- **STO's hand-rolled Python MSPDI parser:** oracle-only until the sidecar cross-check is green on all fixtures, then delete. `opaque.py` retired immediately — source bytes + SHA-256 + source-edit export replace lossy opaque retention.
- **Resolution of the A/B overlap:** the MSPDI/PMXML/XER *writers* live in the Java sidecar; engine slice S8 reduces to Python orchestration (`sto/interchange/export/`) + the 3-category classifier port; engine slice S11 is absorbed by I9–I12 below.

### B.1 Interchange slices (I-numbered)
| # | Capability | Modules | Proof | Days |
|---|---|---|---|---|
| **I1** Sidecar full extraction → canonical NDJSON | `POST /worker/v2/parse` on any MPXJ-readable file → gzip NDJSON sections (header, calendars w/ exceptions + work weeks, wbs, activities, relationships w/ type+lag+lag-format, resources, assignments, timephased planned/actual/remaining/baseline_n, baselines 0–10, codes, udfs, warnings, footer{sha256,counts}) | `canonical/CanonicalProjectMapper.java` (replaces `MpxjProjectEntityExtractionService`), `DurationMapper.java` (`{value, unit, elapsed}` + `source_format_code`), `CanonicalNdjsonWriter.java` (Jackson streaming), `handoff/WorkerParseV2Controller.java`, `WorkerStorageProperties.scratchRoot`. Rules: summary/P6-WBS → `wbs_node` + `summary_task_attributes`; **all** custom fields (drop the alias-only filter); P6 activity codes; lag calendar from `getRelationshipLagCalendar()` (P6) or `successor_calendar` for MS (flagged hypothesis); `ResourceUID -65535` → unassigned marker | JUnit expected-output on `synthetic-basic-wbs`, `synthetic-shutdown-areas` (+ `expected-canonical-counts.json`); BOILER local counts (635 links, 40 exceptions, 2,224 timephased rows, 45 calendars); NDJSON lines validate against the A.1 generated schema | 6 |
| **I2** Format detection + widen inputs | `POST /worker/v2/detect` → `{readerClass, fileType, fileApplication, applicationVersion, supportedExportTargets}`; API accepts `.mpp .mpt .mpx .xml .xer .pmxml .planner .pp .ppx .gnt .zip` | `canonical/FormatDetector.java`, `xml/HardenedXml.java` (moved from exporter); Python `sto/interchange/formats.py` `SourceFormat`/`ExportTarget` enums; upload validator calls detect, not extensions | detection fixtures per format | 1 |
| **I3** Python client + JVM process manager + loader | `sto import schedule <file>` end-to-end; sidecar health in `/api/health` | `sto/interchange/project_worker/{client.py (httpx, bearer, typed dataclasses), process.py (SidecarProcess: launch jar, per-boot secret, free port, health poll, restart-once, stop on shutdown, SIDECAR_MODE=external), ndjson.py, loader.py}` | pytest `@sidecar` with real JVM on synthetic fixtures; recorded-response fake for unit tests. Start JVM at API boot (3–5 s cold start) | 3 |
| **I4** Import oracle: Python parser vs sidecar | `sto oracle mspdi <fixture>` canonical diff; CI over STO `tests/fixtures/*.mspdi.xml`, ST-Claude synthetic fixtures, locally the four BOILER files | `sto/interchange/canonical_diff.py` (entity key `(type, external_uid)`, normalisation table: duration units, `-0.00`, whitespace, second precision), `oracle.py` | green on all fixtures for tasks/resources/assignments/calendars → **delete the Python parser** | 3 |
| **I5** Regenerate path: canonical → MPXJ `ProjectFile` → MSPDI / PMXML / XER, re-read proof | Schedules with no source (CMMS-derived, STO-authored) or cross-format export; each artifact re-read and canonical-diffed against input; unexplained loss fails | `exporter/regenerate/CanonicalToMpxjBuilder.java` (calendars → WBS as summaries → activities → relations → resources → assignments → timephased → custom fields → activity codes → baselines), `RegenerateExportService.java` (`UniversalProjectWriter`; MSPDI `setMicrosoftProjectCompatibleOutput(true)`, `setWriteTimephasedData(true)`; PMXML `setWriteBaselines(true)`; XER `windows-1252`), `ExpectedLossPolicy.java`, `proof/RegenerateProofReport.java`, `POST /worker/v2/export/regenerate`; Python `sto/interchange/export/regenerate.py` | round trips canonical→{MSPDI,PMXML,XER}→canonical on synthetic + BOILER-derived; expected-loss lists checked in at `fixtures/interchange/expected-loss/{mspdi,pmxml,xer}.json`; label `DIAGNOSTIC` until I13 evidence | 8 |
| **I6** Proven completion transaction in the Java source-edit writer | MSPDI candidate for an approved 100 % leaf task carries the full proven set (task 10 fields, assignment 6, timephased Type 1→2); whole-doc diff passes; out-of-boundary tasks bucketed with reason, not written | `exporter/sourceedit/MspdiSourceEditWriter.java` (from `MpxjMspdiExportArtifactService`; keep hash gate, identity gate, schema-order insertion, whole-doc verify; add assignment + timephased editing), `profiles/TransactionProfile.java` `{id, label BASELINE|DIAGNOSTIC|NATIVE_EVIDENCE_DERIVED, guard(), apply()}`, `profiles/AssignedTaskCompletionV1.java`, `profiles/LegacyThreeFieldProfile.java` (DIAGNOSTIC, disproved — kept so the register can say why), `BulkComposition.java` (reason buckets `SUMMARY, INACTIVE, MILESTONE, ALREADY_STARTED, NO_ASSIGNMENT, MULTI_ASSIGNMENT, MULTI_TIMEPHASED_ROW, PARTIAL_PROGRESS_NOT_PROVEN, ACTUALS_OUTSIDE_PLANNED_WINDOW, IDENTITY_MISMATCH, UNKNOWN_ELEMENT_ORDER`; sentinel-block byte identity outside touched blocks), `MspdiAssignmentElementOrder.java` (reflect `Project$Assignments$Assignment` propOrder). Extend `MspdiCandidateDifference` identity to `Assignment[UID]`, `TimephasedData[(Type,Start)]` and `approvedFieldsFor` to assignment paths. New contract `ProjectExportTransactionRequest{profileId, tasks[{taskUid, taskId, taskName, actualStart, actualFinish}]}` — client supplies only these; the profile derives Duration/Work/timephased from the **source** | JUnit on `boiler-before-no-progress.xml` → diff vs `boiler-roundtrip-candidate-task43.xml` empty outside `Name/GUID/LastSaved/CurrentDate`; two-assignment synthetic buckets `MULTI_ASSIGNMENT` | 5 |
| **I7** Returned-file delta classifier | `POST /worker/v2/classify-returned` (source, candidate, returned) → every difference `serialization_normalization | project_calculated_consequence | unexpected_difference` with path reasons | `proof/ReturnedDeltaClassifier.java` (reuse the difference walker with a classifier callback; `BigDecimal.compareTo` collapsing `-0.00`), `proof/MspdiConsequenceRules.java` (from the field contract: slack/late/critical on any task; rollup set on **ancestors** of touched tasks; resource rollup on assigned resources; `Name/GUID/LastSaved/CurrentDate/SaveVersion/BuildNumber` = normalization; timephased collapse on untouched multi-assignment tasks = normalization **only if** the I13 control run showed it), `PmxmlConsequenceRules.java` (stub until P6 evidence); Python `sto/interchange/export/returned.py` — anything `unexpected` blocks adoption | classifier on the BOILER proof pair reproduces the field-contract's legit-recalc set with zero unexpected | 3 |
| **I8** Export decision rule + unified export API | `export_schedule(schedule_id, target, change_set)` picks the path, runs the right proof, stores artifact + proof + label | `sto/interchange/export/strategy.py`: **SOURCE_EDIT** iff `change_set.kind == execution_facts` ∧ source ∈ {MSPDI, PMXML} ∧ source hash matches ∧ target == source format ∧ a profile exists; **REGENERATE** iff no source ∨ target ≠ source format ∨ change kind ∈ {logic, structure, dates, resourcing} (label from evidence register else DIAGNOSTIC); else **REFUSE** with reason (e.g. `.mpp` source + execution facts → offer REGENERATE explicitly as format conversion). UI never presents a REGENERATE artifact as "the same file with progress" | strategy unit tests over the decision table | 2 |
| **I9** Canonical work-order model + generic mapped-file adapter | `sto cmms import --profile <name>` on an IW37N/IW39 xlsx, Maximo WOTRACK csv or Oracle eAM operations export → validation report, dry-run preview, canonical WOs/operations under a revision; fail-closed rows | `sto/cmms/model.py` (below), `mapping/profile.py` (+ `profile.schema.json`), `mapping/transforms.py` (`strip, upper, zero_pad, split, regex_extract, lookup, concat, date(fmt,tz), duration(unit), bool(map), int`), `adapters/generic_mapped_file.py` (openpyxl/csv, header detection, sheet select), `validate.py` (row errors → `rejected_rows[]`, `fail_import_if_rejected_ratio_gt`), `preview.py`, `store.py` (profiles versioned, immutable once used); bundled `profiles/cmms/*.yaml` | three synthetic fixtures `fixtures/cmms/synthetic-{sap-iw37n.xlsx, maximo-wotrack.csv, oracle-eam-ops.csv}` with expected canonical JSON; one deliberately broken row each must be rejected with a coded reason | 6 |
| **I10** WO → schedule projection + CMMS ↔ P6/Project link resolver | CMMS import with no schedule → WBS (revision → functional location/system → WO) + one activity per operation (duration/work/crew from operation, codes for WO/op/work-centre/control-key/FLOC/equipment; relationships only where the CMMS carries them); with an existing schedule → operations linked via the site code/UDF convention, link health reported | `sto/cmms/projection.py`, `sto/cmms/link.py` (profile `schedule_link{work_order_field{mspdi_alias, p6_code, p6_udf}, operation_field{…}, normalise{…}}`; per operation `LINKED | AMBIGUOUS(n) | UNLINKED`; per activity `ORPHAN`) | BOILER: every leaf with `Text4`/`Text5` resolves against a synthetic SAP export built from those values; duplicate (WO, op) fixture yields `AMBIGUOUS` | 4 |
| **I11** Named adapters: SAP PM, Maximo, Oracle eAM/Fusion | `--system sap_pm` etc. work with default column names; `sto cmms export-actuals --system X` writes the confirmation file the site loads | `sto/cmms/adapters/{sap_pm, maximo, oracle_eam}.py` = bundled default profile + `ActualsWriter(batch) → file + manifest{sha256, rows, profile_version}` + validators. Formats in B.3; all writers `DIAGNOSTIC` until a site load is registered | fixture round trips per system | 6 |
| **I12** Re-import identity, scope delta, conflict rules | Second extract shows added/removed/changed operations, never deletes; same fact from two sources resolved by the authority table | `sto/cmms/identity.py` (key `(system, wo_number_norm, operation_number_norm[, sub_op])` → UUID in the shared identity registry, own namespace), `scope_delta.py` (`added`, `removed_in_source` → `scope_status=REMOVED_IN_SOURCE` + warning on linked activity, `changed`, `unchanged`), `sto/core/authority.py` | fixtures for each delta class and one divergence | 3 |
| **I13** Native evidence register, control runs, round-trip matrix | `docs/evidence/register.json` + `REGISTER.md` per `(target_format, application, build, profile_or_writer)`; `sto evidence control-run <file>` computes the untouched-source control delta; labels promote only by register entry | `sto/evidence/{register.py, control_run.py}`, `docs/evidence/TEMPLATE.md` (from ST-Claude `manual-microsoft-project-round-trip-evidence.md` + Shutdown-Tracker `NATIVE-EVIDENCE.md`); the profile registry test (P8) binds to it | matrix B.4 | 3 + manual sessions (~½ day each in Project / P6) |
| **I14** Live CMMS APIs (later) | Read WOs/operations, post confirmations | `sto/cmms/live/{sap_odata, maximo_oslc, oracle_fusion}.py` behind the same model. SAP `API_MAINTENANCEORDER` (`A_MaintenanceOrder/…Operation/…Component`), `API_MAINTORDERCONFIRMATION`; Maximo `/oslc/os/mxapiwo`, `mxapiwodetail`, `mxapilabtrans`; Fusion `/fscmRestApi/resources/latest/maintenanceWorkOrders` (+ operation/resource children), `resourceTransactions`. **All flagged assumption until checked against a tenant** | — | 4 per system, after credentials |

### B.2 Field-mapping traps (the rules `CanonicalProjectMapper`, `CanonicalToMpxjBuilder` and `ExpectedLossPolicy` encode)
| Concept | MS Project (MSPDI) | P6 (PMXML / XER) | Canonical + regenerate rule |
|---|---|---|---|
| Durations | ISO-8601 `PTnHnMnS` + `DurationFormat` (5 h, 7 d, 8 ed, 21 estimated) | decimal **hours** (`PlannedDuration`, `target_drtn_hr_cnt`) | `{value, unit, elapsed}` + `source_format_code`; never re-derive from display format |
| Lag | `LinkLag` **tenths of minutes** + `LagFormat`; applied on successor calendar (hypothesis) | hours; calendar per project option (`RelationshipLagCalendar` / `SCHEDOPTIONS`) | typed duration + schedule-level lag-calendar policy; warn P6→MS when option ≠ successor |
| Task/duration type | Fixed Units / Duration / Work + EffortDriven | Fixed Duration&Units, Fixed Duration&Units/Time, Fixed Units, Fixed Units/Time | MS→P6: FIXED_WORK→Fixed Units (warn); P6→MS: Fixed Units→FIXED_WORK, Fixed Units/Time→FIXED_UNITS |
| % complete | `PercentComplete` (duration), `PercentWorkComplete`, `PhysicalPercentComplete`; `EarnedValueMethod` picks physical | one `PercentCompleteType` governs | store all + `pct_type`; never author `PercentWorkComplete` outside the proven profile |
| WBS vs summary | summary tasks hold links, constraints, UDFs, rollups | WBS nodes hold none; `WBS_SUMMARY`/LOE/hammock activity types exist | `wbs_node` + `summary_task_attributes`; MS summary links → warn+drop or WBS-summary activity by profile; P6 LOE/hammock → flagged ordinary task |
| Constraints | one + `Deadline`; 8 types | primary + secondary; Mandatory Start/Finish, Start On, Finish On, ALAP | MS MSO→P6 Mandatory Start; P6 secondary → MS UDF text; `Deadline` → P6 UDF |
| Calendars | recurring exceptions, work weeks, project-wide `MinutesPerDay` | per-date exceptions, per-calendar hours/day; XER `clndr_data` blob | MS→P6 expand recurrences (window ± 1 y); P6→MS per-calendar hours lost → warn when mixed |
| Codes vs UDFs | ~90 custom-field slots, aliases, lookup tables, formulas, OutlineCodes | activity codes (hierarchical, scoped) + typed UDFs | P6→MS: codes → Text + alias + flat lookup, UDF overflow **fails closed**; MS→P6: aliased fields → UDFs, lookup fields → codes by profile switch; formula fields are context not identity |
| Assignments | `Units` is a rate; `WorkContour` canned | units are hours; `ResourceCurve`; roles exist | compute `units_per_time`; roles → resource `is_role=true` (MS L) |
| Timephased | per-assignment rows Type 1/2/3 (+7/9 cost/units → opaque) | none (curves/spreads) | MS→P6 dropped (expected loss); P6→MS `setGenerateMissingTimephasedData(true)`, DIAGNOSTIC |
| Baselines | 11 inline slots | baseline projects | slot 0 → `setWriteBaselines`; >0 warn |
| Manual scheduling | mode + manual dates | none | drop with warning |
| Identity/meta | `UID/ID/GUID`; `SaveVersion, BuildNumber, Name, LastSaved, CurrentDate` | `ObjectId/Id`; `ERMHDR` in XER (version, user) | external_uid/id/guid on every entity; meta = normalization set |
| Opaque | Leveling*, Sprint/Board, views/tables/filters | CURRTYPE, OBS, SCHEDOPTIONS, TASKFIN, RSRCCURVDATA, PCAT*, financial periods, EPS | survive only via source bytes / source-edit path; in every expected-loss list |
| Encoding / zone | UTF-8; wall-clock | XER **windows-1252**, tab-delimited; wall-clock | never convert time; charset exposed in detect/parse options |

### B.3 CMMS model, profile schema, adapters
**Model (`sto/cmms/model.py`):** `WorkOrder{system, wo_number, description, long_text, order_type, functional_location, equipment, priority, system_status[], user_status[], planned_start/finish, revision (SAP Revision = shutdown id), work_centre, planner_group, cost_centre, notification_number, operations[], components[], permits[], provenance{import_id, profile_id, profile_version, row_ref, sha256}}`; `Operation{operation_number, sub_operation, work_centre, plant, control_key, description, duration, work, number_of_persons, earliest/latest start/finish, actual_start/finish, system_status[], confirmations[], predecessors[]?, schedule_link{activity_id, status LINKED|AMBIGUOUS|UNLINKED, method code|udf|alias|manual}}`; `Component`, `PermitRef{kind ISOLATION|PERMIT|JSA}`, `Confirmation{actual_work, start, finish, final, remaining_work, personnel_number, text, source STO|CMMS}`.
**Profile schema (`profiles/cmms/*.yaml`, JSON Schema in `mapping/profile.schema.json`):** `profile_id, version, system; source{kind xlsx|csv, sheet, header_row, encoding, delimiter, skip_rows_matching[], date_format, time_format, decimal_separator, timezone}; entity operation|work_order|confirmation|component; hierarchy{rule one_row_per_operation|one_row_per_wo|wo_then_ops_indented, wo_key[], operation_key[]}; columns[{source, target (dotted canonical path), required, transforms[]}]; constants{}; lookups{}; validation{reject_row_if[missing_required, unparseable_date, duplicate_key], fail_import_if_rejected_ratio_gt, warn_if_unknown_columns}; schedule_link{work_order_field{mspdi_alias, p6_code, p6_udf}, operation_field{…}, normalise{work_order[], operation[]}}; projection{wbs[], activity_name, resource_from, relationships_from none|operation_sequence|explicit_columns}`. Unknown target path / missing required column / throwing transform → profile does not load. Rejected rows never partially applied.
**Named adapters (column labels are site-configurable — that is why they are profiles):**
- **SAP PM** — in: IW39 orders (`Order, Order Type, Description, Functional Loc., Equipment, Priority, System status, User status, Bsc start, Basic fin., Revision, Main WorkCtr, Planner group, Plant, Cost Center, Notification`), IW37N operations (`Order, Operation, Opr. short text, Work centre, Plant, Control key, Normal duration, Unit, Work, Unit, Number, Earliest start/finish date+time, Latest …, System status, Revision, Actual work, Actual start/finish`); relationships absent from list exports (`AFAB` needs a custom query) → default `none`. Out: no SAP-standard flat loader for PM confirmations → LSMW/IW41-recording-shaped xlsx (`Order, Operation, Sub-op, Work centre, Actual work, Unit, Actual start/finish date+time, Final confirmation, Remaining work, No remaining work, Confirmation text, Personnel no., Posting date`) + control sheet; **assumption: every site's template differs**; API path `BAPI_ALM_CONF_CREATE`.
- **IBM Maximo** — in: WOTRACK (`WONUM, DESCRIPTION, SITEID, ORGID, STATUS, WORKTYPE, ASSETNUM, LOCATION, WOPRIORITY, SCHEDSTART/FINISH, TARGSTARTDATE/TARGCOMPDATE, ESTDUR, ESTLABHRS, PARENT, WOCLASS, PMNUM, JPNUM, LEAD, SUPERVISOR, CREWID, WORKGROUP`), tasks (`WOCLASS=ACTIVITY`, `TASKID`, `WPLABOR` crafts; `PREDECESSORS` text "1234,1235FS+2h" parsed when present — syntax assumed), LABTRANS actuals. Out: MIF flat file (line 1 `EXTSYS,MXLABTRANSInterface,AddChange,EN`, line 2 headers, rows) — service names site-configured, **assumption**.
- **Oracle eAM (EBS) / Fusion Maintenance** — in: eAM WO list + operations/resources exports; Fusion via OTBI export of `maintenanceWorkOrders` (+ `WorkOrderOperation`, `WorkOrderOperationResource`) — field names **assumed** from REST docs. Out: eAM has no flat loader except WIP/MTL open interfaces (DBA) → site WebADI template; Fusion FBDI "Import Maintenance Work Order Resource Transactions"-style `.xlsm` — **verify against the FBDI library before building**.
**Authority table (`sto/core/authority.py`):** WO header / system status / components / permits → **CMMS**; planned dates / durations / logic / resourcing → **scheduler** (P6/Project, or STO when it is the scheduler); live progress/actuals → **STO execution layer** until exported and confirmed, then CMMS confirmation authoritative and STO's fact marked `EXPORTED_CONFIRMED`. Divergent values: both kept with provenance, `divergence` record raised, owner's value canonical, other shown as "reported by X". Never overwrite, never average.

### B.4 Round-trip matrix — green before a writer is `NATIVE_EVIDENCE_DERIVED`
| Check | MSPDI source-edit | MSPDI regen | PMXML regen | PMXML source-edit | XER regen | CMMS actuals |
|---|---|---|---|---|---|---|
| 1 Mechanical re-read proof (write → MPXJ read → canonical diff within expected-loss) | DOM diff instead | req | req | DOM diff | req | schema/column check |
| 2 Boundary proof (byte identity outside touched blocks) | req | — | — | req | — | — |
| 3 Untouched-source control run on this build | req | req | req | req | req | — |
| 4 Native open, recalc, save without error | req | req | req (P6 import, no ObjectId collision) | req | req | site load without rejection |
| 5 Returned classifier `unexpected == 0` | req | req | req | req | req | confirmation posted |
| 6 Approved inputs survived save | req | req | req | req | req | posted == exported |
| 7 Cross-format P6→MSPDI→P6 and MSPDI→PMXML→MSPDI within expected-loss | — | req | req | — | req | — |
| 8 Partial progress | **refused until evidenced** | same | same | same | same | allowed (CMMS semantics explicit) |
| 9 Multi-assignment / multi-timephased | refused until evidenced | — | — | — | — | — |
1–3 failing → generation fails (fail closed). 4–7 are register entries; until present the label is `DIAGNOSTIC` and the UI says so.

---

## D. Unified roadmap, dependencies, verification

### D.0 Sequencing rule
Engine (S), platform (P) and interchange (I) slices interleave. Each phase ends with something demonstrable that was impossible before; nothing in a later phase is started until the phase gate passes. Effort totals: engine ≈ 44 d, platform ≈ 49 d, interchange ≈ 53 d, minus overlaps (P3 ≈ I3+I4; S8 ≈ I6/I7 orchestration; S11 ⊂ I9–I11) ≈ **~130 dev-days ≈ 26 weeks** solo-with-agents to the full vision. First demonstrable increment: week 1. Live loop: ~week 8. Export with evidence: ~week 11.

### D.1 Phases
| Phase | Weeks | Slices | Gate (all must pass) |
|---|---|---|---|
| **0 · Monorepo + spine model** | 1–2 | **P1** persistent multi-project workspace; **S1** canonical model v1 + identity; governance: single `AGENTS.md`, `docs/adr/ADR-001…010` + `LEGACY-INDEX.md`, `docs/goals/ACTIVE.md`, frozen-repo banners; delete `workspace_web/` and the stale `~/Shutdown-Tracker` clone | Two MSPDI files import into two projects, survive restart with identical hashes; `from_dict(to_dict(x))==x` on BOILER; reconciliation original→day5 = 555 matched / 7 new; pytest, ruff, pyright green; drift guard green on a fresh DB |
| **1 · Engine + interchange spine** | 3–7 | **S2** calendars; **S3** forward pass 4 types; **S4** backward/float; **S5** progress/status date; **S6** rollup + eligibility + validator; **I1** sidecar full extraction; **I2** detect; **I3** client + JVM manager (= **P3**); **I4** import oracle → delete Python parser; **P2** real auth | 47 executable PM cases byte-identical, byte-identical across 3 processes; BOILER both snapshots: 460/460 leaves dispositioned, zero `UNEXPLAINED` on Start/Finish/Late/Slack/Critical; genuine-recalc oracle (`before` → `after-native-progress`) zero unexpected; cross-check report empty on all fixtures; `.mpp` imports; no route accepts the actor header |
| **2 · Live execution loop** | 8–11 | **S7** execution layer + incremental reschedule; **P4** live loop API + SSE + audit; **P5** field app offline; **P6** review chain as export governance; **P7** planner lease, scenarios, React console replaces legacy | `incremental == full` on 1k random DAGs; 200 posts on BOILER-shaped fixture p95 POST→SSE < 1 s; replay idempotent; update-log replay reproduces head hash; airplane-mode 3-task scenario recorded in `docs/evidence/field/`; approved_forecast moves only on planner approval; lease contention 409 |
| **3 · Export with evidence** | 12–15 | **I6** proven transaction in Java writer; **I7** returned classifier; **I5** regenerate MSPDI/PMXML/XER; **I8** strategy; **S8** Python export orchestration + classifier port; **P8** export lifecycle + profile registry bound to `docs/evidence/`; **I13** register + control runs | candidate diff vs `boiler-roundtrip-candidate-task43.xml` empty outside metadata; classifier on the proof pair zero unexpected; regenerate round trips within expected-loss for all three targets; a profile without a register entry cannot be selected; **one manual Project session** re-verifies the transaction on the current build and records the untouched-source control (register entries for build .20188/.20186 carried over with provenance) |
| **4 · CMMS** | 16–19 | **I9** WO model + mapped-file adapter; **I10** projection + link resolver; **P11** API seam; **I11** SAP / Maximo / Oracle adapters; **I12** identity, scope delta, authority | three synthetic CMMS fixtures import with coded rejections; BOILER `Text4/Text5` links resolve against a synthetic SAP export; second extract yields add/removed/changed without deletion; actuals files produced per system (DIAGNOSTIC) |
| **5 · Operations, scheduler depth, cut-over** | 20–26 | **P9** problems/actions/evidence/handover (blocked → suspended → reschedule); **P10** critical watch; **S9** CP-SAT levelling; **S10** operational constraints; **P12** cut-over | parity checklist (C.3 P12) recorded in `docs/evidence/cutover-<date>.md`; SEM-DET-049/050 pass; Gate-1 sample 48h→38h; verifier zero violations on BOILER with 32 resources; ports swapped in one redeploy; frozen repos archived |
| **Later** | — | **I14** live CMMS APIs; XER source-edit; PMXML source-edit; OIDC; multi-calendar levelling; partial-progress transaction (needs one native 50 % reference first) | each gated by its own register entry |

### D.2 Hard external dependencies (not code)
1. **A real P6 file (XER or PMXML) and a P6 session.** None exists in the estate. Until one arrives, every P6 writer stays `DIAGNOSTIC`, the XER reader has no file oracle, and P6 lag-calendar semantics remain a hypothesis. Ask for one now; it gates Phase 3's P6 column and Phase 1's XER oracle.
2. **A real CMMS extract** (any of SAP IW37N/IW39, Maximo WOTRACK, Oracle eAM) — even anonymised. Gates Phase 4 beyond synthetic fixtures.
3. **The Windows box with Microsoft Project** — exists (three round trips ran on it in August). One session per Phase-3 register entry; one more when the add-in spike is run (side experiment; Office.js has no assignment/timephased API so it cannot replace the MSPDI path).
4. **Site confirmation-upload templates** for whichever CMMS is first — every vendor's flat-file path is site-specific.

### D.3 Verification (how "done" is demonstrated end to end)
- **Engine conformance job (CI):** `benchmarks/semantic/` 50 PM cases via `sto.conformance.semantic_suite`; 49 pass + 1 native-required; three fresh-process runs byte-identical.
- **File oracle (CI on fixtures, local on BOILER):** `sto compare <file>` → `DifferenceReport` with zero `UNEXPLAINED` across Start/Finish/LateStart/LateFinish/TotalSlack/FreeSlack/Critical; both BOILER snapshots; the `before→after-native-progress` recalculation pair.
- **Import cross-check (CI):** Python-parser-vs-MPXJ canonical diff empty on every fixture until the parser is deleted; thereafter MPXJ re-read of every regenerated artifact within expected-loss.
- **Live loop (integration, real Postgres):** idempotent replay; p95 < 1 s POST→SSE on 555-task fixture; incremental-equals-full property test; update-log replay reproduces head hash; Playwright offline script.
- **Export (unit + manual register):** candidate diff vs committed Project-saved fixture; classifier zero unexpected; profile registry ↔ `docs/evidence/register.json` binding test; manual native session per target/build with untouched-source control.
- **Security:** test that no route accepts `X-Shutdown-Tracker-Actor-Id`; capability parity `Capability` enum ↔ generated `identity.ts` ↔ DB CHECK lists.
- **Governance (CI):** PR touching `src/` must touch `docs/goals/ACTIVE.md` or carry `no-goal-change`; profile without register entry fails the registry test; `redeploy.sh` prints native-evidence-derived profile count.
- **Cut-over:** the 14-item parity checklist in C.3/P12, driven through the UI, recorded in `docs/evidence/`.

### D.4 What this plan deliberately does not do
- Does not port ST-Claude's 240 Java API files — the domain is ported, the Java is retired.
- Does not chase P6/Project feature parity — the engine's boundary is the conformance suite plus fail-closed `Assumption`/`Exclusion` codes; anything outside is labelled, not guessed.
- Does not keep two MSPDI parsers — the Python one is an oracle with a deletion criterion.
- Does not treat the Office.js add-in as the `.mpp` fix.
- Does not migrate the old deployment's data (synthetic by the deploy README's own rule).
- Does not run a fourth reset — ST-Claude stays deployed and untouched until the parity gate.

---

# E. Session continuity — closing the handoff gaps

## Context

Asked on 2026-09-02 whether everything from the session that produced this plan is saved well
enough to continue in a different chat. Verified state:

**Already durable.** Five commits pushed to `origin/feat/canonical-model-v1` with a clean working
tree and PR #22 open. This plan file (69 KB, sections A–D). Three memory files
(`sto-consolidation-direction`, `sto-market-gap-scan`, `shutdown-tracker-estate-review-artifact`)
plus the `MEMORY.md` index. Two published artifacts, their URLs in memory. In-repo governance:
`AGENTS.md`, `ADR-001..003` + `LEGACY-INDEX.md`, `docs/goals/ACTIVE.md`, `docs/evidence/README.md`.

**Three gaps.** Each would misdirect or block a fresh session; none is large.

## E1 — Stale memory actively contradicts the approved direction (highest priority)

`shutdown-tracker-fresh-repo.md` (written 2026-08-25) still says Shutdown Tracker is "developed as
**two live repositories**, deliberately" and closes with *"**How to apply:** work in
`/home/dez/Shutdown-Tracker-Claude`"*. That is now wrong: ADR-001 makes
`STO-Scheduler-Tracker-Research` the monorepo and freezes the other two. A future session recalling
that memory would open the wrong repository and re-learn the estate from a superseded map.

The file's own history shows why this matters — it records that an earlier version wrongly called
the original repo dormant and "caused a confident wrong conclusion".

**Fix:** rewrite it as a *superseded* pointer: keep the durable facts that survive (the two repos
share no commit ancestry so nothing can ever be git-merged between them; the local
`Shutdown-Tracker` clone is stale and should be read through `gh api`), state plainly that both are
now frozen references, and redirect to `[[sto-consolidation-direction]]`. Update its `MEMORY.md`
line, which currently reads "two live repos in a deliberate split; the original is NOT dormant".

## E2 — Test fixture provenance is undocumented

`tests/test_canonical_model.py:34-35` defaults to `/home/dez/sto-fixtures/boiler-before-no-progress.xml`
and `/home/dez/BOILER-WG110-day5-candidate.mspdi.xml`. `ACTIVE.md` names the two environment
variables but not **where the files came from**, so if they are lost the six BOILER cases silently
skip and nobody knows how to restore them.

They are recoverable, and the recipe is the thing to record:

```bash
# the four proof fixtures, from the frozen repo's origin/main
cd /home/dez/Shutdown-Tracker-Claude
for f in boiler-before-no-progress boiler-after-native-progress \
         boiler-roundtrip-candidate-task43 boiler-roundtrip-project-saved-task43; do
  git show origin/main:fixtures/project-files/boiler/$f.xml > /home/dez/sto-fixtures/$f.xml
done
```

The day-5 candidate (`BOILER-WG110-day5-candidate.mspdi.xml`, 562 tasks, `StatusDate
2025-05-09T17:00`, 8 progressed tasks, 40 calendar exceptions) is **not in any repository** — it
sits loose in `/home/dez` and exists nowhere else. It is the only progress oracle for engine slice
S5.

**Fix:** a `fixtures/README.md` in the monorepo giving the recovery recipe, the expected SHA-256 of
each file, what each one proves, and a warning that the day-5 candidate has no upstream. Reference
it from `ACTIVE.md`'s validation block. Keep the files themselves out of git.

## E3 — The detailed design is reachable only through memory

`~/.claude/plans/hazy-wandering-lantern.md` is not referenced from the repository. `ACTIVE.md`
carries a condensed roadmap, but the field-mapping tables, CMMS mapping-profile schema, round-trip
matrix, slice sequence and phase gates live only here. A session started inside the repo would not
find them.

**Fix:** copy this plan into the repo as `docs/roadmap/CONSOLIDATION-PLAN.md` (it is design
documentation, not a scratch file) and link it from `ACTIVE.md` and `README.md`. The memory file
already names the `~/.claude/plans` path; add the in-repo path beside it.

## E4 — Housekeeping

Delete `/home/dez/Shutdown-Tracker` — a pre-reset clone, 14 commits behind `origin/main`, whose
content predates the 2026-08-27 reset. Section C already calls for this; it has not been done, and
leaving it invites reading the wrong tree from disk. Confirm before deleting.

The session task list is not persisted, which is correct: `ACTIVE.md` is the durable equivalent and
already carries the next three items.

## Verification

```bash
# E1: no memory still points at ST-Claude as the place to work
grep -rn "work in .*Shutdown-Tracker-Claude" ~/.claude/projects/-home-dez/memory/   # expect none

# E2: fixtures documented and recoverable
cat /home/dez/STO-Scheduler-Tracker-Research/fixtures/README.md
sha256sum /home/dez/sto-fixtures/*.xml /home/dez/BOILER-WG110-day5-candidate.mspdi.xml

# E3: plan reachable from the repo
ls /home/dez/STO-Scheduler-Tracker-Research/docs/roadmap/CONSOLIDATION-PLAN.md
grep -n "CONSOLIDATION-PLAN" /home/dez/STO-Scheduler-Tracker-Research/docs/goals/ACTIVE.md

# the six BOILER cases still run, and the suite is still green
cd /home/dez/STO-Scheduler-Tracker-Research
PYTHONPATH=src python3 -m unittest discover -s tests    # expect 115 tests, OK
```

A fresh session is then continued by: reading `MEMORY.md` → `sto-consolidation-direction` → opening
`/home/dez/STO-Scheduler-Tracker-Research` → `AGENTS.md`, `docs/goals/ACTIVE.md`, and
`docs/roadmap/CONSOLIDATION-PLAN.md`.
