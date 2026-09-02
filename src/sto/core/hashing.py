"""Canonical serialisation and hashing for the STO canonical model.

Two rules carried forward from the research repositories, both deliberate:

*   Object keys are sorted and separators are tight, so the same document always
    produces the same bytes. Array order stays meaningful and is controlled by
    the model's own ``seq``/``source_order`` fields.
*   Floats are refused. A float in the time or quantity domain makes the hash
    depend on binary rounding, which is how two identical-looking imports come
    to disagree. Durations are integer seconds, percentages are integer
    per-mille, and units are integer per-mille; anything that arrives as a float
    is a modelling defect and is raised here rather than hashed.

Text is normalised to NFC before hashing so that a name typed with a combining
accent and one typed with a precomposed character do not hash differently.
"""

from __future__ import annotations

import hashlib
import json
import unicodedata
from pathlib import Path
from typing import Any


class CanonicalHashError(ValueError):
    """Raised when a value cannot be canonically serialised."""


def _canonicalise(value: Any, path: str = "$") -> Any:
    if isinstance(value, bool) or value is None or isinstance(value, int):
        return value
    if isinstance(value, float):
        raise CanonicalHashError(
            f"float at {path}: canonical documents carry integers "
            "(seconds, per-mille) so that hashing cannot depend on binary rounding"
        )
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value)
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise CanonicalHashError(f"non-string key at {path}: {key!r}")
            out[unicodedata.normalize("NFC", key)] = _canonicalise(item, f"{path}.{key}")
        return out
    if isinstance(value, (list, tuple)):
        return [_canonicalise(item, f"{path}[{index}]") for index, item in enumerate(value)]
    raise CanonicalHashError(f"unsupported type {type(value).__name__} at {path}")


def canonical_json_bytes(value: Any) -> bytes:
    """Serialise deterministically, refusing floats and normalising text."""

    return json.dumps(
        _canonicalise(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def file_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
