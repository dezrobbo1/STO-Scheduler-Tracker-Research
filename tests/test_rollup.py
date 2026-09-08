"""A summary's dates are its children's (slice S6).

The rule is arithmetic over a result the passes have already produced, so
these tests are mostly about the shapes a real hierarchy takes -- nesting,
a summary of summaries, a branch holding nothing the plan would schedule --
rather than about scheduling. The measurement against the real files lives in
``tests/test_rollup_boiler.py``.
"""

from __future__ import annotations

import unittest
from uuid import NAMESPACE_URL, UUID, uuid5

from sto.core.engine import roll_up


def uid(name: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"sto-rollup/{name}")


class RollupTests(unittest.TestCase):
    def test_a_summary_spans_its_children(self):
        rolled = roll_up(
            {uid("s"): (uid("a"), uid("b"))},
            {uid("a"): (10, 20), uid("b"): (5, 15)},
        ).by_uid()
        self.assertEqual((rolled[uid("s")].start, rolled[uid("s")].finish), (5, 20))
        self.assertEqual(rolled[uid("s")].placed, 2)

    def test_and_a_summary_of_summaries_spans_everything_beneath_it(self):
        rolled = roll_up(
            {
                uid("root"): (uid("left"), uid("right")),
                uid("left"): (uid("a"), uid("b")),
                uid("right"): (uid("c"),),
            },
            {uid("a"): (10, 20), uid("b"): (5, 15), uid("c"): (30, 40)},
        ).by_uid()
        self.assertEqual((rolled[uid("root")].start, rolled[uid("root")].finish), (5, 40))
        self.assertEqual(rolled[uid("root")].placed, 3)
        self.assertEqual((rolled[uid("left")].start, rolled[uid("left")].finish), (5, 20))

    def test_a_branch_with_nothing_placed_beneath_it_gets_no_span(self):
        """Not a guessed one: a summary of excluded work has no dates to give."""

        result = roll_up(
            {uid("s"): (uid("excluded"),), uid("t"): (uid("a"),)},
            {uid("a"): (1, 2)},
        )
        self.assertEqual(result.empty, (uid("s"),))
        self.assertEqual([row.uid for row in result.spans], [uid("t")])

    def test_an_empty_branch_does_not_empty_its_parent(self):
        result = roll_up(
            {
                uid("root"): (uid("empty"), uid("full")),
                uid("empty"): (uid("excluded"),),
                uid("full"): (uid("a"),),
            },
            {uid("a"): (7, 9)},
        )
        rolled = result.by_uid()
        self.assertEqual((rolled[uid("root")].start, rolled[uid("root")].finish), (7, 9))
        self.assertEqual(result.empty, (uid("empty"),))

    def test_a_milestone_beneath_a_summary_is_a_coordinate_not_a_span(self):
        rolled = roll_up(
            {uid("s"): (uid("m"), uid("a"))},
            {uid("m"): (50, 50), uid("a"): (10, 20)},
        ).by_uid()
        self.assertEqual((rolled[uid("s")].start, rolled[uid("s")].finish), (10, 50))

    def test_a_node_reached_from_two_parents_is_answered_once(self):
        rolled = roll_up(
            {
                uid("one"): (uid("shared"),),
                uid("two"): (uid("shared"),),
                uid("shared"): (uid("a"),),
            },
            {uid("a"): (3, 4)},
        ).by_uid()
        self.assertEqual(rolled[uid("one")].placed, 1)
        self.assertEqual(rolled[uid("two")].placed, 1)

    def test_a_hierarchy_that_contains_itself_is_reported_not_answered(self):
        """A cycle is a defect in the source hierarchy, not an answer to give.

        Stopping the recursion is not enough. Whichever node the traversal
        reached first spanned the whole cycle's leaves and the other spanned
        only its own, so the same hierarchy gave two different answers
        depending on the order of a mapping.
        """

        children = {uid("a"): (uid("b"),), uid("b"): (uid("a"), uid("leaf"))}
        rollup = roll_up(children, {uid("leaf"): (1, 2)})
        self.assertEqual(sorted(rollup.cyclic, key=str), sorted([uid("a"), uid("b")], key=str))
        self.assertEqual(rollup.by_uid(), {})
        self.assertEqual(rollup.empty, ())

    def test_a_cycle_reads_the_same_from_either_end(self):
        forwards = roll_up(
            {uid("a"): (uid("b"), uid("x")), uid("b"): (uid("a"), uid("y"))},
            {uid("x"): (1, 2), uid("y"): (5, 6)},
        )
        backwards = roll_up(
            {uid("b"): (uid("a"), uid("y")), uid("a"): (uid("b"), uid("x"))},
            {uid("x"): (1, 2), uid("y"): (5, 6)},
        )
        self.assertEqual(forwards.cyclic, backwards.cyclic)
        self.assertEqual(forwards.by_uid(), backwards.by_uid())

    def test_a_branch_above_a_cycle_is_not_given_what_it_could_reach(self):
        rollup = roll_up(
            {
                uid("root"): (uid("sound"), uid("a")),
                uid("a"): (uid("b"),),
                uid("b"): (uid("a"),),
                uid("sound"): (uid("leaf"),),
            },
            {uid("leaf"): (1, 2)},
        )
        self.assertIn(uid("root"), rollup.cyclic)
        self.assertEqual(
            [row.uid for row in rollup.spans], [uid("sound")], "only the sound branch answers"
        )

    def test_the_answer_does_not_depend_on_the_order_the_tree_is_walked(self):
        children = {
            uid("root"): (uid("left"), uid("right")),
            uid("left"): (uid("a"),),
            uid("right"): (uid("b"),),
        }
        spans = {uid("a"): (10, 20), uid("b"): (5, 30)}
        forwards = roll_up(children, spans).by_uid()[uid("root")]
        backwards = roll_up(dict(reversed(list(children.items()))), spans).by_uid()[uid("root")]
        self.assertEqual((forwards.start, forwards.finish), (backwards.start, backwards.finish))


if __name__ == "__main__":
    unittest.main()
