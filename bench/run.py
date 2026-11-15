"""Time the Python evaluator and DuckDB on the synthetic population.

    PYTHONPATH=src python bench/run.py [population] [days]

Prints rows per table, the time to compile the pack, the time for each backend
to run all rules, and per-rule hit counts with the planted outcome.
"""

from __future__ import annotations

import sys
import time

from fraudrules import duck, pyeval
from fraudrules.loader import load_pack
from fraudrules.sql import compile_pack
from fraudrules.synth import generate


def timed(fn, *a):  # type: ignore[no-untyped-def]
    t = time.perf_counter()
    out = fn(*a)
    return out, time.perf_counter() - t


def main() -> None:
    population = int(sys.argv[1]) if len(sys.argv) > 1 else 2000
    days = int(sys.argv[2]) if len(sys.argv) > 2 else 90
    rules, t_load = timed(load_pack)
    sql, t_sql = timed(compile_pack, rules)
    ds, t_gen = timed(generate, 7, population, days, 3)
    print(f"rows: {ds.size()}  (generated in {t_gen:.2f}s)")
    print(f"load+validate {len(rules)} rules: {t_load * 1000:.0f} ms, compile SQL: {t_sql * 1000:.1f} ms")
    py_hits, t_py = timed(pyeval.run, rules, ds.tables)
    con = duck.connect()
    _, t_ld = timed(duck.load, con, ds.tables)
    rows, t_db = timed(lambda: con.execute(sql).fetchall())
    print(f"python evaluator, all rules: {t_py:.2f}s")
    print(f"duckdb load: {t_ld:.2f}s, all rules as one UNION ALL query: {t_db:.2f}s")
    assert sorted((h.rule_id, h.table, h.row_id) for h in py_hits) == sorted(
        (str(a), str(b), str(c)) for a, b, c in rows
    ), "backends disagree"
    print(f"\n{'rule':<8}{'hits':>6}{'planted+':>10}{'caught':>8}{'near-miss hits':>16}")
    for r in rules:
        hits = {h.row_id for h in py_hits if h.rule_id == r.id}
        pos = [p for p in ds.planted if p.rule_id == r.id and p.kind == "positive"]
        nm = [p for p in ds.planted if p.rule_id == r.id and p.kind == "near_miss"]
        caught = sum(bool(hits & p.rows) for p in pos)
        nm_hits = sum(bool(hits & p.rows) for p in nm)
        print(f"{r.id:<8}{len(hits):>6}{len(pos):>10}{caught:>8}{nm_hits:>16}")


if __name__ == "__main__":
    main()
