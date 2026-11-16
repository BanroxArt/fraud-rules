"""Hypothesis strategies that generate small tables aimed at one rule's edges.

Values are drawn from the constants the rule actually uses, one either side of
each, and timestamps from multiples of half the rule's window plus or minus one
second, so the generated data keeps landing on the boundaries where backends
could disagree: inclusive versus exclusive comparisons, window edges, nulls.
"""

from __future__ import annotations

from collections import defaultdict

from hypothesis import strategies as st

from fraudrules import model as m
from fraudrules.schema import TABLES

T = 1_800_000_000
GENERIC_INT = (0, 1, 2, 3, 100_000, 250_000, 1_000_000)
GENERIC_STR = ("v1", "v2", "v3", "v4", "v5", "v6", "v7")


def _col_type(table: str, name: str) -> str:
    return next(c.type for c in TABLES[table] if c.name == name)


def _has(table: str, name: str) -> bool:
    return any(c.name == name for c in TABLES[table])


def _walk_pred(p: m.Pred, out: dict[str, set[int | str]], refs: dict[str, set[int]]) -> None:
    if isinstance(p, (m.All, m.AnyOf)):
        for x in p.items:
            _walk_pred(x, out, refs)
    elif isinstance(p, m.Not):
        _walk_pred(p.item, out, refs)
    elif isinstance(p, m.Cmp):
        v = p.value
        if isinstance(v, m.FieldRef):
            refs[v.field].add(v.plus)
        elif isinstance(v, tuple):
            out[p.field].update(v)
        elif v is not None:
            out[p.field].add(v)


def _preds(rule: m.Rule) -> list[tuple[str, m.Pred]]:
    lg = rule.logic
    if isinstance(lg, m.Filter):
        return [(lg.table, lg.where)]
    if isinstance(lg, m.Aggregate):
        return [(lg.table, lg.anchor), (lg.table, lg.members)] + [(lg.table, x.where) for x in lg.measures]
    return [(s.table, s.where) for s in lg.steps]


def _consts(h: m.Having, out: set[int]) -> None:
    if isinstance(h, (m.HAll, m.HAny)):
        for x in h.items:
            _consts(x, out)
    elif isinstance(h, m.HNot):
        _consts(h.item, out)
    else:
        for t in (h.left, h.right):
            if t.kind == "const":
                out.add(t.const * t.times)


def _span(rule: m.Rule) -> int:
    lg = rule.logic
    if isinstance(lg, m.Aggregate):
        return lg.window or 86_400
    if isinstance(lg, m.Sequence):
        return lg.within
    return 86_400


def tables_for(
    rule: m.Rule, max_rows: int = 24
) -> st.SearchStrategy[dict[str, list[dict[str, int | str | None]]]]:
    consts: dict[str, dict[str, set[int | str]]] = defaultdict(lambda: defaultdict(set))
    refs: dict[str, dict[str, set[int]]] = defaultdict(lambda: defaultdict(set))
    for table, p in _preds(rule):
        _walk_pred(p, consts[table], refs[table])
    having_consts: set[int] = set()
    if isinstance(rule.logic, m.Aggregate):
        _consts(rule.logic.having, having_consts)
    half = max(1, _span(rule) // 2)
    ts_values = sorted({T + k * half + d for k in range(4) for d in (-1, 0, 1)})
    keys = set(rule.logic.key) if not isinstance(rule.logic, m.Filter) else set()
    match_fields: set[str] = set()
    if isinstance(rule.logic, m.Sequence):
        for mt in rule.logic.match:
            match_fields |= {mt.field, mt.anchor_field}

    def column_strategy(
        table: str, name: str, typ: str, nullable: bool
    ) -> st.SearchStrategy[int | str | None]:
        base: st.SearchStrategy[int | str | None]
        if name == "ts":
            return st.sampled_from(ts_values)
        if name in keys:
            base = st.sampled_from(("k1", "k2")) if typ == "str" else st.sampled_from((1, 2))
        elif name in match_fields:
            base = st.sampled_from(("p1", "p2"))
        elif typ == "int":
            vals: set[int] = set(GENERIC_INT)
            for c in consts[table].get(name, set()) | having_consts:
                if isinstance(c, int):
                    vals |= {c - 1, c, c + 1, c // 2, c // 3}
            base = st.sampled_from(sorted(vals))
        else:
            svals = {c for c in consts[table].get(name, set()) if isinstance(c, str)}
            base = st.sampled_from(sorted(svals | {"v1"}) if svals else list(GENERIC_STR))
        if nullable:
            return st.one_of(base, base, base, base, base, st.none())
        return base

    def int_domain(table: str) -> list[int]:
        vals: set[int] = set(GENERIC_INT)
        for cs in consts[table].values():
            for c in cs:
                if isinstance(c, int):
                    vals |= {c - 1, c, c + 1, c // 2, c // 3}
        for c in having_consts:
            vals |= {c - 1, c, c + 1, c // 2, c // 3}
        return sorted(vals)

    def opened_ts(table: str, name: str) -> st.SearchStrategy[int | str | None] | None:
        # A column compared as ``ts OP name + plus``: put it where that comparison flips.
        for target, pluses in refs[table].items():
            if target == name:
                vals = sorted({v - p for v in ts_values for p in pluses})
                return st.sampled_from(vals)
        return None

    targets: dict[str, list[m.Pred]] = defaultdict(list)
    for table, p in _preds(rule):
        if not isinstance(p, m.TrueP):
            targets[table].append(p)

    def rows(table: str) -> st.SearchStrategy[list[dict[str, int | str | None]]]:
        cols = TABLES[table]
        fields = {}
        for c in cols:
            if c.name == "id":
                continue
            special = opened_ts(table, c.name)
            fields[c.name] = (
                special if special is not None else column_strategy(table, c.name, c.type, c.nullable)
            )
        plain = st.fixed_dictionaries(fields)
        aimed = [
            st.tuples(plain, satisfying(p, int_domain(table))).map(lambda ab: {**ab[0], **ab[1]})
            for p in targets[table]
        ]
        row = st.one_of(plain, *aimed, *aimed) if aimed else plain
        # A burst: rows aimed at the rule, on one key, packed inside one window.
        # Count and distinct-count thresholds are out of reach of uniform rows.
        tight = sorted({T + i * max(1, half // 4) for i in range(4)} | {T - 1, T + 1})
        pin = {k: ("k1" if _col_type(table, k) == "str" else 1) for k in keys if _has(table, k)}
        burst_row = (st.one_of(*aimed) if aimed else plain).flatmap(
            lambda r: st.sampled_from(tight).map(lambda ts: {**r, **pin, "ts": ts})
        )

        def with_ids(
            parts: tuple[list[dict[str, int | str | None]], list[dict[str, int | str | None]]],
        ) -> list[dict[str, int | str | None]]:
            rs = parts[0] + parts[1]
            return [{"id": f"{table[0]}{i}", **r} for i, r in enumerate(rs)]

        # Hypothesis keeps most lists short, and a rule that needs three distinct
        # senders plus a cash-out (MU-004) needs at least four rows on one key.
        # Half the time the burst is forced to that size so count thresholds are
        # reached in most runs rather than in a lucky few.
        n = max_rows // 2
        burst = st.one_of(
            st.lists(burst_row, max_size=n),
            st.lists(burst_row, min_size=min(5, n), max_size=n),
        )
        return st.tuples(st.lists(row, max_size=n), burst).map(with_ids)

    return st.fixed_dictionaries({t: rows(t) for t in rule.tables()})


def satisfying(p: m.Pred, ints: list[int]) -> st.SearchStrategy[dict[str, int | str | None]]:
    """Field values that make ``p`` true, most of the time.

    Constraints on the same field are intersected for ``All``; ``AnyOf`` picks a
    branch; ``Not`` and field-to-field comparisons are left to chance.
    """
    if isinstance(p, m.AnyOf):
        return st.one_of(*(satisfying(x, ints) for x in p.items))
    items = p.items if isinstance(p, m.All) else (p,)
    flat: list[m.Cmp] = []
    branches: list[m.Pred] = []
    for x in items:
        if isinstance(x, m.Cmp):
            flat.append(x)
        elif isinstance(x, (m.All, m.AnyOf)):
            branches.append(x)
    by_field: dict[str, list[m.Cmp]] = defaultdict(list)
    for c in flat:
        if not isinstance(c.value, m.FieldRef):
            by_field[c.field].append(c)
    parts: dict[str, st.SearchStrategy[int | str | None]] = {}
    for f, cs in by_field.items():
        choice = _field_values(cs, ints)
        if choice is not None:
            parts[f] = choice
    base = st.fixed_dictionaries(parts)
    for br in branches:
        base = st.tuples(base, satisfying(br, ints)).map(lambda ab: {**ab[0], **ab[1]})
    return base


def _field_values(cs: list[m.Cmp], ints: list[int]) -> st.SearchStrategy[int | str | None] | None:
    if any(c.op == "is_null" for c in cs):
        return st.just(None)
    allowed: set[int | str] | None = None
    excluded: set[int | str] = set()
    lo, hi = -(10**18), 10**18
    for c in cs:
        v = c.value
        if c.op == "eq" and not isinstance(v, (tuple, m.FieldRef)) and v is not None:
            allowed = {v} if allowed is None else allowed & {v}
        elif c.op == "in" and isinstance(v, tuple):
            allowed = set(v) if allowed is None else allowed & set(v)
        elif c.op == "ne" and isinstance(v, (int, str)):
            excluded.add(v)
        elif c.op == "not_in" and isinstance(v, tuple):
            excluded |= set(v)
        elif isinstance(v, int):
            if c.op == "gt":
                lo = max(lo, v + 1)
            elif c.op == "gte":
                lo = max(lo, v)
            elif c.op == "lt":
                hi = min(hi, v - 1)
            elif c.op == "lte":
                hi = min(hi, v)
    if allowed is not None:
        vals = sorted((x for x in allowed if x not in excluded), key=str)
        return st.sampled_from(vals) if vals else None
    if lo > -(10**18) or hi < 10**18:
        cand = sorted(
            {x for x in ints if lo <= x <= hi}
            | ({lo} if lo > -(10**18) else set())
            | ({hi} if hi < 10**18 else set())
        )
        cand = [x for x in cand if lo <= x <= hi and x not in excluded]
        return st.sampled_from(cand) if cand else None
    if excluded:
        return st.sampled_from(["v1", "v2"])
    return None
