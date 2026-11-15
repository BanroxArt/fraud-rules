from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest
import yaml
from test_semantics import BASE

from fraudrules.loader import RuleError, builtin_dir, load_pack, parse_duration, parse_rule

GOOD: dict[str, Any] = {
    **BASE,
    "params": {"window": "10m", "n": 3},
    "tuning": [{"param": "n", "effect": "threshold"}],
    "table": "events",
    "aggregate": {
        "key": ["customer_id"],
        "window": "$window",
        "measures": {"c": {"fn": "count"}},
        "having": {"left": "c", "gte": "$n"},
    },
}


def bad(mutate: Any) -> dict[str, Any]:
    raw = copy.deepcopy(GOOD)
    mutate(raw)
    return raw


def test_good_rule_and_overrides() -> None:
    r = parse_rule(GOOD)
    assert r.logic.window == 600  # type: ignore[union-attr]
    r2 = parse_rule(GOOD, overrides={"n": 5, "window": "1h"})
    assert r2.params == {"window": "1h", "n": 5}
    assert r2.logic.window == 3600  # type: ignore[union-attr]


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda r: r.update(id="bad"), "does not match"),
        (lambda r: r["aggregate"].update(key=["nope"]), "no column 'nope'"),
        (lambda r: r["aggregate"]["having"].update(gte="$missing"), "unknown parameter"),
        (lambda r: r["params"].update(spare=1), "not used"),
        (
            lambda r: r["aggregate"]["measures"].update(s={"fn": "sum", "field": "event_type"}),
            "integer column",
        ),
        (lambda r: r["aggregate"]["measures"].update(s={"fn": "count", "field": "ts"}), "takes no field"),
        (
            lambda r: r["aggregate"].update(anchor={"field": "event_type", "gt": "a"}),
            "only allowed on integers",
        ),
        (lambda r: r["aggregate"].update(anchor={"field": "device_new", "eq": "1"}), "is int"),
        (lambda r: r["aggregate"].update(anchor={"field": "device_new", "eq": True}), "booleans|not valid"),
        (lambda r: r["aggregate"].update(window="10 minutes"), "does not match|bad duration"),
        (lambda r: r["aggregate"]["having"].update(left="nope"), "unknown measure"),
        (lambda r: r.update(tuning=[{"param": "zzz", "effect": "x"}]), "unknown parameter 'zzz'"),
        (lambda r: r.update(sources=[{"publisher": "p", "title": "t", "url": "http://x"}]), "does not match"),
        (
            lambda r: r.update(filter={"field": "ts", "gt": 1}),
            "is valid under each of|should not be valid|valid",
        ),
    ],
)
def test_rejects(mutate: Any, message: str) -> None:
    import re

    with pytest.raises(RuleError, match=re.compile(message)):
        parse_rule(bad(mutate))


def test_override_errors() -> None:
    with pytest.raises(RuleError, match="unknown parameter"):
        parse_rule(GOOD, overrides={"nope": 1})
    with pytest.raises(RuleError, match="wrong type"):
        parse_rule(GOOD, overrides={"n": "5"})


def test_sequence_checks() -> None:
    seq = {k: v for k, v in GOOD.items() if k not in ("aggregate", "table", "params", "tuning")}
    seq["tuning"] = []
    seq["sequence"] = {
        "key": ["customer_id"],
        "within": "1h",
        "steps": [
            {"table": "events", "where": {"field": "event_type", "eq": "payee_changed"}},
            {"table": "transactions", "where": {"field": "direction", "eq": "out"}},
        ],
        "match": [{"step": 1, "field": "payee_id", "anchor_field": "counterparty_id"}],
    }
    with pytest.raises(RuleError, match="earlier step"):
        parse_rule(seq)
    seq["sequence"]["match"] = [{"step": 0, "field": "payee_id", "anchor_field": "amount_cents"}]
    with pytest.raises(RuleError, match="types differ"):
        parse_rule(seq)
    seq["sequence"]["match"] = [{"step": 0, "field": "payee_id", "anchor_field": "counterparty_id"}]
    assert parse_rule(seq).tables() == ("events", "transactions")


def test_durations() -> None:
    assert parse_duration("90d") == 90 * 86400
    assert parse_duration(15) == 15
    for v in ("0m", "1w", "-1h", 0):
        with pytest.raises(ValueError):
            parse_duration(v)


def test_pack_is_unique_and_files_are_named_after_ids() -> None:
    rules = load_pack()
    assert 20 <= len(rules) <= 30
    for r in rules:
        assert r.path == f"{r.id.lower()}-{r.name}.yaml"
        assert (builtin_dir() / r.category / r.path).is_file()


def test_every_rule_documents_itself() -> None:
    for r in load_pack():
        assert r.sources and r.false_positives
        assert {k.param for k in r.tuning} == set(r.params), r.id
        for s in r.sources:
            assert s.url.startswith("https://")


def test_duplicate_ids_rejected(tmp_path: Path) -> None:
    src = next(builtin_dir().rglob("*.yaml"))
    raw = yaml.safe_load(src.read_text())
    (tmp_path / "a.yaml").write_text(yaml.safe_dump(raw))
    raw["name"] = raw["name"] + "-copy"
    (tmp_path / "b.yaml").write_text(yaml.safe_dump(raw))
    with pytest.raises(RuleError, match="duplicate rule ids"):
        load_pack(tmp_path)
