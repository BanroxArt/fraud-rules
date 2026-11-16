---
name: fraud-rules
description: Choose, tune, compile and run vendor-neutral financial fraud detection rules (synthetic identity, bust-out, money mules, check kiting, structuring, account takeover, payee fraud, elder exploitation, foreign-agent-directed MSB payments) as SQL, Sigma or Python with the fraudrules package from this repo. Use when the user wants detection logic for one of these patterns, wants to turn a FinCEN or FFIEC red flag into a query, needs the SQL for a specific warehouse, or wants to test rules on synthetic data. Engineering checklist only, not legal advice.
---

# Fraud rules

You are helping someone detect fraud patterns in their own bank or fintech data. You produce queries and explain them; you do not decide whether activity is suspicious or whether a SAR or CTR must be filed. Say so if asked.

## 1. Find out what data they have

- Which of the three views can they build: `applications`, `transactions`, `events`? Point them at docs/data-model.md.
- Check the point-in-time fields. `counterparty_new`, `device_new`, `geo_new` and `customer_age` must be computed as of each row's timestamp. If they compute them over the whole table, warn that back-test results will be inflated.
- Amounts in integer cents, time in epoch seconds UTC, vocabulary columns lower case.
- For the foreign-agent rules (FA-001 to FA-008, FinCEN FIN-2026-Alert009), ask whether they are a principal MSB or a bank serving MSBs; the bank side usually lacks `directing_agent_id` and `in_agent_agreement`, so only FA-004, FA-005, FA-006 and FA-008 will fire.

## 2. Pick rules

- `python -m fraudrules list` and `python -m fraudrules show ID`. Match the user's concern to a category, then read each candidate's summary and false positives aloud to them.
- Prefer rules whose false-positive notes do not describe the user's core customers (for example ST-003 at a bank serving route businesses).

## 3. Tune

- Use `--set ID.param=value` or `load_pack(overrides=...)`. Never edit thresholds in compiled SQL by hand.
- Each rule's `tuning` list says what each parameter does. Recommend running defaults on historical data first and adjusting from the alert counts and outcomes, not from intuition.

## 4. Compile and run

- Warehouse: `python -m fraudrules sql --dialect postgres|snowflake|bigquery|duckdb --table transactions=schema.view`.
- SIEM: `python -m fraudrules sigma --out dir/`, then map `logsource: {product: fraudrules, category: events}` and field names in their Sigma pipeline. Only the account takeover rules and FA-007 are emitted as Sigma.
- Try it without real data: `python -m fraudrules synth --out data/ && python -m fraudrules run --data data/`.

## 5. Explain hits

For each hit give the rule id, the anchor row, the window or sequence that made it fire, and the rule's false-positive notes as the first things to check. Call them signals for review, never proof of fraud.

Do not paste real customer names, account numbers or SSNs into rules, tests or examples. Use synthetic data.
