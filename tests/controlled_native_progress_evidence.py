"""Bounded field classifier for P1-NATIVE-PROGRESS-BOILER-UID15-V1.

This is not a returned-file framework.  It encodes the comparison contract
fixed before the controlled Microsoft Project output existed: every result
field is independent, engine agreement is admissible only from a baseline
field that already agreed, and exclusions cannot explain a changed value.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Iterable, Mapping, Sequence, TypeVar


RESULT_FIELDS = (
    "start",
    "finish",
    "early_start",
    "early_finish",
    "late_start",
    "late_finish",
    "total_float",
    "free_float",
    "critical",
)

UNCHANGED = "UNCHANGED"
BASELINE_MISMATCH = "BASELINE_MISMATCH"
DIRECT_CONTROLLED_EDIT = "DIRECT_CONTROLLED_EDIT"
PROJECT_DERIVED_PROGRESS_INPUT = "PROJECT_DERIVED_PROGRESS_INPUT"
ENGINE_NATIVE_AGREEMENT = "ENGINE_NATIVE_AGREEMENT"
EXPLICIT_EXCLUSION = "EXPLICIT_EXCLUSION"
UNEXPLAINED = "UNEXPLAINED"
T = TypeVar("T")


@dataclass(frozen=True)
class ControlledNativeSummary:
    before_rows: int
    after_rows: int
    common_rows: int
    added_rows: int
    removed_rows: int
    field_slots: int
    classifications: tuple[tuple[str, int], ...]
    unexplained: tuple[tuple[str, str], ...]
    baseline_mismatches: tuple[tuple[str, str], ...]

    @property
    def unexplained_count(self) -> int:
        return (
            len(self.unexplained)
            + len(self.baseline_mismatches)
            + self.added_rows
            + self.removed_rows
        )

    @property
    def unexpected_transition_count(self) -> int:
        """Changed or missing native rows outside the transition contract."""

        return len(self.unexplained) + self.added_rows + self.removed_rows

    def assert_reconciled(self) -> None:
        assert self.before_rows == self.common_rows + self.removed_rows
        assert self.after_rows == self.common_rows + self.added_rows
        assert sum(dict(self.classifications).values()) == self.field_slots


def unique_rows(rows: Iterable[tuple[str, T]]) -> dict[str, T]:
    """Index source identities and refuse the ambiguous cases evidence cannot use."""

    indexed: dict[str, T] = {}
    for identity, values in rows:
        if not identity:
            raise ValueError("controlled-native row has no source identity")
        if identity in indexed:
            raise ValueError(f"duplicate controlled-native source identity: {identity}")
        indexed[identity] = values
    return indexed


def _validate(rows: Mapping[str, Sequence[object]], label: str) -> None:
    for identity, values in rows.items():
        if not identity:
            raise ValueError(f"{label} row has no source identity")
        if len(values) != len(RESULT_FIELDS):
            raise ValueError(f"{label} row does not match the result-field contract")


def classify_controlled_transition(
    before_observed: Mapping[str, Sequence[object]],
    native_observed: Mapping[str, Sequence[object]],
    before_engine: Mapping[str, Sequence[object]],
    controlled_engine: Mapping[str, Sequence[object]],
    native_engine: Mapping[str, Sequence[object]],
    explicit_exclusions: Mapping[str, str],
) -> ControlledNativeSummary:
    """Classify the complete result-field cohort without causal inference."""

    for label, rows in (
        ("before observed", before_observed),
        ("native observed", native_observed),
        ("before engine", before_engine),
        ("controlled engine", controlled_engine),
        ("native engine", native_engine),
    ):
        _validate(rows, label)

    before_ids = set(before_observed)
    after_ids = set(native_observed)
    common = before_ids & after_ids
    engine_ids = set(before_engine)
    if engine_ids != set(controlled_engine) or engine_ids != set(native_engine):
        raise ValueError("controlled-native engine disposition changed between inputs")
    if not engine_ids <= common:
        raise ValueError("controlled-native engine result lacks a common source identity")
    excluded_ids = set(explicit_exclusions)
    if any(not code for code in explicit_exclusions.values()):
        raise ValueError("controlled-native explicit exclusion has no code")
    if engine_ids & excluded_ids or engine_ids | excluded_ids != common:
        raise ValueError(
            "controlled-native rows do not form an exact scheduled/excluded partition"
        )
    counts: Counter[str] = Counter()
    unexplained: list[tuple[str, str]] = []
    baseline_mismatches: list[tuple[str, str]] = []

    for identity in sorted(common, key=lambda item: (not item.isdigit(), item)):
        old_observed = before_observed[identity]
        new_observed = native_observed[identity]
        old_engine = before_engine.get(identity)
        expected_engine = controlled_engine.get(identity)
        recalculated_engine = native_engine.get(identity)

        for index, field in enumerate(RESULT_FIELDS):
            old_value = old_observed[index]
            new_value = new_observed[index]
            if old_engine is None or expected_engine is None:
                reason = EXPLICIT_EXCLUSION if old_value == new_value else UNEXPLAINED
            else:
                engine_changed = old_engine[index] != expected_engine[index]
                native_changed = old_value != new_value
                if not engine_changed and not native_changed:
                    if (
                        old_engine[index] == old_value
                        and recalculated_engine is not None
                        and recalculated_engine[index] == new_value
                    ):
                        reason = UNCHANGED
                    else:
                        reason = BASELINE_MISMATCH
                elif (
                    old_engine[index] == old_value
                    and new_value == expected_engine[index]
                    and recalculated_engine is not None
                    and recalculated_engine[index] == expected_engine[index]
                ):
                    reason = ENGINE_NATIVE_AGREEMENT
                else:
                    reason = UNEXPLAINED
            counts[reason] += 1
            if reason == UNEXPLAINED:
                unexplained.append((identity, field))
            elif reason == BASELINE_MISMATCH:
                baseline_mismatches.append((identity, field))

    summary = ControlledNativeSummary(
        before_rows=len(before_ids),
        after_rows=len(after_ids),
        common_rows=len(common),
        added_rows=len(after_ids - before_ids),
        removed_rows=len(before_ids - after_ids),
        field_slots=len(common) * len(RESULT_FIELDS),
        classifications=tuple(sorted(counts.items())),
        unexplained=tuple(unexplained),
        baseline_mismatches=tuple(baseline_mismatches),
    )
    summary.assert_reconciled()
    return summary


def classify_selected_progress(
    *,
    before_actual_start: object,
    after_actual_start: object,
    expected_actual_start: object,
    before_remaining: int,
    after_remaining: int,
    expected_remaining: int,
    before_planned: int,
    after_planned: int,
    before_actual: int,
    after_actual: int,
    after_percent_permille: int,
    after_actual_finish: object,
    assignment_units_permille: int,
    before_task_work: int,
    after_task_work: int,
    before_assignment_work: int,
    after_assignment_work: int,
    before_assignment_actual_work: int,
    after_assignment_actual_work: int,
    after_assignment_remaining_work: int,
) -> tuple[tuple[str, int], ...]:
    """Classify the exact edit and Project's measured normalizations."""

    counts: Counter[str] = Counter()
    if before_actual_start is None and after_actual_start == expected_actual_start:
        counts[DIRECT_CONTROLLED_EDIT] += 1
    else:
        counts[UNEXPLAINED] += 1
    if before_remaining != expected_remaining and after_remaining == expected_remaining:
        counts[DIRECT_CONTROLLED_EDIT] += 1
    else:
        counts[UNEXPLAINED] += 1

    expected_percent = 0 if after_planned == 0 else round(after_actual * 1000 / after_planned)
    if (
        before_actual == 0
        and after_actual == before_actual
        and before_planned != after_planned
        and after_planned == after_actual + after_remaining
        and after_percent_permille == expected_percent
        and after_actual_finish is None
    ):
        counts[PROJECT_DERIVED_PROGRESS_INPUT] += 1
    else:
        counts[UNEXPLAINED] += 1
    expected_work = round(after_remaining * assignment_units_permille / 1000)
    if (
        before_task_work != after_task_work
        and after_task_work == expected_work
    ):
        counts[PROJECT_DERIVED_PROGRESS_INPUT] += 1
    else:
        counts[UNEXPLAINED] += 1
    if (
        before_assignment_work != after_assignment_work
        and after_assignment_work == expected_work
        and before_assignment_actual_work == 0
        and after_assignment_actual_work == before_assignment_actual_work
        and after_assignment_work
        == after_assignment_actual_work + after_assignment_remaining_work
    ):
        counts[PROJECT_DERIVED_PROGRESS_INPUT] += 1
    else:
        counts[UNEXPLAINED] += 1
    return tuple(sorted(counts.items()))
