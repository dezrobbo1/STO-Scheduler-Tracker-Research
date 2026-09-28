# RC01 V2 Microsoft Project return: two immutable uploaded files

This append-only receipt follows the V2 experiment contract and preserves both
uploaded native files outside the repository. The committed machine-readable
analyzer outputs are
`p1-g2-rc01-native-v2-invalid-return-2026-09-28.json` and
`p1-g2-rc01-native-v2-valid-return-2026-09-28.json`. Neither native XML file
is committed. The frozen V2 input and the earlier V1 records are unchanged.

| File supplied | Bytes | SHA-256 | Frozen analyzer verdict |
|---|---:|---|---|
| `P1-G2-RC01-ASSIGNMENT-ENVELOPE-NATIVE-MATRIX-V2-returned.xml` | 54,123 | `3dfb874e7e0e5bb72502b1b87a0e884c96dcb5a730155fc156436a9579fa62f4` | `V2_INPUT_CONTRACT_VIOLATED`: `project input changed: Name` |
| `P1-G2-RC01-ASSIGNMENT-ENVELOPE-NATIVE-MATRIX-V2.xml` (separate uploaded Project save, **not** the committed input) | 54,152 | `674b2a70649991ac6b9624ced1d16ca88a5287fed35da08486a59986360d513e` | `V2_ASSIGNMENT_ENVELOPE_SUPPORTED` |

The 54,123-byte return has internal Project.Name ending in `V2-returned.xml`;
the 54,152-byte return has the exact predeclared internal Project.Name ending
in `V2.xml`. File basenames alone do not prove which is the generated input:
the **committed generated input** is 20,989 bytes, SHA-256
`f8c0b622e257186ee30c6b933aedebe697841dc41f72b2c3137ba0f77126cb0c`.
Both external uploads have native BuildNumber `16.0.20326.20140`. No source
XML was changed to obtain either verdict. The in-memory diagnostic substitution
previously attempted on the invalid return is not used as evidence here.

## Valid native observation

The valid 54,152-byte Project save passes all frozen experiment-defining input
checks and all seven acceptance predicates, including the assignment-order
twin and both controls. Its case A and B tasks each run 08:00–17:00 with
eight-hour returned Duration, and their AM and PM assignments work
08:00–12:00 and 13:00–17:00 respectively. Case C's overlapping resources and
case D's single resource each finish at 12:00 with four-hour Duration. Project
and task input identities, calendars, assignment Work and Units, topology and
declaration order pass the predeclared comparison. See the exact observations,
input identity, predicate outcomes and decision in the machine-readable valid
return record.

The V2 assignment-envelope hypothesis is **supported for this synthetic
matrix and Project build**. The valid native return authorizes only a later,
separate, **diagnostic-only BOILER counterfactual** against an exact verified
BOILER fixture. That counterfactual has **not run** here. No production RC01
correction is authorized and no claim has been made about the customer BOILER
outcome. P1-G2 stays **OPEN**, P1 remains **4/5 IN PROGRESS**, and P2 has
**NOT STARTED**.
