"""Reference evaluator in plain Python.

This is the executable definition of the semantics in :mod:`fraudrules.model`;
the SQL and Sigma outputs are tested against it. It is also usable on its own for
streams small enough to hold in memory (a day of one institution's events, a
replayed case file).

Rows are mappings from column name to ``int``, ``str`` or ``None``.
"""

from __future__ import annotations

import bisect
from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass

from . import model as m

Row = Mapping[str, int | str | None]
Tables = Mapping[str, Sequence[Row]]
RowPred = Callable[[Row], bool]


@dataclass(frozen=True, order=True)
class Hit:
    rule_id: str
    table: str
    row_id: str


def compile_pred(p: m.Pred) -> RowPred:
    if isinstance(p, m.TrueP):
        return lambda r: True
    if isinstance(p, m.All):
        parts = [compile_pred(x) for x in p.items]
        return lambda r: all(f(r) for f in parts)
    if isinstance(p, m.AnyOf):
        parts = [compile_pred(x) for x in p.items]
        return lambda r: any(f(r) for f in parts)
    if isinstance(p, m.Not):
        inner = compile_pred(p.item)
        return lambda r: not inner(r)
    return _cmp(p)


def _cmp(c: m.Cmp) -> RowPred:
    f, op, v = c.field, c.op, c.value
    if op == "is_null":
        return lambda r: r.get(f) is None
    if op == "not_null":
        return lambda r: r.get(f) is not None
    if op in ("in", "not_in"):
        assert isinstance(v, tuple)
        vals = frozenset(v)
        if op == "in":
            return lambda r: (x := r.get(f)) is not None and x in vals
        return lambda r: (x := r.get(f)) is not None and x not in vals
    test = _OPS[op]
    if isinstance(v, m.FieldRef):
        other, plus = v.field, v.plus

        def ref(r: Row) -> bool:
            x, y = r.get(f), r.get(other)
            return isinstance(x, int) and isinstance(y, int) and test(x, y + plus)

        return ref
    assert v is not None and not isinstance(v, tuple)
    const = v
    return lambda r: (x := r.get(f)) is not None and test(x, const)


def _eq(a: object, b: object) -> bool:
    return a == b


def _ne(a: object, b: object) -> bool:
    return a != b


def _lt(a: object, b: object) -> bool:
    return a < b  # type: ignore[operator, no-any-return]


def _le(a: object, b: object) -> bool:
    return a <= b  # type: ignore[operator, no-any-return]


def _gt(a: object, b: object) -> bool:
    return a > b  # type: ignore[operator, no-any-return]


def _ge(a: object, b: object) -> bool:
    return a >= b  # type: ignore[operator, no-any-return]


_OPS: dict[str, Callable[[object, object], bool]] = {
    "eq": _eq,
    "ne": _ne,
    "lt": _lt,
    "lte": _le,
    "gt": _gt,
    "gte": _ge,
}


def _key(r: Row, key: tuple[str, ...]) -> tuple[int | str, ...] | None:
    out = []
    for k in key:
        v = r.get(k)
        if v is None:
            return None
        out.append(v)
    return tuple(out)


def _ts(r: Row) -> int:
    t = r["ts"]
    assert isinstance(t, int), "ts must be an integer"
    return t


def _id(r: Row) -> str:
    return str(r["id"])


def evaluate(rule: m.Rule, tables: Tables) -> set[str]:
    """Ids of the anchor rows ``rule`` flags."""
    lg = rule.logic
    if isinstance(lg, m.Filter):
        p = compile_pred(lg.where)
        return {_id(r) for r in tables.get(lg.table, ()) if p(r)}
    if isinstance(lg, m.Aggregate):
        return _aggregate(lg, tables.get(lg.table, ()))
    return _sequence(lg, tables)


def run(rules: Iterable[m.Rule], tables: Tables) -> list[Hit]:
    out = []
    for rule in rules:
        out.extend(Hit(rule.id, rule.table, i) for i in evaluate(rule, tables))
    return sorted(out)


def _measure(ms: m.Measure, rows: list[Row], where: RowPred) -> int | None:
    sel = [r for r in rows if where(r)]
    if ms.fn == "count":
        return len(sel)
    assert ms.field is not None
    vals = [v for r in sel if (v := r.get(ms.field)) is not None]
    if ms.fn == "count_distinct":
        return len(set(vals))
    if not vals:
        return None
    ints = [v for v in vals if isinstance(v, int)]
    if ms.fn == "sum":
        return sum(ints)
    return min(ints) if ms.fn == "min" else max(ints)


def _term(t: m.Term, measures: Mapping[str, int | None], anchor: Row) -> int | None:
    if t.kind == "const":
        return t.const * t.times
    v = measures[t.ref] if t.kind == "measure" else anchor.get(t.ref)
    if v is None:
        return None
    assert isinstance(v, int)
    return v * t.times


def _having(h: m.Having, measures: Mapping[str, int | None], anchor: Row) -> bool:
    if isinstance(h, m.HAll):
        return all(_having(x, measures, anchor) for x in h.items)
    if isinstance(h, m.HAny):
        return any(_having(x, measures, anchor) for x in h.items)
    if isinstance(h, m.HNot):
        return not _having(h.item, measures, anchor)
    a = _term(h.left, measures, anchor)
    b = _term(h.right, measures, anchor)
    if a is None or b is None:
        return False
    return _OPS[h.op](a, b)


def _groups(
    rows: Iterable[Row], key: tuple[str, ...]
) -> dict[tuple[int | str, ...], tuple[list[int], list[Row]]]:
    g: dict[tuple[int | str, ...], list[Row]] = defaultdict(list)
    for r in rows:
        k = _key(r, key)
        if k is not None:
            g[k].append(r)
    out = {}
    for k, rs in g.items():
        rs.sort(key=_ts)
        out[k] = ([_ts(r) for r in rs], rs)
    return out


def _aggregate(lg: m.Aggregate, rows: Sequence[Row]) -> set[str]:
    anchor_p = compile_pred(lg.anchor)
    member_p = compile_pred(lg.members)
    wheres = {ms.name: compile_pred(ms.where) for ms in lg.measures}
    members = _groups((r for r in rows if member_p(r)), lg.key)
    hits = set()
    for a in rows:
        if not anchor_p(a):
            continue
        k = _key(a, lg.key)
        if k is None or k not in members:
            continue
        times, rs = members[k]
        t = _ts(a)
        hi = bisect.bisect_right(times, t)
        lo = 0 if lg.window is None else bisect.bisect_right(times, t - lg.window)
        window = rs[lo:hi]
        if not window:
            continue
        vals = {ms.name: _measure(ms, window, wheres[ms.name]) for ms in lg.measures}
        if _having(lg.having, vals, a):
            hits.add(_id(a))
    return hits


def _sequence(lg: m.Sequence, tables: Tables) -> set[str]:
    preds = [compile_pred(s.where) for s in lg.steps]
    step_groups = [
        _groups((r for r in tables.get(s.table, ()) if p(r)), lg.key)
        for s, p in zip(lg.steps[:-1], preds[:-1], strict=True)
    ]
    matches: dict[int, list[m.Match]] = defaultdict(list)
    for mt in lg.match:
        matches[mt.step].append(mt)
    hits = set()
    for a in tables.get(lg.steps[-1].table, ()):
        if not preds[-1](a):
            continue
        k = _key(a, lg.key)
        if k is None:
            continue
        t_a = _ts(a)
        prev = t_a - lg.within  # the next step must be strictly later than this
        ok = True
        for i, groups in enumerate(step_groups):
            if k not in groups:
                ok = False
                break
            times, rs = groups[k]
            j = bisect.bisect_right(times, prev)
            found = None
            while j < len(rs) and times[j] < t_a:
                r = rs[j]
                if all(
                    (v := r.get(mt.field)) is not None and v == a.get(mt.anchor_field)
                    for mt in matches[i]
                ):
                    found = times[j]
                    break
                j += 1
            if found is None:
                ok = False
                break
            prev = found
        if ok:
            hits.add(_id(a))
    return hits
