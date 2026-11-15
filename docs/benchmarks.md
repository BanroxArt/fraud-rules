# Benchmarks

`make bench` (`bench/run.py`) generates a synthetic population with three planted positive and three near-miss cases per rule, runs the whole pack on the Python evaluator and on DuckDB, checks that both return the same hits, and prints per-rule counts.

Measured on 2026-11-15 on an 8-vCPU Linux VM, Python 3.13.5, DuckDB 2.0.0, default arguments (population 2,000, 90 days):

| | |
|---|---|
| rows | 836 applications, 107,963 transactions, 132,029 events |
| load and validate 26 rules (JSON Schema plus semantic checks) | 0.97 s |
| compile the pack to SQL | 0.5 ms |
| Python evaluator, all rules | 5.2 s |
| DuckDB: load the three tables from CSV | 0.83 s |
| DuckDB: all rules as one `UNION ALL` query | 0.10 s |
| planted positives caught | 78 of 78 |
| near misses flagged | 0 of 78 |

The Python evaluator is a reference, not a production engine: it walks every anchor row per rule. Use it for tests, for replaying a case, or for streams that fit in memory. Use the SQL for anything larger.

The background population (payroll, card spending, bills, ATM withdrawals, logins from a known device) produced no hits at all, which says only that ordinary synthetic behaviour does not trip the rules. It is not an estimate of false-positive rates on real portfolios; those depend on your customers, and every rule file lists the benign patterns to expect.
