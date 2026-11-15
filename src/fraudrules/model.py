"""The compiled form of a rule: a small, closed AST every backend walks.

Three rule kinds cover the pack:

``filter``
    A predicate on one row. The row is the hit.

``aggregate``
    For each *anchor* row, the *member* rows with the same key whose ``ts`` lies
    in ``(anchor.ts - window, anchor.ts]`` are aggregated, and the anchor is a hit
    when ``having`` holds. Without a window the lower bound is open, which gives a
    point-in-time "everything seen so far" count. An anchor with no members is
    never a hit, so ``having`` cannot express absence.

``sequence``
    The last step is the anchor. It is a hit when, for every earlier step, a row
    with the same key matches that step, the rows are in strictly increasing
    ``ts`` in step order, and the first one is inside ``(anchor.ts - within,
    anchor.ts)``. Optional ``match`` pins a field of an earlier step to a field of
    the anchor (the payee that was changed is the payee that got paid).

Comparisons involving a null are false, on every backend. ``not`` is two-valued:
it is true exactly when its operand is not true, so ``not (x = 'a')`` holds for a
null ``x`` while ``x != 'a'`` does not. SQL output wraps negated operands in
``COALESCE(..., FALSE)`` to get that behaviour.
"""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field as dc_field
from typing import Literal

Scalar = int | str
CmpOp = Literal["eq", "ne", "lt", "lte", "gt", "gte", "in", "not_in", "is_null", "not_null"]
CMP_OPS: tuple[CmpOp, ...] = (
    "eq",
    "ne",
    "lt",
    "lte",
    "gt",
    "gte",
    "in",
    "not_in",
    "is_null",
    "not_null",
)
ORDER_OPS = ("lt", "lte", "gt", "gte")
HavingOp = Literal["eq", "ne", "lt", "lte", "gt", "gte"]
HAVING_OPS: tuple[HavingOp, ...] = ("eq", "ne", "lt", "lte", "gt", "gte")
AggFn = Literal["count", "sum", "count_distinct", "min", "max"]


@dataclass(frozen=True)
class FieldRef:
    """Another column of the same row, plus a constant: ``ts < account_opened_ts + 90d``."""

    field: str
    plus: int = 0


@dataclass(frozen=True)
class Cmp:
    field: str
    op: CmpOp
    value: Scalar | FieldRef | tuple[Scalar, ...] | None = None


@dataclass(frozen=True)
class All:
    items: tuple[Pred, ...]


@dataclass(frozen=True)
class AnyOf:
    items: tuple[Pred, ...]


@dataclass(frozen=True)
class Not:
    item: Pred


@dataclass(frozen=True)
class TrueP:
    pass


Pred = Cmp | All | AnyOf | Not | TrueP


@dataclass(frozen=True)
class Measure:
    name: str
    fn: AggFn
    field: str | None = None
    where: Pred = dc_field(default_factory=TrueP)


@dataclass(frozen=True)
class Term:
    """``kind`` is measure, anchor or const; the value is multiplied by ``times``."""

    kind: Literal["measure", "anchor", "const"]
    ref: str = ""
    const: int = 0
    times: int = 1


@dataclass(frozen=True)
class HCmp:
    left: Term
    op: HavingOp
    right: Term


@dataclass(frozen=True)
class HAll:
    items: tuple[Having, ...]


@dataclass(frozen=True)
class HAny:
    items: tuple[Having, ...]


@dataclass(frozen=True)
class HNot:
    item: Having


Having = HCmp | HAll | HAny | HNot


@dataclass(frozen=True)
class Filter:
    table: str
    where: Pred


@dataclass(frozen=True)
class Aggregate:
    table: str
    key: tuple[str, ...]
    window: int | None
    anchor: Pred
    members: Pred
    measures: tuple[Measure, ...]
    having: Having


@dataclass(frozen=True)
class Step:
    table: str
    where: Pred


@dataclass(frozen=True)
class Match:
    step: int
    field: str
    anchor_field: str


@dataclass(frozen=True)
class Sequence:
    key: tuple[str, ...]
    within: int
    steps: tuple[Step, ...]
    match: tuple[Match, ...] = ()

    @property
    def table(self) -> str:
        return self.steps[-1].table


Logic = Filter | Aggregate | Sequence


@dataclass(frozen=True)
class Source:
    title: str
    url: str
    publisher: str
    note: str = ""


@dataclass(frozen=True)
class Knob:
    param: str
    effect: str


@dataclass(frozen=True)
class Rule:
    id: str
    name: str
    title: str
    category: str
    severity: str
    status: str
    summary: str
    rationale: str
    sources: tuple[Source, ...]
    false_positives: tuple[str, ...]
    tuning: tuple[Knob, ...]
    params: dict[str, Scalar]
    logic: Logic
    path: str = ""

    @property
    def table(self) -> str:
        return self.logic.table

    @property
    def kind(self) -> str:
        return type(self.logic).__name__.lower()

    def tables(self) -> tuple[str, ...]:
        if isinstance(self.logic, Sequence):
            return tuple(dict.fromkeys(s.table for s in self.logic.steps))
        return (self.logic.table,)
