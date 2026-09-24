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

