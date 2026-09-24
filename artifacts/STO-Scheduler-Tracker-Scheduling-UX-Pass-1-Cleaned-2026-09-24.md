# STO Scheduler + Tracker
## Professional Scheduling UX/UI and Live Shutdown Execution Research
### Deep Research Pass 1 - Cleaned and Reviewed Edition
**24 September 2026**

> **Revision note.** This edition cleans and corrects the original Pass 1 report after review. It does not add a new broad research pass. It preserves the original evidence base while making current STO authority, inherited Design C evidence, external documented patterns, recommendations and practitioner-test hypotheses explicit.

**Overall judgement:** Pass 1 establishes a sufficiently supported direction to begin STO UX Architecture v1 and low-fidelity prototyping. It does not establish a finished scheduler UI.

# 1. Executive conclusion

**CURRENT STO FACT.** STO is now the product monorepo and describes itself as a shutdown, turnaround and outage scheduler that will import from CMMS, Primavera P6 or Microsoft Project, track/manage/schedule execution in real time, and export back. Today it imports Microsoft Project XML into a canonical model, persists and calculates an immutable baseline, and supports one persisted duration scenario that demonstrates downstream movement behind authenticated project access. [I1][I2]

**INHERITED DESIGN EVIDENCE.** The earlier Shutdown Tracker UX was designed for a different authority boundary: Microsoft Project remained the scheduler while Shutdown Tracker concentrated on execution, review, evidence and export. Its UX ADR therefore excluded schedule editing and dependency planning from the baseline UX. [I4][I5]

**RECOMMENDATION.** STO should evolve that inherited work rather than replace it. The product should remain one activity-centred operational system with two deliberately different surfaces: a professional desktop scheduling/control-room application and a sparse offline-first field application. Planning and execution should share STO activity identity, authoritative state and audit lineage, while presenting role-appropriate workflows.

**RECOMMENDATION TO PROTOTYPE.** A synchronized WBS/activity table plus Gantt plus progressively disclosed activity inspector is the leading desktop architecture to validate. Professional scheduling products repeatedly document combinations of dense activity tables, temporal bars, relationship views, filters, grouping and detail panes. That recurrence supports a prototype direction; vendor documentation does not prove that the pattern is objectively the most usable design. [E1][E2][E5]

The strongest product opportunity is to connect schedule mechanics to live execution without hiding authority. A field execution command may change the live forecast after server validation and application; communication cannot. Supervisor and planner review govern movement of the approved forecast. [I2][I3]

A second opportunity is explainability: the planner should be able to ask **"Why did this move?"** This must be a provenance-backed scheduler explanation, not an inference from coincident date changes. Current STO can identify changed activities and expose some calculation/placement metadata in its P1 planner, but a production explanation requires sufficient causal provenance to identify authoritative changed inputs, driving relationships, calendar/constraint decisions and downstream effects. [I8]

No further broad scheduling-UX research is required before architecture and prototyping. The next step is:

**STO UX Architecture v1 -> low-fidelity scheduler/execution prototypes -> practitioner validation -> corrections -> P2 implementation.**

# 2. Evidence model and source hierarchy

This cleaned report uses five evidence labels:

- **CURRENT STO FACT** - current repository, roadmap, accepted ADRs, implemented P1 behaviour and gate contracts. Highest authority for current product direction.
- **INHERITED/FROZEN DESIGN EVIDENCE** - Design C and frozen Shutdown Tracker material. Strong evidence for operational UX principles, but not current authority where the product boundary changed.
- **EXTERNAL DOCUMENTED PATTERN** - current vendor documentation or authoritative platform/human-factors guidance. Establishes documented capability or constraints, not user preference or usability success.
- **RECOMMENDATION** - synthesis for STO based on the evidence.
- **TEST / UNVALIDATED HYPOTHESIS** - a design choice that must be demonstrated with practitioners or representative workloads before it is hardened.

Current STO authority outranks frozen documents where they conflict. The roadmap treats the consolidation plan as a frozen design record and keeps P2 as the live execution loop, P3 as export/interchange evidence, P4 as CMMS integration and P6 as later scheduler depth. [I2]

# 3. Design C inheritance: Keep / Adapt / Retire / Test

## KEEP

- Separate Master Console and Field App.
- Mobile is not a responsive collapse of the professional desktop scheduler.
- Attention-first Today surface: what changed, what is blocked, what is late, what needs review, who owns it, and what is not synchronized.
- Flat, restrained industrial visual language; limited decorative cards, shadows, radii and marketing-style presentation.
- Semantic state rather than colour names; text/icon/shape plus colour rather than colour-only meaning.
- Structured Problems, Actions and Evidence rather than burying operational facts in comments.
- Explicit offline/queued/server states and preservation of failed local work.
- Dense tables/lists where comparison matters; sparse field cards where rapid action matters.
- Communication remains contextual rather than becoming a generic top-level chat product.

## ADAPT

- The old Tasks zone should no longer be expected to carry professional scheduling. A distinct scheduling capability is required. The exact replacement label for operational work is **TEST**; "Execution" is the current leading candidate.
- The old Exports concept must eventually broaden to Project/P6/CMMS import, reconciliation, mapping and export evidence. The exact label "Interchange" is **TEST** and need not appear as an empty P2 top-level zone.
- Planner review moves from an export-centric model toward governed live-versus-approved forecast review, while P3 artifact review remains an integration concern.
- Project-boundary warnings become source/provenance/authority warnings. Project is no longer STO's scheduling authority.

## RETIRE

- The frozen five-zone desktop navigation freeze where it prevents first-class scheduling.
- The blanket prohibition on Gantt/scheduler views.
- The blanket prohibition on CPM/float/critical-path visualization. These are now scheduler concepts, although they still require restrained presentation.
- Microsoft Project as the scheduling authority.

## TEST

- Exact desktop label "Execution" versus alternatives such as Work or Live Execution.
- Exact future label "Interchange" and when it becomes visible.
- Exact Live/Approved/Scenario visual treatment.
- Materiality thresholds for schedule-derived attention.
- Exact inspector tab labels/order and default pane sizes.

The conclusion is not that Design C is obsolete. Its operational discipline remains the foundation. Only the assumptions that flowed from the old Project-owned scheduling boundary are retired. [I4][I5]

# 4. Professional scheduler interaction patterns

**EXTERNAL DOCUMENTED PATTERN.** Oracle P6 documents an Activities workspace in which an activity table can be supplemented by a Gantt and detailed information for the selected activity. Relationship lines, data-date display and configurable views are documented. [E1][E2]

**EXTERNAL DOCUMENTED PATTERN.** Microsoft Project documents Gantt-based task editing, relationship creation, Task Path highlighting for predecessors/driving predecessors/successors, critical-path and slack views. These patterns demonstrate useful local logic inspection without requiring every relationship to remain visible. [E3][E4]

**EXTERNAL DOCUMENTED PATTERN.** Safran Project's Barchart Editor combines activity columns with a Gantt/bar area, synchronized information panes, logic/resource views, saved layouts and immediate schedule feedback from timing/logic edits. [E5]

**EXTERNAL DOCUMENTED PATTERN.** InEight Progress documents mobile planning/execution workflows and explicit offline/sync state. This supports role/state clarity but does not define STO's CPM scheduler model. [E6]

**RECOMMENDATION.** STO should borrow interaction primitives, not copy an application's chrome or complexity. The candidate pattern is synchronized activity grid + Gantt + selected-activity detail, supported by search, grouping, filters, saved views, keyboard operation and explicit schedule-state context.

Dependency lines should be selection-local or driving-path oriented by default. Always-on network "spaghetti" should not be the primary analysis mode. Microsoft Project Task Path and P6 relationship views provide documented examples of localizing logic inspection. [E2][E3]

Direct manipulation may be offered as convenience, but semantic schedule actions must remain explicit and have keyboard/form alternatives. WCAG 2.2 requires a simple pointer alternative for functionality that uses dragging unless dragging is essential. [E10]

# 5. Planner jobs-to-be-done

The following priorities are recommendations inferred from the STO roadmap, PM-Software trial material and documented scheduler patterns. They are not measured industry frequency and must be validated with shutdown planners.

## Continuous during execution

- Locate an activity, WBS or workfront quickly.
- See actual history, remaining work, live forecast and approved position without confusing them.
- Find blocked, late, newly critical, materially moved, stale or review-required work.
- Determine why an activity or milestone moved.
- Inspect predecessor/successor logic, driving logic and float.

## Frequent

- Review execution reports and understand their live forecast effect.
- Evaluate recovery alternatives in isolated scenarios.
- Compare a scenario with an explicit reference version.
- Review forecast changes under the governed P2 process.

## Planning and maintenance

- Edit supported durations, relationships, calendars and constraints.
- Perform multi-select and bulk operations with preview/validation.
- Import/build WBS and logic through professional table workflows.

## Guarded / high consequence

- Correct accepted history.
- Change a calendar or constraint with broad schedule impact.
- Submit/promote a scenario outcome.
- Advance approved forecast or approve an external interchange artifact.

High-frequency editing and high-consequence editing should not have identical friction.

# 6. Proposed STO information architecture

**RECOMMENDATION.** Preserve Design C's operational zones while introducing first-class scheduling. Labels marked TEST remain provisional.

```
STO MASTER CONSOLE

Today
Schedule
Operational work [TEST label: Execution]
Problems
Evidence
External systems [future concept; TEST label: Interchange]

STO FIELD APP

My Work
Today
Problems
Evidence
Sync
```

Schedule should be treated as a first-class desktop capability before P2 frontend structure hardens. This does not require every scheduling feature to be built in P2.

Today remains an attention surface, not a management dashboard. It should prioritize decisions and exceptions: material forecast movement, blocked controlling work, newly critical work, stale execution information, review queues, rejected field updates and sync/data-quality failures. Exact thresholds are TEST.

The future external-systems concept should reserve a coherent home for Project/P6/CMMS import, reconciliation and export evidence, but P2 should not expose an empty Interchange zone merely to reserve navigation.

Communication remains contextual to activities/workfronts/entities and may appear in a timeline. It should not become a generic top-level Chat area.

# 7. Candidate scheduler workspace

**RECOMMENDATION TO PROTOTYPE.** The main professional scheduling surface should be a synchronized table/Gantt workspace with persistent schedule-state context and progressive detail.

```
Project / status point / viewed state / scenario / freshness
------------------------------------------------------------
Today | Schedule | Operational work | Problems | Evidence
------------------------------------------------------------
Search | View | Group | Filter | Compare | Scenario | Recalculate
------------------------------------------------------------
WBS / ACTIVITY TABLE        | GANTT
ID  Name  Dur  Start  Float | baseline / actual / live / scenario
                            |
[same row model and selection across both panes]
------------------------------------------------------------
SELECTED ACTIVITY INSPECTOR
Summary | Plan | Logic | Execution | Context | History  [TEST labels]

Movement / impact explanation when provenance supports it
```

The table and Gantt should share one row identity and selection model. Recalculation should preserve selected activity, filters, relevant scroll position and timescale wherever possible.

Default grid density should remain professional rather than card-based. Progressive disclosure prevents the default grid from becoming a fifty-column dump.

Keyboard navigation, multi-selection and bulk operations are candidate architectural requirements, but exact shortcuts and bulk-edit semantics require prototype testing.

# 8. Activity detail architecture

The central architectural decision is one STO activity identity viewed through planning and execution lenses. Exact tab names and order are TEST.

- **Summary** - identity, WBS/workfront, live timing, approved timing, movement, current execution state and immediate attention.
- **Plan** - duration, calendar, constraints, early/late dates, total/free float and supported planning assumptions.
- **Logic** - predecessors, successors, relationship type/lag, driving relationship/path and selected-path highlighting.
- **Execution** - actual start/finish, status point, remaining duration, submitted operations, acceptance/application state, review state and live forecast effect.
- **Context** - Problems/Actions, Evidence/photos, communication and later work-order/equipment context.
- **History** - source/import provenance, baseline, accepted authoritative changes, corrections, scenario/promotion history and audit.

Opening an activity from Schedule can emphasize Summary/Plan; opening the same activity from operational work can emphasize Execution. These are lenses over one record, not separate task databases.

# 9. Schedule-state and execution-time model

**CURRENT STO FACT.** P1 already distinguishes imported/source observations, an immutable calculated baseline and a persisted scenario. P2 adds live execution semantics and requires that approved forecast move only on planner approval after supervisor then planner review. [I1][I2]

**RECOMMENDATION.** Do not present Source, Baseline, Live, Approved, Scenario and History as equal peer tabs. They belong to different dimensions.

```
REFERENCE
  Source/imported observations
  Immutable STO baseline

OPERATIONAL
  Approved forecast
  Live forecast
    may include authoritative execution effects
    not yet incorporated into Approved

WORKING
  Scenario / planner draft
    explicitly based on a version
    isolated until governed promotion

HISTORY
  Immutable prior versions and audit
```

The execution-time model is separate:

```
ACTUAL HISTORY | STATUS POINT | REMAINING FORECAST
===============|==============|====================
```

The global context should make the viewed state explicit: what is being viewed, what version it is based on, the data/status point, current approved version, whether unreviewed effects exist, and whether edits can affect live execution.

When viewing a scenario, the UI should explicitly state that it is not live and not approved, identify its base version, last calculation and edited inputs. Exact visual treatment remains TEST.

# 10. Trustworthy movement and impact explanation

**DESIGN OBJECTIVE.** "Why did this move?" should be a first-class STO interaction because it connects scheduler mechanics to operational decisions. PM-Software's practitioner trial explicitly asks whether planners understand important reasons work moved. [I7]

**CORRECTION.** The UI must not infer a cause from coincident date changes. A trustworthy explanation requires scheduler provenance/causal data. Current STO can identify changed activities and expose some calculation/placement metadata, but that is not yet equivalent to a complete causal chain. [I8]

The scheduler should eventually make sufficient evidence available to express:

```
Version v31 -> v32

AUTHORITATIVE CHANGE
A-101 Remaining Duration: 2h -> 3h
Execution operation: E-4821

SCHEDULING CONSEQUENCE
A-101 Finish: +1h

PLACEMENT OF A-102
Driving edge: A-101 -> A-102
Relationship: FS + 0h
Calendar/constraint decision: DAY / none
Result: A-102 Start +1h

DOWNSTREAM IMPACT
A-117 Start +1h
Milestone M-12 Finish +1h
Total float: 1h -> 0h

OTHER SIMULTANEOUS DRIVERS
None / multiple / unresolved
```

The explanation hierarchy should be:

**What moved -> direct driver(s) -> changed authoritative input/event -> scheduling rule/placement -> downstream consequence.**

Potential cause types include predecessor timing, relationship/lag, actual start/finish, remaining duration, calendar, constraint, planner/scenario edit and, later, resource or operational constraints.

Where multiple causes are possible, the UI must show that ambiguity rather than invent a single cause. A production explainability contract therefore depends on scheduler provenance becoming sufficiently explicit.

# 11. Criticality, float and attention semantics

STO should keep the following facts visibly separate:

- Calculated CPM criticality.
- Total float.
- Free float.
- Near-critical threshold/view policy.
- Driving logic / causal path.
- Human Critical/watch operational classification.
- Future resource-constrained executable risk.
- Future operational-constraint risk.

Near-critical is a configured view/filter policy, not a scheduler truth equivalent to total or free float.

Microsoft Project itself documents configurable critical/slack concepts, which reinforces the need for STO to state the basis rather than rely on a generic red bar. [E4]

Human Critical placement and calculated criticality must remain separate. A planner or control-room operator may deliberately watch work that the current CPM calculation does not classify as critical.

# 12. Scenario and recovery UX

**CURRENT STO FACT.** P1 has one persisted duration scenario. P2 PL7 plans planner editing, leases and immutable scenarios with governed promotion. [I1][I2]

**RECOMMENDATION.**

```
Explicit reference version
        |
Create scenario / planner draft
        |
Edit supported inputs
        |
Recalculate
        |
Impact summary + changed-only comparison
        |
Investigate movement and adverse effects
        |
   +----+------------------+
   |                       |
Discard              Submit proposed
                     scenario outcome
                           |
                 Governed promotion process
                           |
              Exact P2 semantics still to define
```

A scenario should always identify its base version and must never silently mutate live or approved state.

Useful comparison patterns to prototype include overlay comparison, changed-only table, impact summary and explicit provenance. Exact promotion/approval interaction remains TEST until PL7/PL6 semantics are designed together.

# 13. Core workflows and authority

## 13.1 Planner edit and recalculation

Schedule -> find/select activity -> edit supported Plan/Logic input -> draft visibly dirty -> validate -> recalculate -> changed-only impact -> inspect movement/provenance -> keep in scenario / undo / discard / submit proposal.

Invalid edits should preserve user input and explain the correction required. Essential operations need keyboard/form paths; drag may be an optional convenience.

## 13.2 Field execution command to live schedule

ADR-016 distinguishes queueing, server acceptance and application. The UI must preserve that distinction. [I3]

```
Field execution command
  -> queued locally
  -> server authenticates and validates
  -> ACCEPTED
  -> authoritative execution effect applied
  -> S7 deterministic recalculation
  -> APPLIED
  -> live schedule updated
```

An accepted receipt must not falsely imply that recalculation or downstream application has finished.

## 13.3 Live forecast to approved forecast

```
Authoritative execution effect
  -> live forecast changes
  -> supervisor review
  -> planner forecast review
  -> approved forecast advances
```

The exact review interaction is P2 design work, but the authority boundary is already explicit in the roadmap. [I2]

## 13.4 Movement investigation

Today/Schedule attention -> open affected milestone/activity -> focus selected activity -> inspect provenance-backed "Why did this move?" -> highlight supported driving chain -> open causal event -> inspect actual/remaining/logic/calendar -> create recovery scenario if required.

## 13.5 Supervisor review

The supervisor should see the submitted execution operation, prior authoritative state, relevant evidence/context and live schedule consequence. Communication acknowledgements or reactions must never perform review implicitly. [I3]

## 13.6 Field communication and photos

My Work -> activity -> contextual timeline -> text or photo/markup -> local queued state if offline -> server acceptance/delivery -> visible to permitted users. **No schedule mutation.**

A separate "Mark complete" or progress action opens an explicit ExecutionCommand path. Message text is never interpreted as scheduling authority. [I3]

## 13.7 Offline reconnect and rejection

Offline capture -> durable local outbox -> process termination/reopen -> queued work remains visible -> reconnect/current permission check -> idempotent submission -> accepted/applied OR rejected.

Rejected/stale/conflicting work becomes **Needs attention** and must show what the user entered, current server state, why it cannot apply, and allowed resolution. Android offline-first guidance and InEight mobile sync states provide external patterns, but STO's authority/idempotency contract comes from ADR-016. [E6][E11][I3]

# 14. Desktop versus mobile responsibility

## Desktop / Master Console

- Full WBS/activity table and professional Gantt.
- Logic and float investigation.
- Planner editing and scenarios.
- Changed-only and comparison views.
- Planner forecast review/approval.
- Supervisor/control-room review where authorised.
- Import/reconciliation/export in later phases.
- Future CMMS/P6 mapping/configuration.

## Field App

- Assigned work / My Work.
- Start, progress, remaining duration and finish through supported execution commands.
- Problems/actions where in scope.
- Evidence/photo capture.
- Contextual communication.
- Durable offline submission.
- Sync diagnostics/recovery understandable to field users.
- Summary schedule context only where useful; no professional scheduler.

This preserves Design C's strongest premise: the field app is a different application surface with different jobs and density.

# 15. Design-system implications

Design C's restrained operational language should be retained. Scheduling adds semantic tokens named by meaning rather than colour, for example:

`schedule.reference.source`, `schedule.reference.baseline`, `schedule.history.actual`, `schedule.forecast.live`, `schedule.forecast.approved`, `schedule.forecast.unreviewed`, `schedule.working.scenario`, `schedule.working.edited`, `schedule.logic.driving`, `schedule.logic.related`, `schedule.risk.critical`, `schedule.risk.nearCritical`.

Exact colours, fills and patterns remain TEST.

Gantt semantics should use combinations of position, fill/outline/pattern, labels and persistent state context rather than colour alone. Actual history and future forecast should be separated by an explicit status point.

WCAG 2.2 requires alternatives to drag-only interaction and defines minimum target-size rules. STO's field UX should go beyond minimum web compliance where real device/PPE/time-pressure conditions justify it. [E10]

High-contrast/night use should be prototyped rather than assumed. HSE control-room guidance emphasizes task analysis, readable displays, logical grouping and clear feedback. [E8]

# 16. Large-schedule UX

Candidate architectural requirements:

- Virtualized activity and Gantt rows.
- One shared vertical row/selection model.
- Pinned identity/name/state columns.
- Collapsible WBS.
- Search-to-activity rather than manual scrolling.
- Saved views and filters.
- Changed-only, critical/near-critical, needs-review, shift/lookahead and workfront views.
- Selection-local/driving-path dependency display rather than global lines by default.
- Preserve selection, filters, relevant scroll position and zoom after recalculation.
- Multi-select and keyboard operations.
- Asynchronous detail loading where appropriate.

**TEST COHORTS, NOT PRODUCT LIMITS:** 500, 2,000 and 5,000+ activity fixtures may be used as representative performance/usability cohorts. They are not supported limits, SLAs or latency promises. Actual interaction budgets should come from profiling representative real schedules.

# 17. Human factors and attention design

HSE control-room guidance says HMI design should be based on task analysis, displays should be logically grouped, and operators should receive clear feedback about actions and delays. HSE alarm guidance emphasizes useful, relevant alarms tied to timely operator action rather than flooding. [E8][E9]

Applied to STO, this supports an attention-by-action model rather than treating every schedule movement as an alert.

Candidate Today categories are Decision required, Schedule risk, Execution risk, Review queues and Data/sync exceptions. Exact materiality thresholds are TEST.

# 18. Future readiness without premature design

## P3 - Project/P6 interchange

Reserve a coherent external-systems area and activity provenance seam for import, identity reconciliation, candidate export, difference review and returned-file evidence. Do not design the full P3 writer/reconciliation UI before semantics and evidence profiles exist. [I2]

## P4 - CMMS/EAM

Allow the activity Context area to later expose STO identity, source schedule identity, work order, operation, equipment, CMMS provenance and mapping status. Do not design vendor adapter configuration in P2. [I2]

## P6 - scheduler depth

The Schedule workspace should be extensible to later Resources and operational Constraints without introducing a second "advanced scheduler". Resource levelling, crew capacity, permits, isolations, workface occupancy and optimisation explanation remain deferred until P6 semantics are real. [I2]

# 19. Proposed practitioner validation

This report recommends adapting PM-Software's practitioner method for STO. It is a **PROPOSED STO VALIDATION METHOD**, not yet a formally adopted STO gate.

PM-Software currently requires at least three independent experienced planners, with five preferable, and classifies findings A/B/C. Its exit gate requires practitioners to distinguish accepted actual history, status point, remaining work, future recovery and approved plan, and to understand material movement. [I6][I7]

## Planner trial

Participants should complete outcomes rather than follow click-by-click instructions:

1. Identify whether they are viewing Baseline, Live, Approved or Scenario and explain what edits can affect.
2. Distinguish accepted actual history, status point, remaining work and future forecast.
3. Investigate a moved milestone/activity and identify supported driving causes.
4. Inspect driving predecessor/relationship without displaying the entire network.
5. Create an isolated scenario, change a supported planning input and recalculate.
6. Compare scenario consequences against Approved.
7. Explain that scenario submission/promotion is not automatic forecast approval.
8. Resolve a stale edit or rejected update without losing intended information.
9. Distinguish calculated criticality, float, near-critical policy and human Critical/watch status.
10. Complete a representative keyboard-heavy sequence without repeatedly leaving the main workspace.

Measure task completion, wrong-layer edits, state-identification errors, unsupported causal assumptions, ability to explain movement, whether participants invent unavailable information, error recovery, interaction effort, terminology confusion and trust sufficient to investigate/use results.

## Supervisor, coordinator and field trials

Supervisor: distinguish submitted execution operations from communication, inspect evidence and live consequence, request correction, and understand whether the action advances Approved.

Shutdown coordinator: work through a mixed Today queue containing a blocked controlling activity, routine non-material delay, failed offline submission, newly critical path and planner decision. Observe whether highest-consequence work is found first without notification flooding.

Field: use the P2 two-device offline trial and add UX observations for whether users understand Queued, Accepted, Applied, Failed and Conflict.

## Finding classes

- **A - Fundamental/product blocker:** authority/state is misunderstood, actual/future is confused, causal explanation is untrustworthy, or the UI encourages dangerous wrong-layer edits.
- **B - Important usability issue:** semantics appear sound but normal practitioners materially struggle.
- **C - Later improvement:** convenience, terminology, presentation or polish issue that does not prevent safe comprehension.

# 20. Pre-P2 decisions

## MUST DECIDE BEFORE P2 FRONTEND HARDENS

- Preserve separate desktop Console and Field App.
- Introduce first-class professional scheduling capability.
- Schedule and operational work use the same STO activity identity.
- Prototype synchronized activity grid + Gantt + activity inspector.
- Formalize Reference / Operational / Working / History schedule-state meanings.
- Keep Live and Approved persistently distinguishable.
- Use explicit status-point grammar for actual history versus remaining future.
- Keep scenarios isolated and version-based.
- Treat "Why did this move?" as provenance-backed, never date-correlation inference.
- Preserve field report -> live result -> supervisor -> planner -> approved authority path.
- Keep communication contextual and non-authoritative.
- Preserve Queued / Accepted / Applied / Failed / Conflict distinctions.
- Ensure essential Gantt actions have non-drag alternatives.
- Apply keyboard/focus/non-colour accessibility rules.
- Run low-fidelity practitioner validation before hardening P2 screens.

## CAN BE DECIDED DURING P2

Exact saved-view defaults, pane sizes, column presets, inspector ordering/names, materiality thresholds, notification preferences, exact state copy where semantics are already fixed, final visual tokens and polish.

## DEFER TO P3/P4

Detailed Project/P6 writer screens, returned-file diff/reconciliation UI, writer-profile management, CMMS adapter configuration and site mapping.

## DEFER TO P6

Resource levelling controls, crew optimisation, permit/isolation/workface planning and optimisation explanation.

# 21. Open questions / TEST before P2

1. **Terminology:** Is "Execution" the clearest label for operational work? Is "Interchange" useful later?
2. **Navigation:** Does Schedule need a top-level zone exactly as proposed, and when should external systems become visible?
3. **Pane/inspector structure:** Do planners efficiently use the proposed grid/Gantt/inspector arrangement? Which groupings are natural?
4. **Visual state grammar:** Can users reliably distinguish Source, Baseline, Live, Approved and Scenario without relying on colour?
5. **Attention thresholds:** Which schedule changes deserve Today-level attention in real shutdown practice?
6. **Scenario promotion:** What exact interaction should bridge scenario proposal, planner authority and approved forecast under PL6/PL7?
7. **Causal provenance:** Does the scheduler expose enough explicit provenance to support trustworthy movement explanation? How should multiple causes be shown?
8. **Keyboard/bulk editing:** Which workflows require keyboard-first and bulk operations, and what safety preview is appropriate?
9. **Practitioner comprehension:** Can experienced planners identify schedule state, actual versus remaining future, live versus approved, scenario authority and movement cause?

# 22. Recommended repository documentation after review

Do not modify the frozen Design C repository. Preserve its provenance.

The initial current-STO documentation set should be deliberately small:

- `docs/research/2026-09-24-scheduling-ux-pass-1.md`
- `docs/product/ux-architecture-v1.md`
- `docs/product/scheduling-workspace.md`
- `docs/trials/sto-planner-ux-v1/`
- One current ADR superseding the old tracker-only/no-scheduler UX boundary.

Only split movement explainability or visual semantics into separate contracts later if complexity justifies it.

# 23. Final judgement

Pass 1 establishes a sufficiently supported design direction to begin STO UX Architecture v1 and low-fidelity prototyping. It does not establish a finished scheduler UI.

Design C remains the foundation for STO's operational character: attention-first control-room UX, separate desktop and field surfaces, restrained visual design, structured operational records, role-appropriate complexity and explicit offline state.

The obsolete part of that inheritance is the assumption that Microsoft Project owns scheduling and therefore STO should not expose professional scheduling interfaces.

The leading desktop architecture to validate is a synchronized WBS/activity table + Gantt + progressively disclosed activity inspector, with Schedule and operational work operating on the same STO activity identities.

STO's schedule model must visibly distinguish reference state, operational state, working scenarios and history. Actual history and future forecast must remain separated by an explicit status point. Live forecast and approved forecast must never be visually ambiguous.

"Why did this move?" should be a first-class STO design objective, but the UI may only present causal explanations supported by scheduler provenance. It must not infer causation from date correlation.

Exact navigation labels, pane structure, state visual treatments, scenario-promotion interaction, materiality thresholds and attention rules remain hypotheses requiring practitioner validation.

P3/P4 integration and P6 resource/operational scheduling should be accommodated architecturally but not designed in detail before their semantics exist.

**Next step: STO UX Architecture v1 -> low-fidelity scheduler/execution prototypes -> practitioner validation -> corrections -> P2 implementation.**

No further broad scheduling-UX research is required before that work. Additional research should be targeted only where prototyping or practitioner testing exposes a specific unresolved question.

# Source register

## Internal / project sources

[I1] Current STO README  
https://github.com/dezrobbo1/STO-Scheduler-Tracker-Research/blob/main/README.md

[I2] Current STO roadmap  
https://github.com/dezrobbo1/STO-Scheduler-Tracker-Research/blob/main/docs/goals/roadmap.json

[I3] ADR-016 - Field communication, offline delivery and execution authority  
https://github.com/dezrobbo1/STO-Scheduler-Tracker-Research/blob/main/docs/adr/ADR-016-field-communication-offline-delivery-and-execution-authority.md

[I4] Frozen ADR-009 - UX/UI Architecture  
https://github.com/dezrobbo1/Shutdown-Tracker-Claude/blob/main/docs/adr/ADR-009-ux-ui-architecture.md

[I5] Frozen UX Anti-Slop Rules  
https://github.com/dezrobbo1/Shutdown-Tracker-Claude/blob/main/docs/product/ux-anti-slop-rules.md

[I6] PM-Software planner trial exit gate  
https://github.com/dezrobbo1/PM-Software/blob/main/docs/trials/planner-update-recovery-v1/exit-gate.md

[I7] PM-Software completion questionnaire  
https://github.com/dezrobbo1/PM-Software/blob/main/docs/trials/planner-update-recovery-v1/questionnaire.md

[I8] Current STO P1 planner implementation  
https://github.com/dezrobbo1/STO-Scheduler-Tracker-Research/blob/main/src/sto/api/static/app.js

[I9] Original Pass 1 research report, uploaded 24 September 2026. This cleaned edition corrects and supersedes its presentation while preserving its evidence base.

## External documented patterns / guidance

[E1] Oracle Primavera P6 - Working with Activities  
https://docs.oracle.com/cd/G48897_01/p6help/en/6672.htm

[E2] Oracle Primavera P6 - Gantt and relationships  
https://docs.oracle.com/cd/G48897_01/p6help/en/38087.htm  
https://docs.oracle.com/cd/G48902_01/English/User_Guides/p6_pro_user/adding_relationships_between_activities.htm

[E3] Microsoft Project - Highlight how tasks link to other tasks  
https://support.microsoft.com/en-us/project/highlight-how-tasks-link-to-other-tasks

[E4] Microsoft Project - Critical path and slack  
https://support.microsoft.com/en-us/project/show-the-critical-path-of-your-project-in-project  
https://support.microsoft.com/en-us/project/show-slack-in-your-project-in-project-desktop

[E5] Safran Project - Barchart Editor  
https://docs.safran.com/docs/safran-project-introduction-to-the-barchart-editor  
https://docs.safran.com/docs/safran-project-working-with-the-barchart-editor

[E6] InEight Progress - Mobile overview and data sync  
https://learn.ineight.com/Progress/Content/Daily%20Planning%20Mobile/MobileOverview.htm  
https://learn.ineight.com/Progress/Content/Daily%20Planning%20Mobile/DataSync.htm

[E8] HSE - Control room design  
https://www.hse.gov.uk/comah/sragtech/techmeascontrol.htm

[E9] HSE - Alarm management  
https://www.hse.gov.uk/humanfactors/topics/alarm-management.htm

[E10] W3C - WCAG 2.2 dragging and target-size guidance  
https://www.w3.org/WAI/standards-guidelines/wcag/new-in-22/

[E11] Android Developers - Offline-first architecture  
https://developer.android.com/topic/architecture/data-layer/offline-first

## Source-use note

Vendor documentation in this report is used to establish documented interaction patterns and capabilities, not to claim that a product is easy to use or that STO should copy it. Human-factors guidance is used to support general design constraints and is not presented as a specification for scheduling software.

