"""Run compiled SQL on DuckDB. Used by the tests, the benchmark and ``fraudrules run``."""

from __future__ import annotations

import csv
import tempfile
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING

from . import model as m
from .pyeval import Hit, Row
from .schema import TABLES, sql_type
from .sql import compile_rule

if TYPE_CHECKING:
    import duckdb

NULL = "\\N"


def connect() -> duckdb.DuckDBPyConnection:
    import duckdb

    return duckdb.connect(":memory:")


def create_tables(con: duckdb.DuckDBPyConnection) -> None:
    for name, cols in TABLES.items():
        body = ", ".join(f"{c.name} {sql_type(c.type)}" for c in cols)
        con.execute(f"CREATE OR REPLACE TABLE {name} ({body})")


def load(con: duckdb.DuckDBPyConnection, tables: Mapping[str, Sequence[Row]]) -> None:
    """Create the canonical tables and fill them from rows in memory."""
    create_tables(con)
    with tempfile.TemporaryDirectory() as tmp:
        for name, rows in tables.items():
            if not rows:
                continue
            path = Path(tmp) / f"{name}.csv"
            write_csv(path, name, rows)
            load_csv(con, name, path)


def write_csv(path: Path, table: str, rows: Iterable[Row]) -> None:
    cols = [c.name for c in TABLES[table]]
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for r in rows:
            w.writerow([NULL if (v := r.get(c)) is None else v for c in cols])


def load_csv(con: duckdb.DuckDBPyConnection, table: str, path: Path) -> None:
    cols = TABLES[table]
    types = "{" + ", ".join(f"'{c.name}': '{sql_type(c.type)}'" for c in cols) + "}"
    p = str(path).replace("'", "''")
    con.execute(
        f"INSERT INTO {table} SELECT * FROM read_csv('{p}', header = true, "
        f"columns = {types}, nullstr = '\\N', quote = '\"', escape = '\"')"
    )


def evaluate(con: duckdb.DuckDBPyConnection, rule: m.Rule, sql: str | None = None) -> set[str]:
    rows = con.execute(sql or compile_rule(rule)).fetchall()
    return {str(r[2]) for r in rows}


def run(con: duckdb.DuckDBPyConnection, rules: Iterable[m.Rule]) -> list[Hit]:
    out = []
    for rule in rules:
        out.extend(Hit(rule.id, rule.table, i) for i in evaluate(con, rule))
    return sorted(out)
