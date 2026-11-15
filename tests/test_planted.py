"""Planted ground truth: every positive is caught, every near miss is not, on
every backend, for several seeds."""

from __future__ import annotations

import pytest
from conftest import RULES

from fraudrules import duck, pyeval, sigma, sigma_ref
from fraudrules.synth import SCENARIOS, generate


def test_every_rule_has_scenarios() -> None:
    assert set(SCENARIOS) == {r.id for r in RULES}


@pytest.mark.parametrize("seed", [7, 11, 2026])
def test_planted(seed: int) -> None:
    ds = generate(seed=seed, customers=150, days=45, copies=2)
    con = duck.connect()
    duck.load(con, ds.tables)
    for rule in RULES:
        py = pyeval.evaluate(rule, ds.tables)
        assert duck.evaluate(con, rule) == py, rule.id
        if sigma.emits_sigma(rule):
            docs = sigma_ref.parse(sigma.dump(sigma.to_sigma(rule)))
            assert sigma_ref.evaluate(docs, ds.tables["events"]) == py, rule.id
        planted = [p for p in ds.planted if p.rule_id == rule.id]
        assert len(planted) == 4
        for p in planted:
            if p.kind == "positive":
                assert py & p.rows, f"{rule.id} missed a planted positive"
            else:
                assert not py & p.rows, f"{rule.id} fired on a near miss: {sorted(py & p.rows)}"


def test_generator_is_deterministic() -> None:
    a, b = generate(seed=3, customers=40, days=30), generate(seed=3, customers=40, days=30)
    assert a.tables == b.tables
    assert a.planted == b.planted
    assert generate(seed=4, customers=40, days=30).tables != a.tables


def test_point_in_time_flags() -> None:
    ds = generate(seed=5, customers=60, days=30)
    seen: dict[str, set[object]] = {}
    for r in ds.tables["transactions"]:
        if r["counterparty_id"] is None:
            continue
        acct = str(r["account_id"])
        first = r["counterparty_id"] not in seen.setdefault(acct, set())
        assert r["counterparty_new"] == int(first)
        seen[acct].add(r["counterparty_id"])
    with pytest.raises(ValueError):
        generate(days=10)
