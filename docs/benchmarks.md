# Benchmarks

`make bench` (`bench/run.py`) generates a synthetic population with three planted positive and three near-miss cases per rule, runs the whole pack on the Python evaluator and on DuckDB, checks that both return the same hits, and prints per-rule counts.

Measured on 2026-11-16 on an 8-vCPU Linux VM, Python 3.13.5, DuckDB 2.0.0, default arguments (population 2,000, 90 days):

| | |
|---|---|
| rows | 836 applications, 108,125 transactions, 132,059 events |
| load and validate 40 rules (JSON Schema plus semantic checks) | 1.30 s |
| compile the pack to SQL | 0.5 ms |
| Python evaluator, all rules | 6.4 s |
| DuckDB: load the three tables from CSV | 0.95 s |
| DuckDB: all rules as one `UNION ALL` query | 0.11 s |
| planted positives caught | 120 of 120 |
| near misses flagged | 0 of 120 |

The Python evaluator is a reference, not a production engine: it walks every anchor row per rule. Use it for tests, for replaying a case, or for streams that fit in memory. Use the SQL for anything larger.

The background population (payroll, card spending, bills, ATM withdrawals, logins from a known device) produced no hits at all, which says only that ordinary synthetic behaviour does not trip the rules. Some rules report more hits than planted positives: an aggregate fires on every anchor in a qualifying window, and a few planted cases for one rule are also true positives for another (the IP-005 scenario is an older customer sending $15,000 by RTP to a new destination, which is also EL-001). It is not an estimate of false-positive rates on real portfolios; those depend on your customers, and every rule file lists the benign patterns to expect.
