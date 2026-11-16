"""The foreign-agent family follows FinCEN FIN-2026-Alert009 and works on
small hand-built tables, without the synthetic generator."""

from __future__ import annotations

from typing import Any

import pytest
from conftest import BY_ID

from fraudrules import duck, pyeval, sigma, sigma_ref
from fraudrules.schema import TABLES

ALERT = "https://www.fincen.gov/system/files/2026-10/FinCEN-Alert-Foreign-Agent-Directed-Transactions.pdf"
FA = sorted(r for r in BY_ID if r.startswith("FA-"))
DAY = 86_400
T = 1_790_000_000
COUNTRIES = {"cn", "ae", "eg", "ke", "ug", "dj"}


def wire(i: int, **cols: Any) -> dict[str, Any]:
    row: dict[str, Any] = {c.name: None for c in TABLES["transactions"]}
    row.update(
        id=f"t{i}",
        ts=T + i * DAY,
        customer_id="msb1",
        account_id="a1",
        account_type="dda",
        txn_type="transfer",
        direction="out",
        channel="wire",
        amount_cents=1_234_567,
        counterparty_id=f"payee{i}",
        counterparty_type="business",
        counterparty_new=1,
        account_opened_ts=T - 900 * DAY,
        customer_segment="msb",
        directing_agent_id="agent1",
        in_agent_agreement=0,
        counterparty_country="ae",
        counterparty_sector="other",
        counterparty_formed_ts=T - 3000 * DAY,
        counterparty_web_presence=1,
        purpose="invoice",
        supporting_docs=1,
        round_amount=0,
        corridor_expected=1,
    )
    row.update(cols)
    return row


def hits(rule_id: str, tables: dict[str, list[dict[str, Any]]]) -> set[str]:
    rule = BY_ID[rule_id]
    py = pyeval.evaluate(rule, tables)
    con = duck.connect()
    duck.load(con, tables)
    assert duck.evaluate(con, rule) == py
    if sigma.emits_sigma(rule):
        docs = sigma_ref.parse(sigma.dump(sigma.to_sigma(rule)))
        assert sigma_ref.evaluate(docs, tables.get("events", [])) == py
    return py


def test_eight_rules_all_cite_the_alert() -> None:
    assert len(FA) == 8 and FA[0] == "FA-001" and FA[-1] == "FA-008"
    for rid in FA:
        r = BY_ID[rid]
        assert r.category == "foreign-agent"
        assert any(s.url == ALERT for s in r.sources), rid
        assert all(s.note for s in r.sources if s.url == ALERT), rid


@pytest.mark.parametrize("rid", ["FA-002", "FA-008"])
def test_country_list_is_the_alerts(rid: str) -> None:
    text = repr(BY_ID[rid].logic)
    for cc in COUNTRIES:
        assert f"'{cc}'" in text


def test_fa001_agreement_payee_is_quiet() -> None:
    rows = [wire(0), wire(1, in_agent_agreement=1), wire(2, directing_agent_id=None)]
    assert hits("FA-001", {"transactions": rows}) == {"t0"}


def test_fa002_counts_by_agent_across_accounts() -> None:
    rows = [
        wire(0, account_id="a1", counterparty_country="cn"),
        wire(1, account_id="a2", counterparty_country="ke"),
        wire(2, account_id="a3", counterparty_country="dj"),
        wire(3, account_id="a1", counterparty_country="gb"),
    ]
    assert hits("FA-002", {"transactions": rows}) == {"t2"}
    rows[2]["ts"] = rows[0]["ts"] + 31 * DAY
    assert hits("FA-002", {"transactions": rows}) == set()


def test_fa003_needs_generic_purpose_and_no_documents() -> None:
    rows = [
        wire(0, purpose="settlement", supporting_docs=0),
        wire(1, purpose=None, supporting_docs=None),
        wire(2, purpose="services", supporting_docs=1),
        wire(3, purpose="invoice", supporting_docs=0),
    ]
    assert hits("FA-003", {"transactions": rows}) == {"t0", "t1"}


def test_fa004_new_or_faceless_or_trading_company() -> None:
    rows = [
        wire(0, counterparty_formed_ts=T - 10 * DAY),
        wire(1, counterparty_web_presence=0),
        wire(2, counterparty_sector="textile"),
        wire(3),
        wire(4, counterparty_sector="general_trading", counterparty_country="us"),
        wire(5, counterparty_formed_ts=None),
    ]
    assert hits("FA-004", {"transactions": rows}) == {"t0", "t1", "t2"}


def test_fa005_fourth_round_wire_fires() -> None:
    rows = [wire(i, round_amount=1, amount_cents=2_500_000, directing_agent_id=None) for i in range(4)]
    assert hits("FA-005", {"transactions": rows}) == {"t3"}
    rows[1]["round_amount"] = 0
    assert hits("FA-005", {"transactions": rows}) == set()


def test_fa006_out_within_a_day_of_the_credit() -> None:
    credit = wire(0, direction="in", channel="ach", amount_cents=5_000_000, counterparty_country=None)
    out = wire(1, amount_cents=4_000_000, counterparty_country="ug")
    out["ts"] = credit["ts"] + 20 * 3600
    assert hits("FA-006", {"transactions": [credit, out]}) == {"t1"}
    out["in_agent_agreement"] = 1
    assert hits("FA-006", {"transactions": [credit, out]}) == set()
    out["in_agent_agreement"] = None
    out["ts"] = credit["ts"] + 25 * 3600
    assert hits("FA-006", {"transactions": [credit, out]}) == set()


def test_fa007_reads_events_and_emits_sigma() -> None:
    def ev(i: int, outcome: str) -> dict[str, Any]:
        row: dict[str, Any] = {c.name: None for c in TABLES["events"]}
        row.update(
            id=f"e{i}",
            ts=T + i * 10 * DAY,
            customer_id="agent1",
            event_type="agent_info_request",
            outcome=outcome,
            channel="back_office",
        )
        return row

    assert sigma.emits_sigma(BY_ID["FA-007"])
    assert hits("FA-007", {"events": [ev(0, "failure"), ev(1, "success")]}) == set()
    assert hits("FA-007", {"events": [ev(0, "failure"), ev(1, "denied")]}) == {"e1"}


def test_fa008_only_outside_declared_corridors() -> None:
    rows = [
        wire(0, amount_cents=3_000_000, counterparty_country="eg", corridor_expected=0),
        wire(1, amount_cents=3_000_000, counterparty_country="eg", corridor_expected=1),
        wire(2, amount_cents=2_499_999, counterparty_country="eg", corridor_expected=0),
        wire(3, amount_cents=3_000_000, counterparty_country="mx", corridor_expected=0),
    ]
    assert hits("FA-008", {"transactions": rows}) == {"t0"}
