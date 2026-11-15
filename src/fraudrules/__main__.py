"""Command line.

    python -m fraudrules list
    python -m fraudrules validate [RULES_DIR]
    python -m fraudrules show SI-001
    python -m fraudrules sql [--dialect postgres] [--rule ST-001] [--set ST-001.window=1d]
                             [--table transactions=analytics.fr_transactions]
    python -m fraudrules sigma [--rule AT-002] [--out DIR]
    python -m fraudrules synth --out DIR [--seed 7 --customers 300 --days 60]
    python -m fraudrules run --data DIR [--backend duckdb|python] [--rule ...]

``--set`` overrides a parameter for one rule and may be repeated. ``run`` reads
``applications.csv``, ``transactions.csv`` and ``events.csv`` from ``--data``
(any of them may be missing), with a header row, ``\\N`` for null, and prints
``rule_id,anchor_table,anchor_id`` for every hit.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from . import duck, pyeval, sigma
from .loader import RuleError, load_pack
from .model import Rule, Scalar
from .schema import TABLES
from .sql import DIALECTS, compile_pack, transpile


def _overrides(items: Sequence[str]) -> dict[str, dict[str, Scalar]]:
    out: dict[str, dict[str, Scalar]] = {}
    for item in items:
        target, _, value = item.partition("=")
        rule_id, _, param = target.partition(".")
        if not (rule_id and param and value):
            raise SystemExit(f"--set expects RULE.param=value, got {item!r}")
        v: Scalar = int(value) if value.lstrip("-").isdigit() else value
        out.setdefault(rule_id, {})[param] = v
    return out


def _select(args: argparse.Namespace) -> list[Rule]:
    rules = load_pack(args.rules, _overrides(args.set))
    if args.rule:
        wanted = set(args.rule)
        missing = wanted - {r.id for r in rules}
        if missing:
            raise SystemExit(f"unknown rule id(s): {sorted(missing)}")
        rules = [r for r in rules if r.id in wanted]
    return rules


def _read_csv(path: Path, table: str) -> list[dict[str, int | str | None]]:
    types = {c.name: c.type for c in TABLES[table]}
    rows: list[dict[str, int | str | None]] = []
    with path.open(newline="", encoding="utf-8") as f:
        for raw in csv.DictReader(f):
            row: dict[str, int | str | None] = {}
            for k, v in raw.items():
                if v == duck.NULL or v is None:
                    row[k] = None
                elif types.get(k) == "int":
                    row[k] = int(v)
                else:
                    row[k] = v
            rows.append(row)
    return rows


def main(argv: Sequence[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="fraudrules", description=__doc__.splitlines()[0])
    p.add_argument("--rules", help="rules directory (default: the bundled pack)")
    p.add_argument("--set", action="append", default=[], metavar="RULE.param=value")
    p.add_argument("--rule", action="append", default=[], metavar="ID")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    sub.add_parser("validate")
    sh = sub.add_parser("show")
    sh.add_argument("id")
    sq = sub.add_parser("sql")
    sq.add_argument("--dialect", choices=DIALECTS, default="duckdb")
    sq.add_argument("--table", action="append", default=[], metavar="canonical=actual")
    sg = sub.add_parser("sigma")
    sg.add_argument("--out", type=Path)
    sy = sub.add_parser("synth")
    sy.add_argument("--out", type=Path, required=True)
    sy.add_argument("--seed", type=int, default=7)
    sy.add_argument("--customers", type=int, default=300)
    sy.add_argument("--days", type=int, default=60)
    rn = sub.add_parser("run")
    rn.add_argument("--data", type=Path, required=True)
    rn.add_argument("--backend", choices=("duckdb", "python"), default="duckdb")
    args = p.parse_args(argv)

    try:
        if args.cmd == "synth":
            from .synth import generate

            ds = generate(args.seed, args.customers, args.days)
            args.out.mkdir(parents=True, exist_ok=True)
            for name, rows in ds.tables.items():
                duck.write_csv(args.out / f"{name}.csv", name, rows)
            planted = [{"rule_id": x.rule_id, "kind": x.kind, "rows": sorted(x.rows)} for x in ds.planted]
            (args.out / "planted.json").write_text(json.dumps(planted, indent=1) + "\n")
            print(json.dumps(ds.size()))
            return 0
        rules = _select(args)
        if args.cmd == "list":
            for r in rules:
                print(f"{r.id}  {r.kind:<9}  {r.severity:<6}  {r.status:<12}  {r.title}")
        elif args.cmd == "validate":
            print(f"ok: {len(rules)} rules")
        elif args.cmd == "show":
            match = [r for r in rules if r.id == args.id]
            if not match:
                raise SystemExit(f"unknown rule id {args.id!r}")
            r = match[0]
            print(f"{r.id} {r.name}\n{r.title}\n\n{r.rationale}\n\nparams: {r.params}")
            for s in r.sources:
                print(f"source: {s.publisher}, {s.title} <{s.url}>")
        elif args.cmd == "sql":
            names = dict(t.split("=", 1) for t in args.table)
            print(transpile(compile_pack(rules, names), args.dialect) + ";")
        elif args.cmd == "sigma":
            for r, text in sigma.iter_sigma(rules):
                if args.out:
                    args.out.mkdir(parents=True, exist_ok=True)
                    (args.out / f"{r.id.lower()}_{r.name.replace('-', '_')}.yml").write_text(text)
                else:
                    print(f"# {r.id}\n{text}---")
        elif args.cmd == "run":
            tables = {
                t: _read_csv(args.data / f"{t}.csv", t) for t in TABLES if (args.data / f"{t}.csv").is_file()
            }
            if args.backend == "python":
                hits = pyeval.run(rules, tables)
            else:
                con = duck.connect()
                duck.load(con, tables)
                hits = duck.run(con, rules)
            w = csv.writer(sys.stdout, lineterminator="\n")
            w.writerow(["rule_id", "anchor_table", "anchor_id"])
            for h in hits:
                w.writerow([h.rule_id, h.table, h.row_id])
    except RuleError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
