from __future__ import annotations

import re

import pytest
from conftest import RULES
from test_semantics import rule

from fraudrules import sigma, sigma_ref
from fraudrules.loader import format_duration

SIGMA = [r for r in RULES if sigma.emits_sigma(r)]


def test_log_shaped_rules_all_emit() -> None:
    expected = {r.id for r in RULES if r.category == "account-takeover"} | {"FA-007"}
    assert {r.id for r in SIGMA} == expected


@pytest.mark.parametrize("r", SIGMA, ids=lambda r: r.id)
def test_documents_follow_the_spec(r) -> None:  # type: ignore[no-untyped-def]
    docs = sigma_ref.parse(sigma.dump(sigma.to_sigma(r)))
    top = docs[0]
    for key in ("title", "id", "status", "level", "description", "references", "falsepositives"):
        assert key in top
    assert re.fullmatch(r"[0-9a-f-]{36}", top["id"])
    names = {d["name"] for d in docs[1:]}
    if "correlation" in top:
        c = top["correlation"]
        assert c["type"] in {"event_count", "value_count", "temporal_ordered"}
        assert set(c["rules"]) <= names
        assert re.fullmatch(r"\d+[smhd]", c["timespan"])
        assert c["group-by"]
        for d in docs[1:]:
            assert d["logsource"] == sigma.LOGSOURCE
            assert "condition" in d["detection"]
    else:
        assert "detection" in top
    ids = [d["id"] for d in docs]
    assert len(ids) == len(set(ids))


def test_ids_are_stable() -> None:
    a = sigma.to_sigma(SIGMA[0])
    b = sigma.to_sigma(SIGMA[0])
    assert [d["id"] for d in a] == [d["id"] for d in b]


def test_not_expressible() -> None:
    by_id = {r.id: r for r in RULES}
    with pytest.raises(sigma.NotExpressible):
        sigma.to_sigma(by_id["MU-001"])  # transactions, not events
    ref = rule(table="events", filter={"field": "ts", "gt": {"field": "customer_age", "plus": 5}})
    with pytest.raises(sigma.NotExpressible):
        sigma.to_sigma(ref)
    sum_rule = rule(
        table="events",
        aggregate={
            "key": ["customer_id"],
            "window": 60,
            "measures": {"s": {"fn": "sum", "field": "customer_age"}},
            "having": {"left": "s", "gte": 1},
        },
    )
    with pytest.raises(sigma.NotExpressible):
        sigma.to_sigma(sum_rule)


def test_condition_parser() -> None:
    f = sigma_ref._condition("(a and not b) or not (c or d)")
    assert f({"a": True, "b": False, "c": True, "d": False})
    assert f({"a": False, "b": False, "c": False, "d": False})
    assert not f({"a": False, "b": True, "c": True, "d": False})
    for bad in ("a and", "(a", "a b", "1 of selection_*"):
        with pytest.raises((ValueError, IndexError, KeyError)):
            sigma_ref._condition(bad)({"a": True, "b": True})


def test_format_duration() -> None:
    assert [format_duration(x) for x in (600, 3600, 86400 * 2, 90)] == ["10m", "1h", "2d", "90s"]
