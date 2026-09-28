"""Independent fixed-matrix date/float oracle; no production scheduler imports."""
from __future__ import annotations

from datetime import datetime, timedelta

from scripts.evidence import p1_g2_rc01_networked_v3_generate as matrix

HOUR = timedelta(hours=1)


def signed_project_minutes(earlier: datetime, later: datetime) -> int:
    """Independent weekday 07:30–15:30 measuring calendar (BOILER class)."""
    if later < earlier:
        return -signed_project_minutes(later, earlier)
    minutes = 0
    cursor = earlier.replace(hour=0, minute=0, second=0, microsecond=0)
    while cursor < later:
        if cursor.weekday() < 5:
            start = max(earlier, cursor + timedelta(hours=7, minutes=30))
            end = min(later, cursor + timedelta(hours=15, minutes=30))
            if end > start:
                minutes += int((end - start).total_seconds() // 60)
        cursor += timedelta(days=1)
    return minutes


def _intervals(day: datetime, calendar: int) -> tuple[tuple[datetime, datetime], ...]:
    midnight = day.replace(hour=0, minute=0, second=0, microsecond=0)
    if calendar == 2:
        return ((midnight, midnight + timedelta(days=1)),)
    if calendar in (3, 4):
        return ((midnight + 7 * HOUR, midnight + 17 * HOUR),)
    raise ValueError("unknown synthetic resource calendar")


def placement(bound: datetime, hours: int, calendar: int, *, backward: bool = False) -> tuple[datetime, datetime]:
    """Consume Work/Units on a separate resource's daily working intervals."""
    remaining = timedelta(hours=hours)
    cursor = bound
    edge: datetime | None = None
    for _ in range(60):
        if backward:
            day = cursor if cursor.time() != datetime.min.time() else cursor - timedelta(days=1)
            candidates = reversed(_intervals(day, calendar))
        else:
            day = cursor
            candidates = _intervals(cursor, calendar)
        for start, finish in candidates:
            if backward:
                finish = min(finish, cursor)
                if finish <= start:
                    continue
                consumed = min(remaining, finish - start)
                cursor = finish - consumed
                if edge is None:
                    edge = finish
            else:
                start = max(start, cursor)
                if finish <= start:
                    continue
                consumed = min(remaining, finish - start)
                cursor = start + consumed
                if edge is None:
                    edge = start
            remaining -= consumed
            if not remaining:
                assert edge is not None
                return (cursor, edge) if backward else (edge, cursor)
        day_start = day.replace(hour=0, minute=0, second=0, microsecond=0)
        cursor = day_start if backward else day_start + timedelta(days=1)
    raise ValueError("synthetic calendar horizon exhausted")


def _reference(*, end_padding: bool) -> dict[str, dict]:
    tasks, edges, assignments = matrix.graph()
    incoming = {name: list(spec["predecessors"]) for name, spec in tasks.items()}
    outgoing: dict[str, list[str]] = {name: [] for name in tasks}
    for edge in edges:
        outgoing[edge["predecessor"]].append(edge["successor"])
    project_start = datetime.fromisoformat(matrix.PROJECT_START)
    predicted: dict[str, dict] = {}
    for name, spec in tasks.items():
        bound = max((predicted[p]["early_finish"] for p in incoming[name]),
                    default=project_start)
        rows = [a for a in assignments.values() if a["task"] == name]
        early_assignments = {}
        for assignment in rows:
            effective = assignment["work"] // assignment["units"]
            if effective * assignment["units"] != assignment["work"]:
                raise ValueError("fractional assignment effective duration")
            early_assignments[assignment["uid"]] = placement(
                bound, effective, assignment["calendar"])
        start = min(x[0] for x in early_assignments.values())
        finish = max(x[1] for x in early_assignments.values())
        pad = max(0, spec["duration"] - int((finish - start).total_seconds() // 3600)) \
            if end_padding and len(rows) == 2 else 0
        predicted[name] = {"early_start": start,
                           "early_finish": finish + pad * HOUR,
                           "assignments": early_assignments,
                           "end_padding_hours": pad,
                           "effective_hours": {a["uid"]: a["work"] // a["units"] for a in rows}}
    finish = max(row["early_finish"] for row in predicted.values())
    for name in reversed(tuple(tasks)):
        bound = min((predicted[s]["late_start"] for s in outgoing[name]),
                    default=finish)
        rows = [a for a in assignments.values() if a["task"] == name]
        assignment_bound = bound - predicted[name]["end_padding_hours"] * HOUR
        late_assignments = {a["uid"]: placement(assignment_bound, a["work"] // a["units"],
                                                a["calendar"], backward=True) for a in rows}
        row = predicted[name]
        row["late_start"] = min(x[0] for x in late_assignments.values())
        row["late_finish"] = max(x[1] for x in late_assignments.values()) + \
            row["end_padding_hours"] * HOUR
        row["late_assignments"] = late_assignments
        row["total_slack_minutes"] = min(
            signed_project_minutes(row["early_start"], row["late_start"]),
            signed_project_minutes(row["early_finish"], row["late_finish"]))
        row["free_slack_minutes"] = signed_project_minutes(
            row["early_finish"], min((predicted[s]["early_start"]
                                      for s in outgoing[name]), default=finish))
        row["critical"] = row["total_slack_minutes"] <= 0
    predicted["_project_finish"] = finish
    return predicted


def reference() -> dict[str, dict]:
    """Predeclared independent assignment-envelope candidate."""
    return _reference(end_padding=False)


def padded_reference() -> dict[str, dict]:
    """Coherent alternative: declared-duration end padding after envelope."""
    return _reference(end_padding=True)
