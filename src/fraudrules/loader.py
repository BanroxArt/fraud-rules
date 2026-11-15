"""Read rule files, check them against the JSON Schema and the table schemas,
substitute parameters and build the AST in :mod:`fraudrules.model`.

Parameters are referenced as ``$name`` anywhere a scalar or a duration is
expected. Overrides passed to :func:`load_rule` replace the file's defaults, so a
team can tune a threshold without forking the rule. An override for a parameter
the rule does not declare is an error: a typo should not silently leave the
default in place.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from importlib import resources
from pathlib import Path
from typing import Any, cast

import jsonschema
import yaml

from . import model as m
from .schema import TABLES, column, has_column

_DURATION = re.compile(r"^(\d+)([smhd])$")
_UNIT = {"s": 1, "m": 60, "h": 3600, "d": 86400}
_PARAM = re.compile(r"^\$([a-z_][a-z0-9_]*)$")


class RuleError(ValueError):
    """A rule file that cannot be compiled, with the file and the reason."""


def schema() -> dict[str, Any]:
    text = resources.files("fraudrules").joinpath("rule.schema.json").read_text("utf-8")
    return cast(dict[str, Any], json.loads(text))


def builtin_dir() -> Path:
    return Path(str(resources.files("fraudrules").joinpath("rules")))


def parse_duration(v: int | str) -> int:
    if isinstance(v, int):
        if v <= 0:
            raise ValueError(f"duration must be positive, got {v}")
        return v
    mt = _DURATION.match(v)
    if not mt:
        raise ValueError(f"bad duration {v!r}; use seconds or e.g. 90m, 24h, 30d")
    n = int(mt.group(1)) * _UNIT[mt.group(2)]
    if n <= 0:
        raise ValueError(f"duration must be positive, got {v!r}")
    return n


def format_duration(seconds: int) -> str:
    for unit, size in (("d", 86400), ("h", 3600), ("m", 60)):
        if seconds % size == 0:
            return f"{seconds // size}{unit}"
    return f"{seconds}s"


class _Ctx:
    def __init__(self, path: str, params: Mapping[str, m.Scalar]) -> None:
        self.path = path
        self.params = dict(params)
        self.used: set[str] = set()

    def err(self, msg: str) -> RuleError:
        return RuleError(f"{self.path}: {msg}")

    def scalar(self, v: Any) -> m.Scalar:
        if isinstance(v, bool):
            raise self.err(f"booleans are not allowed, use 0 or 1 (got {v})")
        if isinstance(v, str):
            mt = _PARAM.match(v)
            if mt:
                name = mt.group(1)
                if name not in self.params:
                    raise self.err(f"unknown parameter ${name}")
                self.used.add(name)
                return self.params[name]
            return v
        if isinstance(v, int):
            return v
        raise self.err(f"expected an integer or a string, got {v!r}")

    def int_(self, v: Any, what: str) -> int:
        s = self.scalar(v)
        if not isinstance(s, int):
            raise self.err(f"{what} must be an integer, got {s!r}")
        return s

    def duration(self, v: Any) -> int:
        s = self.scalar(v)
        try:
            return parse_duration(s)
        except ValueError as e:
            raise self.err(str(e)) from None

    def offset(self, v: Any) -> int:
        """A signed offset for ``plus``: seconds, a duration, or a negated duration."""
        s = self.scalar(v)
        if isinstance(s, int):
            return s
        neg = s.startswith("-")
        try:
            n = parse_duration(s[1:] if neg else s)
        except ValueError as e:
            raise self.err(str(e)) from None
        return -n if neg else n


def _field(ctx: _Ctx, table: str, name: str) -> str:
    if not has_column(table, name):
        raise ctx.err(f"{table} has no column {name!r}")
    return name


def _pred(ctx: _Ctx, table: str, raw: Mapping[str, Any]) -> m.Pred:
    if "all" in raw:
        return m.All(tuple(_pred(ctx, table, p) for p in raw["all"]))
    if "any" in raw:
        return m.AnyOf(tuple(_pred(ctx, table, p) for p in raw["any"]))
    if "not" in raw:
        return m.Not(_pred(ctx, table, raw["not"]))
    name = _field(ctx, table, raw["field"])
    col = column(table, name)
    (op,) = (k for k in raw if k != "field")
    v = raw[op]
    op = cast(m.CmpOp, op)
    if op in ("is_null", "not_null"):
        return m.Cmp(name, op)
    if op in ("in", "not_in"):
        vals = tuple(ctx.scalar(x) for x in v)
        for x in vals:
            _check_type(ctx, table, name, x)
        return m.Cmp(name, op, tuple(dict.fromkeys(vals)))
    if isinstance(v, dict):
        other = _field(ctx, table, v["field"])
        if col.type != "int" or column(table, other).type != "int":
            raise ctx.err(f"{table}.{name} vs {other}: field comparisons need integer columns")
        return m.Cmp(name, op, m.FieldRef(other, ctx.offset(v.get("plus", 0))))
    val = ctx.scalar(v)
    _check_type(ctx, table, name, val)
    if op in m.ORDER_OPS and col.type != "int":
        raise ctx.err(f"{table}.{name}: ordering comparisons are only allowed on integers")
    return m.Cmp(name, op, val)


def _check_type(ctx: _Ctx, table: str, name: str, val: m.Scalar) -> None:
    want = column(table, name).type
    got = "int" if isinstance(val, int) else "str"
    if want != got:
        raise ctx.err(f"{table}.{name} is {want}, compared with {val!r}")


def _term(ctx: _Ctx, table: str, raw: Any, measures: Mapping[str, m.Measure]) -> m.Term:
    if isinstance(raw, dict):
        times = ctx.int_(raw.get("times", 1), "times")
        if "measure" in raw:
            if raw["measure"] not in measures:
                raise ctx.err(f"unknown measure {raw['measure']!r}")
            return m.Term("measure", ref=raw["measure"], times=times)
        name = _field(ctx, table, raw["anchor"])
        if column(table, name).type != "int":
            raise ctx.err(f"anchor term {name!r} must be an integer column")
        return m.Term("anchor", ref=name, times=times)
    if isinstance(raw, str) and not raw.startswith("$"):
        if raw not in measures:
            raise ctx.err(f"unknown measure {raw!r}")
        return m.Term("measure", ref=raw)
    return m.Term("const", const=ctx.int_(raw, "constant"))


def _having(ctx: _Ctx, table: str, raw: Mapping[str, Any], measures: Mapping[str, m.Measure]) -> m.Having:
    if "all" in raw:
        return m.HAll(tuple(_having(ctx, table, h, measures) for h in raw["all"]))
    if "any" in raw:
        return m.HAny(tuple(_having(ctx, table, h, measures) for h in raw["any"]))
    if "not" in raw:
        return m.HNot(_having(ctx, table, raw["not"], measures))
    (op,) = (k for k in raw if k != "left")
    left = _term(ctx, table, raw["left"], measures)
    right = _term(ctx, table, raw[op], measures)
    for t in (left, right):
        if t.kind == "measure":
            ms = measures[t.ref]
            if ms.field and column(table, ms.field).type != "int" and ms.fn in ("min", "max"):
                raise ctx.err(f"measure {ms.name}: min and max need an integer column")
    return m.HCmp(left, cast(m.HavingOp, op), right)


def _measures(ctx: _Ctx, table: str, raw: Mapping[str, Any]) -> dict[str, m.Measure]:
    out: dict[str, m.Measure] = {}
    for name, spec in raw.items():
        fn = cast(m.AggFn, spec["fn"])
        fld = spec.get("field")
        if fn == "count":
            if fld is not None:
                raise ctx.err(f"measure {name}: count takes no field")
        else:
            if fld is None:
                raise ctx.err(f"measure {name}: {fn} needs a field")
            _field(ctx, table, fld)
            if fn in ("sum", "min", "max") and column(table, fld).type != "int":
                raise ctx.err(f"measure {name}: {fn} needs an integer column")
        where = _pred(ctx, table, spec["where"]) if "where" in spec else m.TrueP()
        out[name] = m.Measure(name, fn, fld, where)
    return out


def _key(ctx: _Ctx, tables: list[str], key: list[str]) -> tuple[str, ...]:
    for k in key:
        types = {column(t, _field(ctx, t, k)).type for t in tables}
        if len(types) != 1:
            raise ctx.err(f"key {k!r} has different types across {tables}")
    return tuple(key)


def _logic(ctx: _Ctx, raw: Mapping[str, Any]) -> m.Logic:
    if "filter" in raw:
        return m.Filter(raw["table"], _pred(ctx, raw["table"], raw["filter"]))
    if "aggregate" in raw:
        a = raw["aggregate"]
        t = raw["table"]
        measures = _measures(ctx, t, a["measures"])
        anchor = _pred(ctx, t, a["anchor"]) if "anchor" in a else m.TrueP()
        members = _pred(ctx, t, a["members"]) if "members" in a else anchor
        return m.Aggregate(
            table=t,
            key=_key(ctx, [t], a["key"]),
            window=ctx.duration(a["window"]) if "window" in a else None,
            anchor=anchor,
            members=members,
            measures=tuple(measures.values()),
            having=_having(ctx, t, a["having"], measures),
        )
    s = raw["sequence"]
    default = s["steps"][0].get("table", "events")
    steps = []
    for st in s["steps"]:
        t = st.get("table", default)
        steps.append(m.Step(t, _pred(ctx, t, st["where"])))
    matches = []
    for mt in s.get("match", []):
        i = mt["step"]
        if i >= len(steps) - 1:
            raise ctx.err(f"match step {i} must be an earlier step, not the anchor")
        a_t, s_t = steps[-1].table, steps[i].table
        f = _field(ctx, s_t, mt["field"])
        af = _field(ctx, a_t, mt["anchor_field"])
        if column(s_t, f).type != column(a_t, af).type:
            raise ctx.err(f"match {f} = {af}: types differ")
        matches.append(m.Match(i, f, af))
    return m.Sequence(
        key=_key(ctx, [st.table for st in steps], s["key"]),
        within=ctx.duration(s["within"]),
        steps=tuple(steps),
        match=tuple(matches),
    )


def parse_rule(
    raw: Mapping[str, Any], path: str = "<rule>", overrides: Mapping[str, m.Scalar] | None = None
) -> m.Rule:
    try:
        jsonschema.validate(raw, schema())
    except jsonschema.ValidationError as e:
        where = "/".join(str(p) for p in e.absolute_path) or "(top level)"
        raise RuleError(f"{path}: {where}: {e.message}") from None
    params: dict[str, m.Scalar] = dict(raw.get("params", {}))
    for k, v in (overrides or {}).items():
        if k not in params:
            raise RuleError(f"{path}: override for unknown parameter {k!r}")
        if isinstance(v, bool) or type(v) is not type(params[k]):
            raise RuleError(f"{path}: override {k}={v!r} has the wrong type")
        params[k] = v
    ctx = _Ctx(path, params)
    logic = _logic(ctx, raw)
    unused = set(params) - ctx.used
    if unused:
        raise RuleError(f"{path}: parameters declared but not used: {sorted(unused)}")
    for knob in raw["tuning"]:
        if knob["param"] not in params:
            raise RuleError(f"{path}: tuning names unknown parameter {knob['param']!r}")
    for t in logic.steps if isinstance(logic, m.Sequence) else [logic]:
        if t.table not in TABLES:
            raise RuleError(f"{path}: unknown table {t.table!r}")
    return m.Rule(
        id=raw["id"],
        name=raw["name"],
        title=raw["title"],
        category=raw["category"],
        severity=raw["severity"],
        status=raw["status"],
        summary=raw["summary"].strip(),
        rationale=raw["rationale"].strip(),
        sources=tuple(
            m.Source(s["title"], s["url"], s["publisher"], s.get("note", "")) for s in raw["sources"]
        ),
        false_positives=tuple(raw["false_positives"]),
        tuning=tuple(m.Knob(k["param"], k["effect"]) for k in raw["tuning"]),
        params=params,
        logic=logic,
        path=path,
    )


def load_rule(path: str | Path, overrides: Mapping[str, m.Scalar] | None = None) -> m.Rule:
    p = Path(path)
    raw = yaml.safe_load(p.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise RuleError(f"{p}: expected a mapping at the top level")
    return parse_rule(raw, str(p.name), overrides)


def load_pack(
    directory: str | Path | None = None,
    overrides: Mapping[str, Mapping[str, m.Scalar]] | None = None,
) -> list[m.Rule]:
    """Every ``*.yaml`` under ``directory`` (the bundled pack by default), sorted by id.

    ``overrides`` maps a rule id to its parameter overrides.
    """
    base = Path(directory) if directory is not None else builtin_dir()
    rules = []
    for p in sorted(base.rglob("*.yaml")):
        raw_id = yaml.safe_load(p.read_text(encoding="utf-8")).get("id", "")
        rules.append(load_rule(p, (overrides or {}).get(raw_id)))
    ids = [r.id for r in rules]
    dupes = {i for i in ids if ids.count(i) > 1}
    if dupes:
        raise RuleError(f"duplicate rule ids: {sorted(dupes)}")
    names = [r.name for r in rules]
    if len(set(names)) != len(names):
        raise RuleError("duplicate rule names")
    return sorted(rules, key=lambda r: r.id)
