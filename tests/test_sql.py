from __future__ import annotations

import pytest
import sqlglot
from conftest import RULES

from fraudrules import duck, pyeval
from fraudrules.sql import DIALECTS, compile_pack, compile_rule, lit, transpile
from fraudrules.synth import generate


@pytest.mark.parametrize("dialect", DIALECTS)
def test_every_rule_transpiles_and_parses_back(dialect: str) -> None:
    for r in RULES:
        out = transpile(compile_rule(r), dialect)
        assert sqlglot.parse_one(out, read=dialect) is not None, r.id


def test_pack_union_matches_per_rule_runs() -> None:
    ds = generate(seed=9, population=80, days=40)
    con = duck.connect()
    duck.load(con, ds.tables)
    rows = con.execute(compile_pack(RULES)).fetchall()
    union = sorted((str(a), str(b), str(c)) for a, b, c in rows)
    expected = sorted((h.rule_id, h.table, h.row_id) for h in pyeval.run(RULES, ds.tables))
    assert union == expected
    assert len(union) >= len(RULES)


def test_table_name_mapping() -> None:
    sql = compile_rule(RULES[0], {"events": "fraud.v_events"})
    assert "fraud.v_events" in sql
    assert " events " not in sql


def test_literal_quoting() -> None:
    assert lit("o'brien") == "'o''brien'"
    assert lit(-5) == "-5"
    with pytest.raises(TypeError):
        lit(True)
    with pytest.raises(ValueError):
        transpile("SELECT 1", "oracle-ish")


def test_no_dialect_specific_constructs() -> None:
    text = compile_pack(RULES).upper()
    for banned in ("INTERVAL", "RANGE BETWEEN", "OVER (", "::", "DATE_TRUNC", "NOW()"):
        assert banned not in text
