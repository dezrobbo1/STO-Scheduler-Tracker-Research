"""What a summary row's dates are: its children's, and nothing of its own.

A summary task carries a duration in the file and it means nothing. Microsoft
Project derives the span from what sits beneath it, which is why
:data:`~sto.core.engine.plan.SCHEDULED_KINDS` leaves summaries, levels of
effort and hammocks out of the network entirely: an activity whose dates come
from other activities is not a thing the critical path method places.

So the rollup is not a third traversal. It is arithmetic over a result the
passes have already produced -- the same shape as
:mod:`sto.core.engine.criticality`, which is float over two passes rather than
a pass of its own.

**The rule is the obvious one, and it is measured.** A summary spans from the
earliest start beneath it to the latest finish beneath it. On the
un-progressed BOILER snapshot that reproduces the dates Project stored for
seventy-five of the ninety-four summaries with children, and every one of the
nineteen that differ has a leaf beneath it whose own dates differ -- not one
summary is wrong while everything under it is right. So the rule is not
approximate: it is exact wherever the pass beneath it is, and the residue is
the forward pass's, already recorded in ADR-010.

This module takes plain data -- a tree of identifiers and a mapping of spans --
for the same reason the network does: the corpus declares its cases in hours,
the real files arrive in seconds from an epoch, and arithmetic that never sees
a date works for both.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

__all__ = ["ROLLUP_PROFILE", "RolledUp", "Rollup", "roll_up"]

#: Named on the result so a stored answer says which rule produced it.
ROLLUP_PROFILE = "sto-rollup-v1"


@dataclass(frozen=True, slots=True)
class RolledUp:
    """One summary's span, and how much sits beneath it."""

    uid: UUID
    start: int
    finish: int
    #: Leaves anywhere beneath this node that the passes placed. A summary of
    #: summaries reports everything under it, not the count of its children.
    placed: int


@dataclass(frozen=True, slots=True)
class Rollup:
    """Every summary that has something beneath it, and every summary that does not."""

    spans: tuple[RolledUp, ...] = ()
    #: Nodes with no placed leaf anywhere beneath them: empty in the file, or
    #: holding only rows the plan excluded. They get no span rather than a
    #: guessed one, and they are named so that a shrinking cohort is visible
    #: instead of looking like a tree with fewer branches.
    empty: tuple[UUID, ...] = ()
    #: Nodes the hierarchy makes unanswerable: those on a cycle, and those
    #: whose subtree reaches one. A cycle has no deepest node, so there is no
    #: rollup to compute; naming them is the answer.
    cyclic: tuple[UUID, ...] = ()

    def by_uid(self) -> dict[UUID, RolledUp]:
        return {row.uid: row for row in self.spans}


def roll_up(
    children: dict[UUID, tuple[UUID, ...]],
    spans: dict[UUID, tuple[int, int]],
) -> Rollup:
    """Roll ``spans`` up a tree of ``children``, deepest first.

    ``children`` maps every node to the identifiers beneath it, whether those
    are other nodes or placed rows; ``spans`` holds the placed rows. A node
    named by neither is a leaf that was not placed -- an excluded row -- and
    contributes nothing, which is what makes a summary of nothing but excluded
    work come back empty rather than come back wrong.

    Deterministic: nodes are answered in the order ``children`` presents them,
    each is answered once however many parents reach it, and a hierarchy that
    contains a cycle produces the same report whichever node is reached first.
    """

    answered: dict[UUID, tuple[int, int] | None] = {}
    #: The placed leaves under each node, by identity rather than by count.
    #: A hierarchy where two parents reach one subtree is supported, and adding
    #: their counts at a shared ancestor counted the same leaf once per path --
    #: a branch with one leaf beneath it reporting two.
    leaves: dict[UUID, frozenset[UUID]] = {}
    cyclic: set[UUID] = set()
    stack: list[UUID] = []
    on_stack: set[UUID] = set()

    def resolve(uid: UUID) -> tuple[int, int] | None:
        if uid in answered:
            return answered[uid]
        if uid in on_stack:
            # Every node from the first sighting to here is on the cycle.
            # Marking the node and returning nothing -- the earlier shape --
            # stopped the recursion but made the answer depend on which node
            # the traversal reached first: whichever resolved first spanned
            # both subtrees and the other spanned only its own, and reversing
            # the mapping swapped them. A cycle has no deepest node, so there
            # is nothing to roll up and the honest answer is to say so.
            cyclic.update(stack[stack.index(uid):])
            return None
        placed = spans.get(uid)
        if placed is not None and uid not in children:
            leaves[uid] = frozenset({uid})
            answered[uid] = placed
            return placed
        stack.append(uid)
        on_stack.add(uid)
        starts: list[int] = []
        finishes: list[int] = []
        found: set[UUID] = set()
        poisoned = False
        for child in children.get(uid, ()):
            child_span = resolve(child)
            if child in cyclic:
                poisoned = True
            if child_span is None:
                continue
            starts.append(child_span[0])
            finishes.append(child_span[1])
            found |= leaves.get(child, frozenset())
        stack.pop()
        on_stack.discard(uid)
        if poisoned:
            # A subtree that reaches a cycle cannot be summed, so an ancestor
            # of one is not given a span built from whatever else it happened
            # to reach.
            cyclic.add(uid)
        if poisoned or not starts:
            answered[uid] = None
            leaves[uid] = frozenset()
            return None
        answered[uid] = (min(starts), max(finishes))
        leaves[uid] = frozenset(found)
        return answered[uid]

    rolled: list[RolledUp] = []
    empty: list[UUID] = []
    for uid in children:
        span = resolve(uid)
        if uid in cyclic:
            continue
        if span is None:
            empty.append(uid)
        else:
            rolled.append(RolledUp(uid, span[0], span[1], len(leaves[uid])))
    # Sorted so a cycle reported from two entry points reads the same either
    # way; everything else here is already order-independent.
    return Rollup(
        spans=tuple(rolled),
        empty=tuple(empty),
        cyclic=tuple(sorted(cyclic, key=str)),
    )
