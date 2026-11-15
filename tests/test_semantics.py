"""Hand-written cases for the edges the backends must agree on."""

from __future__ import annotations

from typing import Any

import pytest

from fraudrules import duck, pyeval, sigma, sigma_ref
from fraudrules.loader import parse_rule
from fraudrules.model import Rule

BASE: dict[str, Any] = {
    "id": "XX-001",
    "name": "test-rule",
    "title": "A rule used only by the tests",
    "category": "account-takeover",
    "severity": "low",
    "status": "experimental",
    "summary": "Exists to pin down evaluation semantics in tests.",
    "rationale": "x" * 100,
    "sources": [{"publisher": "p", "title": "t", "url": "https://example.com/"}],
    "false_positives": ["none"],
    "tuning": [],
}


def rule(**logic: Any) -> Rule:
    return parse_rule({**BASE, **logic})


def ev(i: int, ts: int, **kw: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": f"e{i}",
        "ts": ts,
        "customer_id": "c1",
        "account_id": None,
        "event_type": "login",
        "outcome": "failure",
        "channel": "web",
        "device_id": None,
        "device_new": None,
        "ip_token": f"ip{i}",
        "geo_new": None,
        "payee_id": None,
        "customer_age": None,
    }
    row.update(kw)
    return row


def all_backends(r: Rule, events: list[dict[str, Any]]) -> set[str]:
    tables = {"events": events}
    py = pyeval.evaluate(r, tables)
    con = duck.connect()
    duck.load(con, tables)
    assert duck.evaluate(con, r) == py, "sql"
    if sigma.emits_sigma(r):
        try:
            docs = sigma.to_sigma(r)
        except sigma.NotExpressible:
            return py
        assert sigma_ref.evaluate(sigma_ref.parse(sigma.dump(docs)), events) == py, "sigma"
    return py


COUNT3 = {
    "table": "events",
    "aggregate": {
        "key": ["customer_id"],
        "window": 100,
        "anchor": {"field": "event_type", "eq": "login"},
        "measures": {"n": {"fn": "count"}},
        "having": {"left": "n", "gte": 3},
    },
}


def test_window_lower_bound_is_exclusive() -> None:
    r = rule(**COUNT3)
    # e0 at 0 is exactly one window before e2 at 100: outside.
    assert all_backends(r, [ev(0, 0), ev(1, 50), ev(2, 100)]) == set()
    assert all_backends(r, [ev(0, 1), ev(1, 50), ev(2, 100)]) == {"e2"}


def test_window_upper_bound_includes_ties() -> None:
    r = rule(**COUNT3)
    # Rows sharing the anchor's timestamp are inside its window, both ways.
    assert all_backends(r, [ev(0, 10), ev(1, 50), ev(2, 50)]) == {"e1", "e2"}


def test_null_key_never_groups() -> None:
    r = rule(**COUNT3)
    rows = [ev(i, 10 + i, customer_id=None) for i in range(4)]
    assert all_backends(r, rows) == set()


def test_ne_is_false_on_null_but_not_eq_is_true() -> None:
    ne = rule(table="events", filter={"field": "payee_id", "ne": "p1"})
    not_eq = rule(table="events", filter={"not": {"field": "payee_id", "eq": "p1"}})
    rows = [ev(0, 1), ev(1, 2, payee_id="p1"), ev(2, 3, payee_id="p2")]
    assert all_backends(ne, rows) == {"e2"}
    assert all_backends(not_eq, rows) == {"e0", "e2"}


def test_not_in_and_not_null() -> None:
    r = rule(
        table="events",
        filter={"all": [{"field": "payee_id", "not_in": ["p1", "p2"]}, {"field": "ip_token", "not_null": True}]},
    )
    rows = [ev(0, 1), ev(1, 2, payee_id="p3"), ev(2, 3, payee_id="p2"), ev(3, 4, payee_id="p4", ip_token=None)]
    assert all_backends(r, rows) == {"e1"}


SEQ = {
    "sequence": {
        "key": ["customer_id"],
        "within": 100,
        "steps": [
            {"table": "events", "where": {"field": "event_type", "eq": "email_change"}},
            {"table": "events", "where": {"field": "event_type", "eq": "payee_added"}},
        ],
    }
}


def test_sequence_needs_strict_order() -> None:
    r = rule(**SEQ)
    same_ts = [ev(0, 10, event_type="email_change"), ev(1, 10, event_type="payee_added")]
    assert all_backends(r, same_ts) == set()
    reversed_ = [ev(0, 10, event_type="payee_added"), ev(1, 20, event_type="email_change")]
    assert all_backends(r, reversed_) == set()
    ok = [ev(0, 10, event_type="email_change"), ev(1, 20, event_type="payee_added")]
    assert all_backends(r, ok) == {"e1"}


def test_sequence_window_is_measured_from_the_first_step() -> None:
    r = rule(**SEQ)
    assert all_backends(r, [ev(0, 0, event_type="email_change"), ev(1, 100, event_type="payee_added")]) == set()
    assert all_backends(r, [ev(0, 1, event_type="email_change"), ev(1, 100, event_type="payee_added")]) == {"e1"}


def test_sequence_match_pins_a_field_to_the_anchor() -> None:
    r = rule(
        sequence={
            **SEQ["sequence"],
            "steps": [
                {"table": "events", "where": {"field": "event_type", "eq": "payee_changed"}},
                {"table": "events", "where": {"field": "event_type", "eq": "payee_added"}},
            ],
            "match": [{"step": 0, "field": "payee_id", "anchor_field": "payee_id"}],
        }
    )
    rows = [
        ev(0, 1, event_type="payee_changed", payee_id="p1"),
        ev(1, 5, event_type="payee_added", payee_id="p2"),
        ev(2, 6, event_type="payee_added", payee_id="p1"),
        ev(3, 7, event_type="payee_added", payee_id=None),
    ]
    assert all_backends(r, rows) == {"e2"}


def test_sequence_greedy_choice_is_not_fooled_by_an_early_first_step() -> None:
    # Steps a, b, c. The earliest a has no b after it within the window from c,
    # but a later a does. Greedy-earliest on step 1 must still find the chain.
    r = rule(
        sequence={
            "key": ["customer_id"],
            "within": 50,
            "steps": [
                {"table": "events", "where": {"field": "event_type", "eq": "password_reset"}},
                {"table": "events", "where": {"field": "event_type", "eq": "login"}},
                {"table": "events", "where": {"field": "event_type", "eq": "payee_added"}},
            ],
        }
    )
    rows = [
        ev(0, 0, event_type="password_reset"),
        ev(1, 60, event_type="password_reset"),
        ev(2, 70, event_type="login"),
        ev(3, 80, event_type="payee_added"),
    ]
    assert all_backends(r, rows) == {"e3"}


def test_measure_filters_and_null_sums() -> None:
    r = rule(
        table="events",
        aggregate={
            "key": ["customer_id"],
            "window": 1000,
            "measures": {
                "ok": {"fn": "count", "where": {"field": "outcome", "eq": "success"}},
                "ages": {"fn": "sum", "field": "customer_age", "where": {"field": "outcome", "eq": "success"}},
            },
            "having": {"any": [{"left": "ok", "gte": 2}, {"left": "ages", "lt": 0}]},
        },
    )
    rows = [ev(0, 1), ev(1, 2, outcome="success"), ev(2, 3, outcome="success")]
    # ages is null throughout: "ages < 0" is false, never an error.
    assert all_backends(r, rows) == {"e2"}


def test_value_count_ignores_nulls() -> None:
    r = rule(
        table="events",
        aggregate={
            "key": ["customer_id"],
            "window": 100,
            "anchor": {"field": "outcome", "eq": "failure"},
            "measures": {"ips": {"fn": "count_distinct", "field": "ip_token"}},
            "having": {"left": "ips", "gte": 3},
        },
    )
    rows = [ev(0, 1), ev(1, 2, ip_token=None), ev(2, 3, ip_token=None), ev(3, 4)]
    assert all_backends(r, rows) == set()
    assert all_backends(r, [*rows, ev(4, 5)]) == {"e4"}


def test_sigma_string_match_is_case_insensitive_by_design() -> None:
    r = rule(table="events", filter={"field": "event_type", "eq": "login"})
    docs = sigma_ref.parse(sigma.dump(sigma.to_sigma(r)))
    assert sigma_ref.evaluate(docs, [ev(0, 1, event_type="LOGIN")]) == {"e0"}
    assert pyeval.evaluate(r, {"events": [ev(0, 1, event_type="LOGIN")]}) == set()


@pytest.mark.parametrize(
    "pred",
    [
        {"any": [{"field": "event_type", "eq": "login"}, {"not": {"field": "outcome", "in": ["success"]}}]},
        {"not": {"all": [{"field": "event_type", "eq": "login"}, {"field": "ip_token", "is_null": True}]}},
        {"all": [{"field": "customer_age", "gte": 60}, {"field": "customer_age", "lt": 70}]},
    ],
)
def test_sigma_dnf_matches_python(pred: dict[str, Any]) -> None:
    r = rule(table="events", filter=pred)
    rows = [
        ev(i, i, event_type=et, outcome=oc, ip_token=ip, customer_age=age)
        for i, (et, oc, ip, age) in enumerate(
            [
                ("login", "success", None, 59),
                ("login", "failure", "x", 60),
                ("mfa_change", "success", None, 69),
                ("mfa_change", "failure", "y", 70),
                ("payee_added", "denied", None, None),
            ]
        )
    ]
    all_backends(r, rows)
