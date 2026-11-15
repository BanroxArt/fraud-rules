"""Emit Sigma rules for the log-shaped part of the pack.

Only rules that read the ``events`` table alone are emitted: digital-banking
logins, credential and contact changes, MFA prompts and payee maintenance are the
events a SIEM already collects. Transaction rules stay in SQL.

Mapping:

- ``filter`` becomes one Sigma rule.
- ``aggregate`` with a single ``count`` or ``count_distinct`` measure, the same
  predicate for anchors and members, and a ``having`` that compares that measure
  with a constant becomes an ``event_count`` or ``value_count`` correlation
  (Sigma correlation specification 2.x).
- ``sequence`` without ``match`` becomes a ``temporal_ordered`` correlation.

Predicates are rewritten to disjunctive normal form; each conjunct is one
``selection_N`` map plus an optional ``filter_N`` list for its negated literals.
``x != v`` is emitted as ``not (x: v or x: null)`` because Sigma's ``not`` is
true on a missing field and the pack's ``ne`` is not. Field-to-field comparisons
have no Sigma form; rules that use them raise :class:`NotExpressible`.

Sigma compares strings case-insensitively. The data model fixes every vocabulary
column to lower case, so on conforming data the two agree.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from typing import Any

import yaml

from . import model as m
from .loader import format_duration

_NS = uuid.UUID("6f1c2b8e-3d0a-5c4e-9b7f-2a1d0e8c4b6a")
LOGSOURCE = {"product": "fraudrules", "category": "events"}
_COND = {"eq": "eq", "ne": "neq", "lt": "lt", "lte": "lte", "gt": "gt", "gte": "gte"}
_MAX_CONJUNCTS = 16


class NotExpressible(ValueError):
    """The rule has no faithful Sigma form."""


Lit = tuple[bool, m.Cmp]


def _lower(p: m.Pred) -> m.Pred:
    """Rewrite ne, not_in and not_null in terms of eq, in and is_null."""
    if isinstance(p, m.All):
        return m.All(tuple(_lower(x) for x in p.items))
    if isinstance(p, m.AnyOf):
        return m.AnyOf(tuple(_lower(x) for x in p.items))
    if isinstance(p, m.Not):
        return m.Not(_lower(p.item))
    if isinstance(p, m.Cmp):
        if isinstance(p.value, m.FieldRef):
            raise NotExpressible(f"field comparison {p.field} vs {p.value.field}")
        null = m.Cmp(p.field, "is_null")
        if p.op == "not_null":
            return m.Not(null)
        if p.op == "ne":
            return m.All((m.Not(null), m.Not(m.Cmp(p.field, "eq", p.value))))
        if p.op == "not_in":
            return m.All((m.Not(null), m.Not(m.Cmp(p.field, "in", p.value))))
    return p


def _dnf(p: m.Pred, neg: bool = False) -> list[list[Lit]]:
    if isinstance(p, m.TrueP):
        if neg:
            raise NotExpressible("a predicate that is never true")
        return [[]]
    if isinstance(p, m.Not):
        return _dnf(p.item, not neg)
    if isinstance(p, m.Cmp):
        return [[(not neg, p)]]
    conj = isinstance(p, m.All) != neg
    parts = [_dnf(x, neg) for x in p.items]
    if not conj:
        return [c for part in parts for c in part]
    out: list[list[Lit]] = [[]]
    for part in parts:
        out = [a + b for a in out for b in part]
        if len(out) > _MAX_CONJUNCTS:
            raise NotExpressible("predicate expands to too many Sigma selections")
    return out


def _entry(c: m.Cmp) -> tuple[str, Any]:
    if c.op == "is_null":
        return c.field, None
    if c.op == "eq":
        return c.field, c.value
    if c.op == "in":
        assert isinstance(c.value, tuple)
        return c.field, list(c.value)
    return f"{c.field}|{c.op}", c.value


def detection(p: m.Pred) -> dict[str, Any]:
    conjuncts = _dnf(_lower(p))
    det: dict[str, Any] = {}
    terms = []
    for i, conj in enumerate(conjuncts, 1):
        sels: list[dict[str, Any]] = [{}]
        negs = []
        for pos, c in conj:
            k, v = _entry(c)
            if not pos:
                negs.append({k: v})
                continue
            for s in sels:
                if k not in s:
                    s[k] = v
                    break
            else:
                sels.append({k: v})
        names = []
        if sels[0]:
            for j, s in enumerate(sels):
                name = f"selection_{i}" + ("" if j == 0 else f"_{j}")
                det[name] = s
                names.append(name)
        if negs:
            det[f"filter_{i}"] = negs
            names.append(f"not filter_{i}")
        if not names:
            raise NotExpressible("a predicate that is always true")
        terms.append(" and ".join(names))
    if len(terms) == 1:
        det["condition"] = terms[0]
    else:
        det["condition"] = " or ".join(f"({t})" if " and " in t else t for t in terms)
    return det


def _uuid(rule: m.Rule, part: str) -> str:
    return str(uuid.uuid5(_NS, f"{rule.id}/{part}"))


def _meta(rule: m.Rule) -> dict[str, Any]:
    level = {"low": "low", "medium": "medium", "high": "high"}[rule.severity]
    return {
        "title": rule.title,
        "id": _uuid(rule, "rule"),
        "status": {"stable": "stable", "test": "test", "experimental": "experimental"}[
            rule.status
        ],
        "description": rule.summary,
        "references": [s.url for s in rule.sources],
        "author": "fraud-rules",
        "date": "2026-11-15",
        "tags": [f"fraudrules.{rule.id.lower()}", f"fraudrules.{rule.category}"],
        "falsepositives": list(rule.false_positives),
        "level": level,
    }


def _base(rule: m.Rule, name: str, title: str, where: m.Pred) -> dict[str, Any]:
    return {
        "title": title,
        "id": _uuid(rule, name),
        "name": name,
        "logsource": dict(LOGSOURCE),
        "detection": detection(where),
    }


def emits_sigma(rule: m.Rule) -> bool:
    return set(rule.tables()) == {"events"}


def to_sigma(rule: m.Rule) -> list[dict[str, Any]]:
    """The documents of a multi-document Sigma YAML file, outermost rule first."""
    if not emits_sigma(rule):
        raise NotExpressible(f"{rule.id} reads {rule.tables()}, not events only")
    lg = rule.logic
    under = rule.name.replace("-", "_")
    if isinstance(lg, m.Filter):
        doc = _meta(rule)
        doc["logsource"] = dict(LOGSOURCE)
        doc["detection"] = detection(lg.where)
        return [doc]
    if isinstance(lg, m.Aggregate):
        if lg.anchor != lg.members or len(lg.measures) != 1:
            raise NotExpressible("needs one measure over the anchor rows themselves")
        (ms,) = lg.measures
        h = lg.having
        if not (
            isinstance(h, m.HCmp)
            and h.left.kind == "measure"
            and h.left.times == 1
            and h.right.kind == "const"
            and isinstance(ms.where, m.TrueP)
            and ms.fn in ("count", "count_distinct")
            and lg.window is not None
        ):
            raise NotExpressible("having must compare one count with a constant")
        cond: dict[str, Any] = {_COND[h.op]: h.right.const * h.right.times}
        if ms.fn == "count_distinct":
            cond = {"field": ms.field, **cond}
        base = f"{under}_event"
        corr = _meta(rule)
        corr["correlation"] = {
            "type": "event_count" if ms.fn == "count" else "value_count",
            "rules": [base],
            "group-by": list(lg.key),
            "timespan": format_duration(lg.window),
            "condition": cond,
        }
        return [corr, _base(rule, base, f"{rule.title}: matching event", lg.members)]
    if lg.match:
        raise NotExpressible("step-to-anchor field matches have no Sigma form")
    names = [f"{under}_step{i + 1}" for i in range(len(lg.steps))]
    corr = _meta(rule)
    corr["correlation"] = {
        "type": "temporal_ordered",
        "rules": names,
        "group-by": list(lg.key),
        "timespan": format_duration(lg.within),
    }
    docs = [corr]
    for i, (name, st) in enumerate(zip(names, lg.steps, strict=True), 1):
        docs.append(_base(rule, name, f"{rule.title}: step {i}", st.where))
    return docs


class _Dumper(yaml.SafeDumper):
    pass


def _str_presenter(d: yaml.SafeDumper, s: str) -> yaml.ScalarNode:
    style = "|" if "\n" in s else None
    return d.represent_scalar("tag:yaml.org,2002:str", s, style=style)


_Dumper.add_representer(str, _str_presenter)


def dump(docs: list[dict[str, Any]]) -> str:
    return yaml.dump_all(docs, Dumper=_Dumper, sort_keys=False, explicit_start=False, width=100)


def iter_sigma(rules: list[m.Rule]) -> Iterator[tuple[m.Rule, str]]:
    for r in rules:
        if emits_sigma(r):
            yield r, dump(to_sigma(r))
