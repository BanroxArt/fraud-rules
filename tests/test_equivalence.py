"""Every backend flags the same rows, on data generated to sit on rule edges."""

from __future__ import annotations

import pytest
from conftest import BY_ID
from hypothesis import HealthCheck, Phase, given, settings
from hypothesis import strategies as st
from strategies import tables_for

from fraudrules import duck, pyeval, sigma, sigma_ref
from fraudrules.sql import compile_rule, transpile

SETTINGS = settings(
    max_examples=80,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.data_too_large],
)


@pytest.fixture(scope="module")
def con():  # type: ignore[no-untyped-def]
    c = duck.connect()
    yield c
    c.close()


@pytest.mark.parametrize("rule_id", sorted(BY_ID))
@SETTINGS
@given(data=st.data())
def test_python_sql_sigma_agree(con, rule_id: str, data: st.DataObject) -> None:  # type: ignore[no-untyped-def]
    rule = BY_ID[rule_id]
    tables = data.draw(tables_for(rule))
    expected = pyeval.evaluate(rule, tables)
    duck.load(con, tables)
    assert duck.evaluate(con, rule) == expected
    pg = transpile(compile_rule(rule), "postgres")
    assert duck.evaluate(con, rule, pg) == expected
    if sigma.emits_sigma(rule):
        docs = sigma_ref.parse(sigma.dump(sigma.to_sigma(rule)))
        assert sigma_ref.evaluate(docs, tables.get("events", [])) == expected


@pytest.mark.parametrize("rule_id", sorted(BY_ID))
def test_generated_data_fires_and_misses(rule_id: str) -> None:
    """The agreement test means little unless the generated rows sometimes fire
    the rule and sometimes do not."""
    rule = BY_ID[rule_id]
    seen: set[bool] = set()

    @settings(max_examples=300, database=None, deadline=None, phases=[Phase.generate])
    @given(tables_for(rule))
    def draw(tables: dict[str, list[dict[str, int | str | None]]]) -> None:
        hits = pyeval.evaluate(rule, tables)
        anchors = tables.get(rule.table, [])
        if hits:
            seen.add(True)
        if len(hits) < len(anchors):
            seen.add(False)

    draw()
    assert seen == {True, False}
