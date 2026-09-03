from __future__ import annotations

import re

_ISO_DURATION = re.compile(
    r"^(?P<sign>-)?P"
    r"(?:(?P<weeks>\d+(?:\.\d+)?)W)?"
    r"(?:(?P<days>\d+(?:\.\d+)?)D)?"
    r"(?:T"
    r"(?:(?P<hours>\d+(?:\.\d+)?)H)?"
    r"(?:(?P<minutes>\d+(?:\.\d+)?)M)?"
    r"(?:(?P<seconds>\d+(?:\.\d+)?)S)?"
    r")?$"
)


def parse_iso_duration_seconds(value: str | None) -> int | float | None:
    """Parse the ISO-8601 duration subset used by MSPDI.

    Months and years are intentionally unsupported because their length is not
    fixed. MSPDI schedule durations normally use week/day/time components.
    """

    if value is None or value == "":
        return None
    match = _ISO_DURATION.fullmatch(value)
    if match is None:
        raise ValueError(f"Unsupported ISO-8601 duration: {value!r}")
    parts = {
        key: float(raw) if raw is not None else 0.0
        for key, raw in match.groupdict().items()
        if key != "sign"
    }
    seconds = (
        parts["weeks"] * 7 * 24 * 60 * 60
        + parts["days"] * 24 * 60 * 60
        + parts["hours"] * 60 * 60
        + parts["minutes"] * 60
        + parts["seconds"]
    )
    if match.group("sign"):
        seconds *= -1
    rounded = round(seconds)
    return int(rounded) if abs(seconds - rounded) < 1e-9 else seconds


def duration_value(raw: str | None) -> dict[str, object] | None:
    if raw is None or raw == "":
        return None
    try:
        seconds = parse_iso_duration_seconds(raw)
    except ValueError:
        return {"raw": raw, "seconds": None, "parse_status": "unsupported"}
    return {"raw": raw, "seconds": seconds, "parse_status": "parsed"}
