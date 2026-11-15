"""The example local rule loads, compiles for every dialect and fires on the
case it describes."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fraudrules import duck, pyeval, sql
from fraudrules.loader import load_pack

EXAMPLES = Path(__file__).resolve().parent.parent / "examples" / "custom-rule"
DAY = 86_400


def deposit(i: int, ts: int, amount: int, opened: int = 0, channel: str = "check") -> dict[str, Any]:
    return {
        "id": f"t{i}",
        "ts": ts,
        "customer_id": "c1",
        "account_id": "a1",
        "account_type": "dda",
        "txn_type": "deposit",
        "direction": "in",
        "channel": channel,
        "amount_cents": amount,
        "counterparty_id": f"maker{i}",
        "counterparty_type": "individual",
        "counterparty_new": 1,
        "return_code": None,
        "location_id": None,
        "account_opened_ts": opened,
        "customer_age": 40,
        "credit_limit_cents": None,
    }


def both(rows: list[dict[str, Any]]) -> set[str]:
    (rule,) = load_pack(EXAMPLES)
    tables = {"transactions": rows}
    py = pyeval.evaluate(rule, tables)
    con = duck.connect()
    duck.load(con, tables)
    assert duck.evaluate(con, rule) == py
    return py


def test_loads_and_compiles() -> None:
    (rule,) = load_pack(EXAMPLES)
    assert rule.id == "CK-901"
    for dialect in sql.DIALECTS:
        assert "SELECT" in sql.transpile(sql.compile_rule(rule), dialect)


def test_fires_on_fourth_check_in_first_month() -> None:
    rows = [deposit(i, (i + 1) * 5 * DAY, 80_000) for i in range(4)]
    assert both(rows) == {"t3"}


def test_quiet_after_first_month_or_below_total() -> None:
    late = [deposit(i, (i + 1) * 8 * DAY, 80_000) for i in range(4)]
    assert both(late) == set()
    small = [deposit(i, (i + 1) * 5 * DAY, 74_999) for i in range(4)]
    assert both(small) == set()
    mixed = [deposit(i, (i + 1) * 5 * DAY, 80_000, channel="ach" if i == 0 else "check") for i in range(4)]
    assert both(mixed) == set()
