# Rule format

A rule is one YAML file under `src/fraudrules/rules/<category>/`, named `<id lower-case>-<name>.yaml`. The structure is checked against [rule.schema.json](../src/fraudrules/rule.schema.json); field names, types and parameter references are checked by `fraudrules.loader`, which knows the table schemas. Both run on every load, so a rule that loads is a rule every backend can compile.

## Metadata

| key | required | notes |
|---|---|---|
| `id` | yes | `XX-000`. Two letters for the family, three digits. Never reused. |
| `name` | yes | kebab-case, unique, matches the file name. |
| `title` | yes | What the rule detects, in words an investigator would use. |
| `category` | yes | One of `synthetic-identity`, `first-party`, `money-mule`, `check-kiting`, `structuring`, `account-takeover`, `payee-fraud`, `elder-exploitation`, `foreign-agent`, `instant-payment`. |
| `severity` | yes | `low`, `medium`, `high`: how much a hit alone should weigh, not how bad the fraud is. |
| `status` | yes | `stable`, `test`, `experimental`, with Sigma's meanings. |
| `summary` | yes | One or two sentences stating exactly when the rule fires, with the default thresholds. |
| `rationale` | yes | Why the pattern indicates the fraud, and why the thresholds are where they are. |
| `sources` | yes | Primary sources only: regulations, regulator and FinCEN publications, Nacha rules. `publisher`, `title`, `url` (https), optional `note` saying what in the source supports the rule. |
| `false_positives` | yes | Known benign causes and how to tell them apart. |
| `tuning` | yes | One entry per parameter: what changing it does. |
| `params` | no | Defaults. Integers, strings, or durations (`90s`, `10m`, `24h`, `30d`). |

## Parameters

Any scalar or duration in the logic may be `$name`. Overrides replace defaults at load time (`load_pack(overrides={"ST-001": {"window": "1d"}})`, or `--set ST-001.window=1d` on the command line). An override for an undeclared parameter, or of the wrong type, is an error, and so is a declared parameter the logic never uses.

## Predicates

```yaml
{field: channel, eq: cash}
{field: channel, in: [cash, atm]}
{field: return_code, not_in: [R05, R07]}
{field: amount_cents, gte: $min_amount_cents}
{field: ts, lt: {field: account_opened_ts, plus: 90d}}   # same-row comparison, integers only
{field: payee_id, is_null: true}
{all: [...]}   {any: [...]}   {not: ...}
```

Operators: `eq ne lt lte gt gte in not_in is_null not_null`. Ordering operators only apply to integer columns. `plus` takes seconds, a duration, or a negated duration (`-30d`).

## Kinds

### filter

```yaml
table: transactions
filter: <predicate>
```

### aggregate

```yaml
table: transactions
aggregate:
  key: [account_id]            # one or more columns
  window: 72h                  # optional; omitted means everything up to the anchor
  anchor: <predicate>          # rows that can be flagged (default: every row)
  members: <predicate>         # rows aggregated (default: same as anchor)
  measures:
    name: {fn: count|sum|count_distinct|min|max, field: col, where: <predicate>}
  having: <having>
```

`having` is `all`/`any`/`not` over comparisons `{left: <term>, <op>: <term>}`. A term is a measure name, an integer or `$param`, `{measure: name, times: k}`, or `{anchor: column, times: k}`. `times` multiplies by an integer, which is how percentages stay exact: "the payment is at least 80% of the inflow" is `{left: {anchor: amount_cents, times: 100}, gte: {measure: inflow, times: 80}}`.

### sequence

```yaml
sequence:
  key: [customer_id]
  within: 72h
  steps:                        # 2 to 6; the last step is the anchor
    - {table: events, where: <predicate>}
    - {table: transactions, where: <predicate>}
  match:                        # optional
    - {step: 0, field: payee_id, anchor_field: counterparty_id}
```

Steps may read different tables if the key columns exist in each with the same type. `match` pins a column of an earlier step to a column of the anchor.

## Writing a new rule

1. Put the file in the right category directory; pick the next free id in the family.
2. Write `summary` so someone can predict every hit without reading the logic.
3. Cite the paragraph, advisory or rule, and say in `note` what in it supports the rule. If the rule is your own reasoning on top of a source, the rationale should say so.
4. Add a positive and a near-miss scenario to `fraudrules.synth.SCENARIOS`. The near miss should be on the wrong side of exactly one condition.
5. `python scripts/build_compiled.py`, then `make check`.
