# V3-R6 project-calendar seed and tool-identity preregistration — **not run**

The uploaded **R4** file remains `V3_INPUT_CONTRACT_VIOLATED` (1,722,330 bytes, SHA-256 `8ff29979fad5776af5909ca26f17715017793cf85a99b8308ab0a4adcd4baa33`), with no native or production authorization. The **R5** input was committed but **never run**: 122,130 bytes, SHA-256 `053cbd7b569cc34c53cbfce11ec6b0370c78ef0483e4eb358ce58d4da54d516a`. R4/R5 evidence and fixtures remain unchanged, append-only. Two Codex findings on the R5 head are accepted before any further desktop run.

The first finding: R5 seeded each task's declared Duration as an **elapsed** Start→Finish even though the project has a weekday 07:30–15:30 calendar and the `PROJECT` Duration model is admitted by the preregistered experiment. Thus its 72-hour finish driver seeded only 24 project-working hours. This new [R6 synthetic input](../../tests/fixtures/P1-G2-RC01-NETWORKED-ASSIGNMENT-ENVELOPE-NATIVE-MATRIX-V3-R6.xml) seeds task Start/Finish/EarlyFinish/LateFinish by **consuming the declared Duration on that exact project calendar**. Source examples: one-hour predecessor Monday 08:00→09:00, eight-hour GAP predecessor Monday 08:00→Tuesday 08:00, 72-hour independent finish driver Monday 08:00→Friday 23 October 08:00. Project.FinishDate is seeded to the latest task finish, Friday 23 October 08:00. Assignment seed Finish still consumes exact Work/Units on each resource calendar from Monday 08:00. The Project source coordinates are now internally coherent under the admitted project-calendar task Duration interpretation. Which *returned* duration model Project actually follows is still open: one global PROJECT or RESOURCE_UNION output model must fit all 35 tasks, and mixed/neither remains INCONCLUSIVE. A different native result is never constructed from the R4 return.

The second finding: a matching fixture/evidence hash did not pin the exact analyzer/generator/oracle code. The [separate R6 pre-result tool manifest](p1-g2-rc01-networked-native-v3-r6-tool-identity-2026-09-28.json) fixes SHA-256 identities for all three complete scripts plus input identity. Before any R6 return is read, the analyzer verifies the committed preregistration identity, exact input, manifest and **all three script bytes**. Its result records manifest hash, preregistration hash and each tool hash. A code edit after a native observation fails closed rather than silently changing an apparently R6-governed decision. The published, reviewed PR head and manifest identity must be recorded before sending this input to Project; any later script change requires a new preregistration and native round trip.

The *new* R6 file is **122,130 bytes**, SHA-256 `414b78b7eef5ed41392ca387d89e60dc59488e74ba4dec6fdc2784a54a88a2d6`, and the fixed Project.Name/return basename both are `P1-G2-RC01-NETWORKED-ASSIGNMENT-ENVELOPE-NATIVE-MATRIX-V3-R6.xml`. Deterministic UIDs/GUIDs, 35 tasks, 46 assignments, project/resource calendar intervals, every topology/allocation case, root-to-class mapping, Work/Units, exact semantic input validation, independent candidate oracle SHA-256 `e4c9182660a825f68c9ec79f1ec8a02738c92c628329567e0cbc1cc4c843c1dc`, coherent rejection, global duration alternatives, source-safe output and all gate decisions remain unchanged. A machine SUPPORT result still cannot prove Microsoft Project provenance or authorize a production correction without independent user-attested desktop evidence.

## R6 desktop procedure

1. Download **only the 122,130-byte R6 XML** and verify SHA-256 `414b78b7eef5ed41392ca387d89e60dc59488e74ba4dec6fdc2784a54a88a2d6`.
2. Open in Microsoft Project desktop; make no edits; do not invoke Resource Leveling; recalculate the entire project (F9).
3. Save as MSPDI XML in another folder using the **identical input basename** `P1-G2-RC01-NETWORKED-ASSIGNMENT-ENVELOPE-NATIVE-MATRIX-V3-R6.xml`; do not edit the saved XML.
4. Return the new Project-saved file and explicitly confirm that those steps were performed on this exact input without editing or levelling. Then use the exact published tool identity:

```bash
python3 scripts/evidence/p1_g2_rc01_networked_v3.py \
  /path/to/returned/P1-G2-RC01-NETWORKED-ASSIGNMENT-ENVELOPE-NATIVE-MATRIX-V3-R6.xml \
  --output /separate/path/p1-g2-rc01-networked-v3-r6-result.json
```

R6 native result **NOT RUN / REQUIRED**; P1-G2 OPEN, P1 4/5 IN PROGRESS, P2 NOT STARTED, and no production RC01 fix is made.
