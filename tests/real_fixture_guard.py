"""Identity guard for customer schedules kept outside the repository."""

from __future__ import annotations

import hashlib
from functools import lru_cache
from pathlib import Path


# Day-5 is the one unavailable file for which the surviving record contains
# only a digest prefix. Its exact byte size is also required. Every available
# fixture has its complete SHA-256 pinned here.
RECORDED = {
    "boiler_untouched": (
        "e6a3739976580e2144352011f818c0099c0dc0c278fb37a976c5b6a55fbc3420",
        3_734_688,
    ),
    "boiler_before": (
        "e9b9b7994cc5cc50479807b82c452da742a91de9f7de52b172a6be6f4f399c70",
        3_361_935,
    ),
    "day5": ("a8d44aa23e20c510", 3_747_935),
    "after_native": (
        "9fabe70debd004aceabe749f3c13abe40823f43746d7db2b15572466c76739c7",
        3_871_501,
    ),
    "roundtrip_saved": (
        "aff57ce8466d619466c51cb6b0366d25933dc6080d256859a961a1154c4c2dc8",
        3_362_829,
    ),
    "kiln": (
        "b7c14b631ecc7c15db7731e4a5159ecefe68aaa1c10e76262f84db6b8c37d3ca",
        3_474_383,
    ),
    "calciner": (
        "e952764512ae718e2701c0c79435025b07a5b09124fee4d51b385e92367ed18d",
        14_280_544,
    ),
}


@lru_cache(maxsize=None)
def _identity(path: Path) -> tuple[int, str]:
    return path.stat().st_size, hashlib.sha256(path.read_bytes()).hexdigest()


def verify_available(fixtures: dict[str, Path]) -> None:
    """Reject any present fixture that is not the recorded evidence object."""

    for role, path in fixtures.items():
        if not path.is_file():
            continue
        expected_digest, expected_size = RECORDED[role]
        size, digest = _identity(path)
        if size != expected_size or not digest.startswith(expected_digest):
            raise RuntimeError(
                f"{role} fixture does not match its evidence identity: {path}; "
                f"expected {expected_size} bytes and SHA-256 {expected_digest}, "
                f"got {size} bytes and {digest}"
            )
