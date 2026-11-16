# Changelog

All notable changes to this project are listed here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses [semantic versioning](https://semver.org/) once it reaches 1.0.

## [Unreleased]

### Added

- Foreign-agent family, FA-001 to FA-008, from FinCEN FIN-2026-Alert009 (October 30, 2026) on payments that foreign agents direct US money transmitters to make: third parties outside the clearing agreement, the alert's jurisdictions, generic purposes without documents, payees without a settlement profile, round amounts, funds out within a day, agents that withhold information, large payments outside declared corridors. FA-007 is also emitted as Sigma.
- Eleven nullable MSB columns on `transactions` and the `agent_info_request` event type.

### Fixed

- `test_generated_data_fires_and_misses[MU-004]` failed in roughly one run in seven. MU-004 needs four rows on one key inside 72 hours, and Hypothesis kept most generated bursts shorter than that. Bursts are now forced to at least five rows half the time, and the check runs with a fixed seed so it gives the same answer on every machine.

## [0.1.0] - 2026-11-15

### Added

- Rule format: YAML with a JSON Schema, parameters with overrides, three kinds (`filter`, `aggregate`, `sequence`), cross-table sequences with step-to-anchor field matches.
- 26 rules: synthetic identity (SI-001 to SI-005), first-party and bust-out (FP-001 to FP-003), money mules (MU-001 to MU-004), check kiting (CK-001, CK-002), structuring (ST-001 to ST-003), account takeover (AT-001 to AT-005), payee fraud (PF-001, PF-002), elder financial exploitation (EL-001, EL-002).
- Backends: SQL (DuckDB, with Postgres, Snowflake and BigQuery through sqlglot), Sigma correlation rules for the event rules, and a Python reference evaluator.
- `fraudrules.sigma_ref`, a reference interpreter for the emitted Sigma subset.
- Synthetic data generator with a planted positive and near miss per rule.
- Tests: Hypothesis agreement across Python, DuckDB, transpiled Postgres SQL and the Sigma interpreter on data aimed at rule edges; planted ground truth on several seeds; semantics, loader, Sigma structure, dialect, CLI and compiled-artifact tests.
- `compiled/` with SQL per dialect and Sigma YAML; command line (`list`, `validate`, `show`, `sql`, `sigma`, `synth`, `run`); `make bench`.
