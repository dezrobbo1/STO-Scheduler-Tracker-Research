"""The indexed arithmetic agrees with the reference on every input tried.

The reference functions are PM-Software's, verbatim, and the conformance
corpus was declared against them. The indexed functions exist so the engine
can ask in O(log n); the only thing that matters about them is that they
answer identically. So: many random interval sets, many random coordinates,
every function against its reference.
"""

from __future__ import annotations

import random
import unittest

from sto.core.calendar.arithmetic import (
    CompiledIntervals,
    add_working,
    consume_duration,
    contains_coordinate,
    earliest_span,
    next_working,
    prev_working,
    productive_segments,
    shift_working_time,
    sub_working,
    working_between,
)


def _reference_earliest_span(start_lb, finish_lb, duration, intervals, horizon):
    """PM-Software's earliest_span, verbatim: a scan over every coordinate."""

    for candidate_start in range(max(0, start_lb), horizon + 1):
        candidate_finish = consume_duration(candidate_start, duration, intervals)
        if (
            candidate_finish is not None
            and candidate_finish <= horizon
            and candidate_finish >= finish_lb
        ):
            return candidate_start, candidate_finish
    return None


def _random_intervals(rng: random.Random, span: int) -> tuple[tuple[int, int], ...]:
    out = []
    cursor = rng.randint(0, 5)
    while cursor < span:
        length = rng.randint(1, 12)
        out.append((cursor, min(cursor + length, span)))
        cursor += length + rng.randint(1, 10)
    return tuple(out)


class HandCases(unittest.TestCase):
    """SEM-CAL-021's calendar: 4 on, 1 off, 4 on, then the next day at 24."""

    def setUp(self):
        self.c = CompiledIntervals.of([(0, 4), (5, 9), (24, 28), (29, 33)])

    def test_six_units_across_lunch_finish_at_seven(self):
        self.assertEqual(add_working(self.c, 0, 6), 7)

    def test_zero_keeps_its_coordinate_even_in_a_gap(self):
        self.assertEqual(add_working(self.c, 4, 0), 4)
        self.assertEqual(sub_working(self.c, 4, 0), 4)

    def test_a_start_in_a_gap_begins_at_the_next_interval(self):
        self.assertEqual(add_working(self.c, 4, 1), 6)
        self.assertEqual(next_working(self.c, 4), 5)

    def test_a_finish_in_a_gap_ends_at_the_previous_edge(self):
        self.assertEqual(prev_working(self.c, 4), 4)
        self.assertEqual(prev_working(self.c, 20), 9)
        self.assertEqual(sub_working(self.c, 20, 1), 8)

    def test_subtraction_inverts_addition(self):
        self.assertEqual(sub_working(self.c, 7, 6), 0)
        self.assertEqual(sub_working(self.c, 26, 4), 7)  # 2 back to 24, then 2 off the 9 edge

    def test_beyond_the_horizon_is_none_not_a_guess(self):
        self.assertIsNone(add_working(self.c, 0, 17))
        self.assertIsNone(sub_working(self.c, 0, 1))
        self.assertIsNone(next_working(self.c, 33))

    def test_working_between_counts_only_working_time(self):
        self.assertEqual(working_between(self.c, 0, 33), 16)
        self.assertEqual(working_between(self.c, 3, 6), 2)

    def test_earliest_span_respects_both_bounds(self):
        self.assertEqual(earliest_span(self.c, 0, 0, 6, 400), (0, 7))
        self.assertEqual(earliest_span(self.c, 0, 8, 2, 400), (6, 8))
        self.assertEqual(earliest_span(self.c, 0, 0, 0, 400), (0, 0))
        self.assertEqual(earliest_span(self.c, 4, 4, 0, 400), (5, 5))

    def test_negative_duration_is_an_error_here_and_none_there(self):
        with self.assertRaises(ValueError):
            add_working(self.c, 0, -1)
        self.assertIsNone(consume_duration(0, -1, self.c.intervals))


class ReferenceDifferentialTests(unittest.TestCase):
    """Ten thousand random inputs per function against PM-Software's code."""

    TRIALS = 10_000

    def setUp(self):
        self.rng = random.Random(20260903)

    def _cases(self):
        for _ in range(self.TRIALS):
            intervals = _random_intervals(self.rng, self.rng.randint(10, 120))
            if not intervals:
                continue
            span = intervals[-1][1]
            yield CompiledIntervals.of(intervals), intervals, self.rng.randint(-3, span + 3)

    def test_add_working_agrees_with_positive_shift(self):
        for c, intervals, anchor in self._cases():
            lag = self.rng.randint(1, 40)
            self.assertEqual(
                add_working(c, anchor, lag),
                shift_working_time(anchor, lag, intervals),
                f"add {anchor}+{lag} on {intervals}",
            )

    def test_sub_working_agrees_with_negative_shift(self):
        for c, intervals, anchor in self._cases():
            lag = self.rng.randint(1, 40)
            self.assertEqual(
                sub_working(c, anchor, lag),
                shift_working_time(anchor, -lag, intervals),
                f"sub {anchor}-{lag} on {intervals}",
            )

    def test_add_working_agrees_with_consume_from_a_working_start(self):
        for c, intervals, anchor in self._cases():
            if not contains_coordinate(anchor, intervals):
                continue
            duration = self.rng.randint(0, 40)
            self.assertEqual(
                add_working(c, anchor, duration),
                consume_duration(anchor, duration, intervals),
            )

    def test_next_and_prev_agree_with_containment(self):
        for c, intervals, anchor in self._cases():
            nxt = next_working(c, anchor)
            if nxt is not None:
                self.assertTrue(contains_coordinate(nxt, intervals))
                self.assertGreaterEqual(nxt, anchor)
                for probe in range(max(anchor, 0), nxt):
                    self.assertFalse(contains_coordinate(probe, intervals))
            prv = prev_working(c, anchor)
            if prv is not None:
                self.assertLessEqual(prv, anchor)
                self.assertTrue(
                    contains_coordinate(prv - 1, intervals), f"prev {prv} on {intervals}"
                )

    def test_working_between_agrees_with_productive_segments(self):
        for c, intervals, anchor in self._cases():
            other = anchor + self.rng.randint(0, 60)
            expected = sum(f - s for s, f in productive_segments(anchor, other, intervals))
            self.assertEqual(working_between(c, anchor, other), expected)

    def test_earliest_span_agrees_with_the_scan(self):
        for c, intervals, anchor in self._cases():
            horizon = intervals[-1][1] + 5
            start_lb = anchor
            finish_lb = anchor + self.rng.randint(-5, 30)
            duration = self.rng.randint(0, 25)
            self.assertEqual(
                earliest_span(c, start_lb, finish_lb, duration, horizon),
                _reference_earliest_span(start_lb, finish_lb, duration, intervals, horizon),
                f"span lb={start_lb} flb={finish_lb} d={duration} h={horizon} on {intervals}",
            )


if __name__ == "__main__":
    unittest.main()
