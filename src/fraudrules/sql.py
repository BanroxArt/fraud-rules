"""Compile rules to SQL.

The generated SQL is written for DuckDB and kept to a subset that every common
warehouse accepts unchanged or after a mechanical rewrite: inner joins, ``CASE``,
``COALESCE``, ``COUNT(DISTINCT ...)``, integer arithmetic on ``ts`` and amounts.
No window frames, no interval literals, no dialect functions. Other dialects are
produced with sqlglot (``pip install 'fraudrules[sql]'``).

Each rule becomes one ``SELECT`` returning ``rule_id``, ``anchor_table`` and
``anchor_id``. :func:`compile_pack` joins them with ``UNION ALL``.

Windows are self-joins on the key with ``b.ts > a.ts - W AND b.ts <= a.ts``.
That is quadratic in the number of rows per key inside a window, which is fine
for per-account and per-customer keys and is what makes the result identical to
the Python evaluator. For keys with very large groups (a shared device id at a
large fintech) put a cap on group size upstream.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from . import model as m

DIALECTS = ("duckdb", "postgres", "snowflake", "bigquery")

_SQL_OP = {"eq": "=", "ne": "<>", "lt": "<", "lte": "<=", "gt": ">", "gte": ">="}


def lit(v: m.Scalar) -> str:
    if isinstance(v, bool):
        raise TypeError("booleans are not valid literals here")
    if isinstance(v, int):
        return str(v)
    return "'" + v.replace("'", "''") + "'"


def pred_sql(p: m.Pred, alias: str) -> str:
    if isinstance(p, m.TrueP):
        return "1 = 1"
    if isinstance(p, m.All):
        return "(" + " AND ".join(pred_sql(x, alias) for x in p.items) + ")"
    if isinstance(p, m.AnyOf):
        return "(" + " OR ".join(pred_sql(x, alias) for x in p.items) + ")"
    if isinstance(p, m.Not):
        return f"NOT COALESCE({pred_sql(p.item, alias)}, FALSE)"
    col = f"{alias}.{p.field}"
    if p.op == "is_null":
        return f"{col} IS NULL"
    if p.op == "not_null":
        return f"{col} IS NOT NULL"
    if p.op in ("in", "not_in"):
        assert isinstance(p.value, tuple)
        items = ", ".join(lit(v) for v in p.value)
        return f"{col} {'IN' if p.op == 'in' else 'NOT IN'} ({items})"
    op = _SQL_OP[p.op]
    if isinstance(p.value, m.FieldRef):
        ref = f"{alias}.{p.value.field}"
        if p.value.plus > 0:
            ref = f"({ref} + {p.value.plus})"
        elif p.value.plus < 0:
            ref = f"({ref} - {-p.value.plus})"
        return f"{col} {op} {ref}"
    assert p.value is not None and not isinstance(p.value, tuple)
    return f"{col} {op} {lit(p.value)}"


def _measure_sql(ms: m.Measure, alias: str) -> str:
    cond = None if isinstance(ms.where, m.TrueP) else pred_sql(ms.where, alias)
    if ms.fn == "count":
        return "COUNT(*)" if cond is None else f"COUNT(CASE WHEN {cond} THEN 1 END)"
    col = f"{alias}.{ms.field}"
    val = col if cond is None else f"CASE WHEN {cond} THEN {col} END"
    if ms.fn == "count_distinct":
        return f"COUNT(DISTINCT {val})"
    return f"{ms.fn.upper()}({val})"


def _term_sql(t: m.Term, measures: Mapping[str, m.Measure]) -> str:
    if t.kind == "const":
        return lit(t.const * t.times)
    base = _measure_sql(measures[t.ref], "b") if t.kind == "measure" else f"MAX(a.{t.ref})"
    return base if t.times == 1 else f"{base} * {t.times}"


def _having_sql(h: m.Having, measures: Mapping[str, m.Measure]) -> str:
    if isinstance(h, m.HAll):
        return "(" + " AND ".join(_having_sql(x, measures) for x in h.items) + ")"
    if isinstance(h, m.HAny):
        return "(" + " OR ".join(_having_sql(x, measures) for x in h.items) + ")"
    if isinstance(h, m.HNot):
        return f"NOT COALESCE({_having_sql(h.item, measures)}, FALSE)"
    left = _term_sql(h.left, measures)
    right = _term_sql(h.right, measures)
    return f"{left} {_SQL_OP[h.op]} {right}"


def _head(rule: m.Rule, alias: str, distinct: bool = False) -> str:
    d = "DISTINCT " if distinct else ""
    return (
        f"SELECT {d}{lit(rule.id)} AS rule_id, {lit(rule.table)} AS anchor_table, "
        f"{alias}.id AS anchor_id"
    )


def compile_rule(rule: m.Rule, tables: Mapping[str, str] | None = None) -> str:
    """One ``SELECT`` for ``rule``. ``tables`` maps canonical table names to the
    names (qualified if needed) of your views."""
    names = dict(tables or {})

    def tn(t: str) -> str:
        return names.get(t, t)

    lg = rule.logic
    if isinstance(lg, m.Filter):
        return f"{_head(rule, 'a')}\nFROM {tn(lg.table)} AS a\nWHERE {pred_sql(lg.where, 'a')}"
    if isinstance(lg, m.Aggregate):
        on = [f"b.{k} = a.{k}" for k in lg.key] + ["b.ts <= a.ts"]
        if lg.window is not None:
            on.append(f"b.ts > a.ts - {lg.window}")
        where = [pred_sql(lg.anchor, "a"), pred_sql(lg.members, "b")]
        measures = {ms.name: ms for ms in lg.measures}
        return (
            f"{_head(rule, 'a')}\n"
            f"FROM {tn(lg.table)} AS a\n"
            f"JOIN {tn(lg.table)} AS b ON {' AND '.join(on)}\n"
            f"WHERE {' AND '.join(where)}\n"
            f"GROUP BY a.id\n"
            f"HAVING {_having_sql(lg.having, measures)}"
        )
    n = len(lg.steps) - 1
    anchor = f"s{n}"
    lines = [_head(rule, anchor, distinct=True), f"FROM {tn(lg.steps[n].table)} AS {anchor}"]
    for i in range(n - 1, -1, -1):
        s = f"s{i}"
        nxt = f"s{i + 1}"
        on = [f"{s}.{k} = {anchor}.{k}" for k in lg.key]
        on.append(f"{s}.ts < {nxt}.ts")
        if i == 0:
            on.append(f"{s}.ts > {anchor}.ts - {lg.within}")
        on.extend(f"{s}.{mt.field} = {anchor}.{mt.anchor_field}" for mt in lg.match if mt.step == i)
        on.append(pred_sql(lg.steps[i].where, s))
        lines.append(f"JOIN {tn(lg.steps[i].table)} AS {s} ON {' AND '.join(on)}")
    lines.append(f"WHERE {pred_sql(lg.steps[n].where, anchor)}")
    return "\n".join(lines)


def compile_pack(rules: Iterable[m.Rule], tables: Mapping[str, str] | None = None) -> str:
    parts = [f"-- {r.id} {r.name}\n{compile_rule(r, tables)}" for r in rules]
    return "\nUNION ALL\n".join(parts)


def transpile(sql: str, dialect: str) -> str:
    """Rewrite DuckDB SQL for another dialect with sqlglot."""
    if dialect == "duckdb":
        return sql
    if dialect not in DIALECTS:
        raise ValueError(f"unknown dialect {dialect!r}; choose from {DIALECTS}")
    import sqlglot

    out = sqlglot.transpile(sql, read="duckdb", write=dialect, pretty=True)
    return ";\n".join(out)
