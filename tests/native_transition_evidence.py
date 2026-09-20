"""Bounded classification for the pinned BOILER native-progress transition.

This is evidence tooling, not a general returned-file classifier.  It compares
the exact fields named by P1-G3 and treats every change outside the documented
completion contract as unexplained.  In particular, it does not infer that a
downstream date change is expected merely because Project recalculated a file.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Mapping, Sequence


FIELD_NAMES = (
    "start",
    "finish",
    "early_start",
    "early_finish",
    "late_start",
    "late_finish",
    "total_float",
    "free_float",
    "critical",
    "actual_start",
    "actual_finish",
    "remaining_duration",
    "percent_complete",
)

# These are distinct fields.  In particular, Start/Finish are not substitutes
# for EarlyStart/EarlyFinish when deciding whether a row changed.
DOCUMENTED_COMPLETION_CHANGE = frozenset(
    {
        "late_start",
        "late_finish",
        "total_float",
        "actual_start",
        "actual_finish",
        "remaining_duration",
        "percent_complete",
    }
)


@dataclass(frozen=True)
class NativeTransitionSummary:
    before_rows: int
    after_rows: int
    common_rows: int
    unchanged_common_rows: int
    documented_completion_rows: int
    unexplained_changed_common_rows: int
    before_only_rows: int
    after_only_rows: int
    field_change_counts: tuple[tuple[str, int], ...]

    @property
    def changed_common_rows(self) -> int:
        return self.documented_completion_rows + self.unexplained_changed_common_rows

    @property
    def unresolved_identity_rows(self) -> int:
        return self.before_only_rows + self.after_only_rows

    @property
    def unresolved_rows(self) -> int:
        return self.unexplained_changed_common_rows + self.unresolved_identity_rows

    def assert_reconciled(self) -> None:
        assert self.common_rows == (
            self.unchanged_common_rows
            + self.documented_completion_rows
            + self.unexplained_changed_common_rows
        )
        assert self.before_rows + self.after_only_rows == (
            self.common_rows + self.before_only_rows + self.after_only_rows
        )
        assert self.after_rows + self.before_only_rows == (
            self.common_rows + self.before_only_rows + self.after_only_rows
        )


def classify_native_transition(
    before: Mapping[str, Sequence[object]],
    after: Mapping[str, Sequence[object]],
    *,
    documented_completion_uids: frozenset[str],
) -> NativeTransitionSummary:
    """Classify only the differences supported by the pinned evidence record."""

    for cohort in (before, after):
        for values in cohort.values():
            if len(values) != len(FIELD_NAMES):
                raise ValueError("native-transition row does not match the field contract")

    unchanged = 0
    documented = 0
    unexplained = 0
    field_counts: Counter[str] = Counter()
    for uid in before.keys() & after.keys():
        changed = frozenset(
            name
            for name, old, new in zip(FIELD_NAMES, before[uid], after[uid])
            if old != new
        )
        field_counts.update(changed)
        if not changed:
            unchanged += 1
        elif (
            uid in documented_completion_uids
            and changed == DOCUMENTED_COMPLETION_CHANGE
        ):
            documented += 1
        else:
            unexplained += 1

    summary = NativeTransitionSummary(
        before_rows=len(before),
        after_rows=len(after),
        common_rows=len(before.keys() & after.keys()),
        unchanged_common_rows=unchanged,
        documented_completion_rows=documented,
        unexplained_changed_common_rows=unexplained,
        before_only_rows=len(before.keys() - after.keys()),
        after_only_rows=len(after.keys() - before.keys()),
        field_change_counts=tuple(
            (name, field_counts[name]) for name in FIELD_NAMES if field_counts[name]
        ),
    )
    summary.assert_reconciled()
    return summary
