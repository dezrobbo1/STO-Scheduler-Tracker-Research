# RC01 native V1 return: input contract failed (append-only receipt)

The genuine Microsoft Project return for `P1-G2-RC01-ASSIGNMENT-ENVELOPE-NATIVE-MATRIX-V1`
is an external, immutable 54,152-byte XML file with SHA-256
`5c190a0d4f41068559f37db845ec0d17a265dea89442453898d6daa3bc2b28ab`.
Its generated input is the unchanged committed 20,989-byte V1 MSPDI with SHA-256
`9d7ad7a8a845fcf036827fe90b51d41431d0452ece57097ce86934bec8119313`.

The predeclared V1 analyzer stops at `project input changed: GUID`. Direct
read-only comparison shows additional contract failures: Project regenerated
the four resource GUIDs, renamed calendar UIDs 2–5 `Unassigned`, and
recalculated task Duration and RemainingDuration from four to eight hours on
the separated-calendar cases A and B. It also inserted a default calendar,
summary task and null resource, normalized empty task calendars to `-1` and
levelling delay formats from `7` to `8`, and added save metadata/options.
Task, assignment and calendar GUIDs; all seven assignment Work and Units
values; their declaration order; the resource-to-calendar UID links; and the
working intervals survived. The companion JSON records these observations.

The returned task spans are A/B 08:00–17:00, C/D 08:00–12:00, but the
failed contract forbids either support or rejection of the RC01 hypothesis.
The sole V1 disposition is
`NATIVE_RETURN_INPUT_NORMALIZED_BEYOND_V1_CONTRACT`. It authorizes neither
BOILER counterfactual nor production correction. The native return itself
remains external and has not been edited or committed. The original V1
experiment and post-RC02 historical evidence remain unchanged.
