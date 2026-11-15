"""A small reference interpreter for the Sigma subset that :mod:`fraudrules.sigma`
emits.

It exists so the tests can run the *emitted YAML* and compare the result with the
SQL and Python backends, instead of trusting the emitter. It implements:

- detections made of named selections, each a map (fields ANDed) or a list of
  maps (ORed); list values are ORed; ``null`` matches a missing value; the
  ``lt``, ``lte``, ``gt`` and ``gte`` modifiers; case-insensitive string equality;
- conditions built from selection names, ``and``, ``or``, ``not`` and brackets;
- ``event_count``, ``value_count`` and ``temporal_ordered`` correlations.

Sigma leaves the output of a correlation to the backend. Here a correlation
reports the event at which its condition holds over the trailing ``timespan``,
which is the same anchor the SQL and Python backends report.
"""

from __future__ import annotations

import bisect
import re
from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from typing import Any

import yaml

from .pyeval import Row

_SPAN = re.compile(r"^(\d+)([smhd])$")
_UNIT = {"s": 1, "m": 60, "h": 3600, "d": 86400}
_TOKEN = re.compile(r"\s*(\(|\)|[A-Za-z_][A-Za-z0-9_]*)")


def parse(text: str) -> list[dict[str, Any]]:
    return [d for d in yaml.safe_load_all(text) if d]


def _span(s: str) -> int:
    mt = _SPAN.match(s)
    if not mt:
        raise ValueError(f"bad timespan {s!r}")
    return int(mt.group(1)) * _UNIT[mt.group(2)]


def _value_eq(have: object, want: object) -> bool:
    if want is None:
        return have is None
    if have is None:
        return False
    if isinstance(want, str) and isinstance(have, str):
        return have.lower() == want.lower()
    if isinstance(want, bool) or isinstance(have, bool):
        return False
    return have == want


def _entry(row: Row, key: str, want: Any) -> bool:
    field, _, mod = key.partition("|")
    have = row.get(field)
    if mod:
        if have is None or not isinstance(have, int) or not isinstance(want, int):
            return False
        return {
            "lt": have < want,
            "lte": have <= want,
            "gt": have > want,
            "gte": have >= want,
        }[mod]
    if isinstance(want, list):
        return any(_value_eq(have, w) for w in want)
    return _value_eq(have, want)


def _selection(row: Row, sel: Any) -> bool:
    if isinstance(sel, list):
        return any(_selection(row, s) for s in sel)
    return all(_entry(row, k, v) for k, v in sel.items())


def _condition(expr: str) -> Callable[[Mapping[str, bool]], bool]:
    tokens: list[str] = _TOKEN.findall(expr)
    if "".join(tokens).replace(" ", "") != expr.replace(" ", ""):
        raise ValueError(f"unsupported condition {expr!r}")
    pos = 0

    def peek() -> str | None:
        return tokens[pos] if pos < len(tokens) else None

    def take() -> str:
        nonlocal pos
        tok = tokens[pos]
        pos += 1
        return tok

    Node = Callable[[Mapping[str, bool]], bool]

    def or_() -> Node:
        left = and_()
        while peek() == "or":
            take()
            right = and_()
            left = (lambda a, b: lambda e: a(e) or b(e))(left, right)
        return left

    def and_() -> Node:
        left = not_()
        while peek() == "and":
            take()
            right = not_()
            left = (lambda a, b: lambda e: a(e) and b(e))(left, right)
        return left

    def not_() -> Node:
        if peek() == "not":
            take()
            inner = not_()
            return lambda e: not inner(e)
        return atom()

    def atom() -> Node:
        tok = take()
        if tok == "(":
            inner = or_()
            if take() != ")":
                raise ValueError(f"unbalanced brackets in {expr!r}")
            return inner
        name = tok
        return lambda e: e[name]

    node = or_()
    if pos != len(tokens):
        raise ValueError(f"trailing tokens in {expr!r}")
    return node


def matcher(doc: Mapping[str, Any]) -> Callable[[Row], bool]:
    det = dict(doc["detection"])
    cond = _condition(det.pop("condition"))

    def match(row: Row) -> bool:
        return cond({name: _selection(row, sel) for name, sel in det.items()})

    return match


def _key(row: Row, group_by: Sequence[str]) -> tuple[object, ...] | None:
    k = tuple(row.get(g) for g in group_by)
    return None if any(v is None for v in k) else k


def _ts(r: Row) -> int:
    t = r["ts"]
    assert isinstance(t, int)
    return t


def evaluate(docs: Sequence[Mapping[str, Any]], events: Sequence[Row]) -> set[str]:
    """Ids of the events the outermost document of ``docs`` reports."""
    by_name = {d["name"]: d for d in docs if "name" in d}
    top = docs[0]
    if "correlation" not in top:
        match = matcher(top)
        return {str(r["id"]) for r in events if match(r)}
    c = top["correlation"]
    group_by = c["group-by"]
    span = _span(c["timespan"])
    rules = [matcher(by_name[n]) for n in c["rules"]]
    hits: set[str] = set()
    if c["type"] in ("event_count", "value_count"):
        (match,) = rules
        cond = dict(c["condition"])
        field = cond.pop("field", None)
        ((op, limit),) = cond.items()
        groups: dict[tuple[object, ...], list[Row]] = defaultdict(list)
        for r in events:
            k = _key(r, group_by)
            if k is not None and match(r):
                groups[k].append(r)
        for rows in groups.values():
            rows.sort(key=_ts)
            times = [_ts(r) for r in rows]
            for r in rows:
                t = _ts(r)
                window = rows[bisect.bisect_right(times, t - span) : bisect.bisect_right(times, t)]
                if field is None:
                    n = len(window)
                else:
                    n = len({w.get(field) for w in window if w.get(field) is not None})
                ok = {
                    "gt": n > limit,
                    "gte": n >= limit,
                    "lt": n < limit,
                    "lte": n <= limit,
                    "eq": n == limit,
                    "neq": n != limit,
                }[op]
                if ok:
                    hits.add(str(r["id"]))
        return hits
    if c["type"] != "temporal_ordered":
        raise ValueError(f"unsupported correlation type {c['type']}")
    per_step: list[dict[tuple[object, ...], list[int]]] = []
    for match in rules[:-1]:
        g: dict[tuple[object, ...], list[int]] = defaultdict(list)
        for r in events:
            k = _key(r, group_by)
            if k is not None and match(r):
                g[k].append(_ts(r))
        for v in g.values():
            v.sort()
        per_step.append(g)
    for r in events:
        k = _key(r, group_by)
        if k is None or not rules[-1](r):
            continue
        t = _ts(r)
        prev = t - span
        ok = True
        for g in per_step:
            times = g.get(k, [])
            j = bisect.bisect_right(times, prev)
            if j >= len(times) or times[j] >= t:
                ok = False
                break
            prev = times[j]
        if ok:
            hits.add(str(r["id"]))
    return hits
