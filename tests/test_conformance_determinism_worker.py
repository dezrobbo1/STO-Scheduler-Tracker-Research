"""One digest over every executable corpus case, runnable as its own process.

Kept beside the test that uses it rather than inside it, because the claim is
about *processes*: the comparison is only worth anything if a second
interpreter can compute the digest from a cold start, and that needs an entry
point it can run. Named ``test_`` so it is discovered alongside its test module
and cannot drift away from it; it declares no test cases of its own.

The digest is over each case's pass fingerprints, which are already canonical
hashes of the answers, so the whole corpus reduces to one comparable string.
"""

from __future__ import annotations

import hashlib

from conformance_fixture import _build_network, _load, _progress_policy

from sto import conformance
from sto.core.engine import backward_pass, float_analysis, forward_pass


def digest_of_every_executable_case() -> str:
    """A single SHA-256 over every executable case's three fingerprints.

    Cases are visited in sorted order so the digest does not depend on the
    order the corpus happens to enumerate them in, and every case contributes
    its forward, backward and float fingerprints -- so a change to any pass on
    any case moves the digest.
    """

    accumulator = hashlib.sha256()
    for case_id in sorted(conformance.executable_case_ids()):
        case = _load(case_id)
        network, _ = _build_network(case_id, case)
        forward = forward_pass(network, progress_policy=_progress_policy(case))
        backward = backward_pass(network, forward)
        floats = float_analysis(network, forward, backward)
        accumulator.update(case_id.encode("utf-8"))
        accumulator.update(forward.fingerprint.encode("utf-8"))
        accumulator.update(backward.fingerprint.encode("utf-8"))
        accumulator.update(floats.fingerprint.encode("utf-8"))
    return accumulator.hexdigest()


if __name__ == "__main__":
    print(digest_of_every_executable_case())
