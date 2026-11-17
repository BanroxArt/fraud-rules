"""The instant-payment family (IP-001 to IP-006) on small hand-built tables.

Each test changes one thing about a flagged case and checks the rule's answer
flips, on the Python evaluator and on DuckDB."""

from __future__ import annotations

from typing import Any

import pytest
from conftest import BY_ID

from fraudrules import duck, pyeval, sigma
from fraudrules.schema import TABLES

IP = sorted(r for r in BY_ID if r.startswith("IP-"))
MIN = 60
HOUR = 3_600
DAY = 86_400
T = 1_790_000_000
INSTANT = {"rtp", "fednow", "p2p"}


def txn(i: int, **cols: Any) -> dict[str, Any]:
    row: dict[str, Any] = {c.name: None for c in TABLES["transactions"]}
    row.update(
        id=f"t{i}",
        ts=T,
        customer_id="c1",
        account_id="a1",
        account_type="dda",
        txn_type="transfer",
        direction="out",
        channel="rtp",
        amount_cents=100_000,
        counterparty_id=f"cp{i}",
        counterparty_type="individual",
        counterparty_new=1,
        account_opened_ts=T - 900 * DAY,
    )
    row.update(cols)
    return row


def event(i: int, **cols: Any) -> dict[str, Any]:
    row: dict[str, Any] = {c.name: None for c in TABLES["events"]}
    row.update(id=f"e{i}", ts=T, customer_id="c1", event_type="login", outcome="success", channel="mobile")
    row.update(cols)
    return row


def hits(rule_id: str, txns: list[dict[str, Any]], events: list[dict[str, Any]] | None = None) -> set[str]:
    tables = {"transactions": txns, "events": events or [], "applications": []}
    rule = BY_ID[rule_id]
    py = pyeval.evaluate(rule, tables)
    con = duck.connect()
    duck.load(con, tables)
    assert duck.evaluate(con, rule) == py
    return py


def test_family_shape() -> None:
    assert [f"IP-00{i}" for i in range(1, 7)] == IP
    for rid in IP:
        r = BY_ID[rid]
        assert r.category == "instant-payment"
        assert r.status == "experimental"
        assert len(r.sources) >= 3, rid
        assert all(s.url.startswith("https://") and s.note for s in r.sources), rid
        assert "fednow" in repr(r.logic), rid
        assert not sigma.emits_sigma(r), rid


def test_ip001_minutes_not_hours() -> None:
    new = T - 5 * DAY
    credit = txn(1, direction="in", channel="rtp", amount_cents=300_000, account_opened_ts=new)
    out = txn(2, ts=T + 10 * MIN, channel="fednow", amount_cents=290_000, account_opened_ts=new)
    assert hits("IP-001", [credit, out]) == {"t2"}
    assert hits("IP-001", [credit, {**out, "ts": T + 31 * MIN}]) == set()
    assert hits("IP-001", [credit, {**out, "amount_cents": 200_000}]) == set()
    assert hits("IP-001", [{**credit, "channel": "ach"}, out]) == set()
    old = T - 400 * DAY
    assert hits("IP-001", [{**credit, "account_opened_ts": old}, {**out, "account_opened_ts": old}]) == set()


def test_ip001_ignores_returns() -> None:
    new = T - 5 * DAY
    ret = txn(1, direction="in", txn_type="return", amount_cents=300_000, account_opened_ts=new)
    out = txn(2, ts=T + 5 * MIN, amount_cents=290_000, account_opened_ts=new)
    assert hits("IP-001", [ret, out]) == set()


def test_ip002_counts_distinct_senders() -> None:
    new = T - 10 * DAY
    rows = [
        txn(
            i,
            ts=T + i * HOUR,
            direction="in",
            amount_cents=60_000,
            account_opened_ts=new,
            counterparty_id=f"s{i}",
        )
        for i in range(5)
    ]
    assert hits("IP-002", rows) == {"t4"}
    same = [{**r, "counterparty_id": "s0" if r["id"] != "t4" else "s1"} for r in rows]
    assert hits("IP-002", same) == set()
    spread = [{**r, "ts": T + i * 7 * HOUR} for i, r in enumerate(rows)]
    assert hits("IP-002", spread) == set()


def test_ip003_hour_window_and_first_time_payees() -> None:
    rows = [txn(i, ts=T + i * 10 * MIN, amount_cents=110_000) for i in range(3)]
    assert hits("IP-003", rows) == {"t2"}
    assert hits("IP-003", [{**r, "counterparty_new": 0} if r["id"] == "t0" else r for r in rows]) == set()
    assert hits("IP-003", [{**r, "ts": T + i * 40 * MIN} for i, r in enumerate(rows)]) == set()
    assert hits("IP-003", [{**r, "channel": "ach"} for r in rows]) == set()


@pytest.mark.parametrize(
    "signal",
    [
        {"event_type": "sim_change", "channel": "back_office"},
        {"event_type": "login", "device_new": 1},
    ],
)
def test_ip004_either_signal(signal: dict[str, Any]) -> None:
    ev = event(1, **signal)
    pay = txn(1, ts=T + 2 * HOUR, channel="p2p", amount_cents=80_000)
    assert hits("IP-004", [pay], [ev]) == {"t1"}
    assert hits("IP-004", [{**pay, "ts": T + 25 * HOUR}], [ev]) == set()
    assert hits("IP-004", [{**pay, "counterparty_new": 0}], [ev]) == set()
    assert hits("IP-004", [{**pay, "ts": T - HOUR}], [ev]) == set()


def test_ip004_known_device_or_failed_swap_is_quiet() -> None:
    pay = txn(1, ts=T + HOUR)
    assert hits("IP-004", [pay], [event(1, device_new=0)]) == set()
    assert hits("IP-004", [pay], [event(1, event_type="sim_change", outcome="failure")]) == set()
    assert hits("IP-004", [pay], [event(1, event_type="phone_change")]) == set()


def test_ip005_link_age_and_ownership() -> None:
    pay = txn(1, amount_cents=500_000, payee_self=1, counterparty_linked_ts=T - 10 * HOUR)
    assert hits("IP-005", [pay]) == {"t1"}
    assert hits("IP-005", [{**pay, "counterparty_linked_ts": T - 4 * DAY}]) == set()
    assert hits("IP-005", [{**pay, "payee_self": 0}]) == set()
    assert hits("IP-005", [{**pay, "payee_self": None}]) == set()
    assert hits("IP-005", [{**pay, "counterparty_linked_ts": None}]) == set()
    assert hits("IP-005", [{**pay, "channel": "ach"}]) == set()


def test_ip006_source_age_destination_age() -> None:
    pay = txn(
        1,
        channel="internal",
        amount_cents=2_500_000,
        payee_self=1,
        account_opened_ts=T - 9 * 365 * DAY,
        counterparty_opened_ts=T - 3 * DAY,
    )
    assert hits("IP-006", [pay]) == {"t1"}
    assert hits("IP-006", [{**pay, "account_opened_ts": T - 300 * DAY}]) == set()
    assert hits("IP-006", [{**pay, "counterparty_opened_ts": T - 20 * DAY}]) == set()
    assert hits("IP-006", [{**pay, "counterparty_opened_ts": None}]) == set()
    assert hits("IP-006", [{**pay, "amount_cents": 999_999}]) == set()


def test_fednow_is_in_the_channel_vocabulary() -> None:
    doc = next(c.doc for c in TABLES["transactions"] if c.name == "channel")
    assert "fednow" in doc
    for rid in IP:
        text = repr(BY_ID[rid].logic)
        assert INSTANT & {w.strip("'\" ,[]()") for w in text.split()}, rid
