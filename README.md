# fraud-rules

Detection rules for financial fraud, written once in a small YAML format and compiled to three targets that give the same answer: portable SQL (tested on DuckDB, transpiled to Postgres, Snowflake and BigQuery), Sigma for the log-shaped rules, and a plain Python evaluator that defines the semantics.

40 rules across synthetic identity, first-party bust-out, money mules, check kiting, structuring, account takeover, payee fraud, elder financial exploitation, payments directed by the foreign agents of US money transmitters, and mule and takeover patterns on instant payment rails (RTP, FedNow, P2P). Every rule cites the regulation, FinCEN advisory, FFIEC guidance or Nacha rule it is built from, and lists its known false positives and the parameters to tune.

Built and maintained by Art Akopian, CEO of [Banrox](https://banrox.com). Banrox builds consumer credit and fraud-prevention software and publishes the general-purpose pieces.

> **Engineering checklist, not legal advice.** The rules flag activity for a human to review. They do not decide whether activity is suspicious, whether a SAR or CTR is due, or whether an institution meets its BSA, Nacha or Regulation CC obligations. Thresholds are starting points; set them from your own data and your own risk assessment. Every rule has been tested on synthetic data only.

## Why another rule format

Fraud teams keep the same patterns in three places: SQL in the warehouse for investigations and back-tests, a SIEM for digital-banking events, and application code for real-time decisions. The three copies drift. A window that is `<=` in one and `<` in another, a null that is false in SQL and true in Python, and the back-test no longer says anything about production.

Here a rule is data. One file compiles to every target, and the test suite checks on every commit that every target flags exactly the same rows:

- Hypothesis generates tables aimed at each rule's edges (values one either side of each threshold, timestamps one second either side of each window boundary, nulls) and asserts that the Python evaluator, DuckDB running the generated SQL, DuckDB running the SQL after transpiling to Postgres, and a reference interpreter running the emitted Sigma YAML all return the same set.
- A synthetic data generator plants, for every rule, a positive case it must catch and a near miss it must not (one dollar, one second or one step on the wrong side), on top of a background population of ordinary customers.

## The rules

| id | title | kind | targets | sources |
|---|---|---|---|---|
| [AT-001](src/fraudrules/rules/account-takeover/at-001-reset-new-device-payee.yaml) | Credential reset, then a login from a new device, then a new payee | sequence | SQL, Python, Sigma | FFIEC, FinCEN |
| [AT-002](src/fraudrules/rules/account-takeover/at-002-failed-logins-many-ips.yaml) | Failed logins against one customer from many IP addresses | aggregate | SQL, Python, Sigma | FFIEC, FinCEN |
| [AT-003](src/fraudrules/rules/account-takeover/at-003-contact-change-then-payee.yaml) | Email, phone or address change followed by a payee change | sequence | SQL, Python, Sigma | FFIEC, FinCEN |
| [AT-004](src/fraudrules/rules/account-takeover/at-004-mfa-push-fatigue.yaml) | Burst of denied or ignored MFA prompts for one customer | aggregate | SQL, Python, Sigma | FFIEC |
| [AT-005](src/fraudrules/rules/account-takeover/at-005-new-geo-device-then-mfa-change.yaml) | Login from a new device in a new country, then an MFA change | sequence | SQL, Python, Sigma | FFIEC, FinCEN |
| [CK-001](src/fraudrules/rules/check-kiting/ck-001-circular-checks.yaml) | Checks flowing both ways with the same counterparty within days | aggregate | SQL, Python | FFIEC, eCFR |
| [CK-002](src/fraudrules/rules/check-kiting/ck-002-deposit-then-drain.yaml) | Check deposits withdrawn before they could have cleared | aggregate | SQL, Python | FinCEN, eCFR |
| [EL-001](src/fraudrules/rules/elder-exploitation/el-001-older-adult-large-new-outflow.yaml) | Large wire or cash withdrawal by an older adult to a new counterparty | filter | SQL, Python | Federal Reserve, FinCEN |
| [EL-002](src/fraudrules/rules/elder-exploitation/el-002-older-adult-scam-rails.yaml) | Older adult paying crypto exchanges, gift card sellers or money transmitters repeatedly | aggregate | SQL, Python | Federal Reserve, FinCEN |
| [FA-001](src/fraudrules/rules/foreign-agent/fa-001-third-party-outside-agreement.yaml) | Agent-directed payment to a third party the clearing agreement does not cover | filter | SQL, Python | FinCEN |
| [FA-002](src/fraudrules/rules/foreign-agent/fa-002-third-party-alert-jurisdictions.yaml) | Agent regularly directs third-party payments to the jurisdictions the alert names | aggregate | SQL, Python | FinCEN |
| [FA-003](src/fraudrules/rules/foreign-agent/fa-003-vague-purpose-no-documents.yaml) | Third-party payment with a generic purpose and no invoice, contract or order on file | filter | SQL, Python | FinCEN |
| [FA-004](src/fraudrules/rules/foreign-agent/fa-004-payee-without-settlement-profile.yaml) | MSB pays a foreign company that does not look like a settlement counterparty | filter | SQL, Python | FinCEN |
| [FA-005](src/fraudrules/rules/foreign-agent/fa-005-repeated-round-amounts.yaml) | MSB sends repeated round-dollar wires abroad | aggregate | SQL, Python | FinCEN |
| [FA-006](src/fraudrules/rules/foreign-agent/fa-006-same-day-pass-through-abroad.yaml) | Funds credited to an MSB account leave for a foreign third party within a day | sequence | SQL, Python | FinCEN |
| [FA-007](src/fraudrules/rules/foreign-agent/fa-007-agent-withholds-information.yaml) | Foreign agent ignores or refuses repeated requests for documents or due diligence | aggregate | SQL, Python, Sigma | FinCEN |
| [FA-008](src/fraudrules/rules/foreign-agent/fa-008-large-payment-outside-corridors.yaml) | Large MSB payment to an alert jurisdiction the customer never said it serves | filter | SQL, Python | FinCEN |
| [FP-001](src/fraudrules/rules/first-party/fp-001-sleeper-line-maxout.yaml) | Seasoned card account draws most of its credit line within a week | aggregate | SQL, Python | FFIEC, Federal Reserve |
| [FP-002](src/fraudrules/rules/first-party/fp-002-payment-spend-return.yaml) | Card payment spent before it clears, then returned unpaid | sequence | SQL, Python | Federal Reserve, Nacha |
| [FP-003](src/fraudrules/rules/first-party/fp-003-payment-stacking.yaml) | Several card payments in a few days adding up to more than the limit | aggregate | SQL, Python | Federal Reserve, Nacha |
| [IP-001](src/fraudrules/rules/instant-payment/ip-001-instant-in-instant-out.yaml) | New account sends an instant credit straight back out within minutes | aggregate | SQL, Python | Federal Reserve, TCH, FFIEC, FinCEN |
| [IP-002](src/fraudrules/rules/instant-payment/ip-002-instant-fan-in.yaml) | Young account receives instant credits from many senders in a day | aggregate | SQL, Python | Federal Reserve, FFIEC, FinCEN |
| [IP-003](src/fraudrules/rules/instant-payment/ip-003-instant-fan-out.yaml) | Instant payments to several first-time payees within an hour | aggregate | SQL, Python | Federal Reserve, FinCEN, FFIEC |
| [IP-004](src/fraudrules/rules/instant-payment/ip-004-new-payee-after-device-or-sim-change.yaml) | First instant payment to a new payee within a day of a new device or SIM change | sequence | SQL, Python | FBI IC3, FFIEC, FinCEN |
| [IP-005](src/fraudrules/rules/instant-payment/ip-005-me-to-me-newly-linked.yaml) | Large transfer to the customer's own account at another bank, linked days ago | filter | SQL, Python | FBI IC3, Federal Reserve, FinCEN |
| [IP-006](src/fraudrules/rules/instant-payment/ip-006-old-account-to-new-own-account.yaml) | Long-held account sends a large sum to an account in the same name opened days ago | filter | SQL, Python | FBI IC3, Federal Reserve, FFIEC |
| [MU-001](src/fraudrules/rules/money-mule/mu-001-rapid-pass-through.yaml) | New account sends out most of what it received in the last three days | aggregate | SQL, Python | FFIEC, FinCEN, Nacha |
| [MU-002](src/fraudrules/rules/money-mule/mu-002-fan-in-new-account.yaml) | New personal account credited by many unrelated individuals | aggregate | SQL, Python | FFIEC, FinCEN, Nacha |
| [MU-003](src/fraudrules/rules/money-mule/mu-003-fan-out-new-payees.yaml) | Funds sent to several first-time payees within two days | aggregate | SQL, Python | FFIEC, FinCEN |
| [MU-004](src/fraudrules/rules/money-mule/mu-004-p2p-in-cash-out.yaml) | P2P credits from several people followed by a cash withdrawal | aggregate | SQL, Python | FFIEC, FinCEN |
| [PF-001](src/fraudrules/rules/payee-fraud/pf-001-payee-change-then-payment.yaml) | Payment to a payee whose bank details changed in the last three days | sequence | SQL, Python | FinCEN, Nacha |
| [PF-002](src/fraudrules/rules/payee-fraud/pf-002-outsized-first-payment.yaml) | First payment to a new payee far larger than any recent known payment | aggregate | SQL, Python | FinCEN, Nacha |
| [SI-001](src/fraudrules/rules/synthetic-identity/si-001-ssn-multiple-identities.yaml) | One SSN presented with more than one name or date of birth | aggregate | SQL, Python | FFIEC, Federal Reserve |
| [SI-002](src/fraudrules/rules/synthetic-identity/si-002-phone-shared-across-ssns.yaml) | Phone number shared by several SSNs within a short period | aggregate | SQL, Python | FFIEC, Federal Reserve |
| [SI-003](src/fraudrules/rules/synthetic-identity/si-003-address-shared-across-ssns.yaml) | Mailing address shared by many SSNs within six months | aggregate | SQL, Python | FFIEC, Federal Reserve |
| [SI-004](src/fraudrules/rules/synthetic-identity/si-004-device-across-identities.yaml) | One device submitting applications for several identities | aggregate | SQL, Python | FFIEC, Federal Reserve |
| [SI-005](src/fraudrules/rules/synthetic-identity/si-005-thin-file-piggyback.yaml) | Adult applicant with a thin credit file built on authorized-user tradelines | filter | SQL, Python | Federal Reserve |
| [ST-001](src/fraudrules/rules/structuring/st-001-cash-aggregate-over-ctr.yaml) | Cash deposits each at or under $10,000 that together exceed it in a day | aggregate | SQL, Python | U.S. Code, eCFR |
| [ST-002](src/fraudrules/rules/structuring/st-002-just-below-threshold.yaml) | Repeated cash deposits just below the reporting threshold | aggregate | SQL, Python | FFIEC, eCFR |
| [ST-003](src/fraudrules/rules/structuring/st-003-multi-location-cash.yaml) | Cash deposits spread across several branches or ATMs in one day | aggregate | SQL, Python | FFIEC, eCFR |

`python -m fraudrules show SI-001` prints a rule's rationale, parameters and sources.

## A rule

```yaml
id: MU-001
name: rapid-pass-through
title: New account sends out most of what it received in the last three days
category: money-mule
params:
  window: 72h
  max_account_age: 90d
  min_inflow_cents: 200000
  pass_through_pct: 80
table: transactions
aggregate:
  key: [account_id]
  window: $window
  anchor:            # the row that gets flagged
    all:
      - {field: direction, eq: out}
      - {field: channel, in: [wire, ach, rtp, p2p]}
      - {field: ts, lt: {field: account_opened_ts, plus: $max_account_age}}
  members:           # the rows aggregated in (anchor.ts - window, anchor.ts]
    all:
      - {field: direction, eq: in}
      - {field: txn_type, ne: return}
  measures:
    inflow: {fn: sum, field: amount_cents}
  having:
    all:
      - {left: inflow, gte: $min_inflow_cents}
      - left: {anchor: amount_cents, times: 100}
        gte: {measure: inflow, times: $pass_through_pct}
# plus rationale, sources, false_positives and tuning (see the file)
```

There are three kinds: `filter` (one row), `aggregate` (a trailing window per key, compared with constants or with the anchor row itself), and `sequence` (ordered steps on one key inside a window, optionally across tables and with a field of an earlier step pinned to the anchor: the payee that was changed is the payee being paid). [docs/spec.md](docs/spec.md) is the format; [src/fraudrules/rule.schema.json](src/fraudrules/rule.schema.json) is its JSON Schema; [docs/semantics.md](docs/semantics.md) pins down windows, ordering and nulls.

Amounts are integer cents and time is integer epoch seconds. That is not an aesthetic choice: it is what makes `amount * 100 >= inflow * 80` and `b.ts > a.ts - 259200` mean the same thing in DuckDB, Snowflake, BigQuery, Postgres and Python, with no float rounding, interval types or time zones in the way.

## The data model

Rules read three flat views: `applications`, `transactions` and `events`. Each is a few dozen columns you build from your core, card, origination and digital-banking systems. [docs/data-model.md](docs/data-model.md) lists every column with its meaning, and is explicit about the point-in-time fields (`counterparty_new`, `device_new`, `geo_new`, `customer_age`) that must be computed from data available at the row's timestamp, or every back-test will look better than production.

## Use it

```sh
pip install 'fraudrules[sql] @ git+https://github.com/BanroxArt/fraud-rules'

python -m fraudrules list
python -m fraudrules sql --dialect snowflake --table transactions=risk.v_fr_transactions > pack.sql
python -m fraudrules --set ST-001.window=1d --rule ST-001 sql
python -m fraudrules sigma --out sigma/
python -m fraudrules synth --out data/ && python -m fraudrules run --data data/
```

Without installing anything: [compiled/](compiled) has every rule as SQL for each dialect and the Sigma rules as YAML, regenerated by `scripts/build_compiled.py` and checked by the test suite.

From Python:

```python
from fraudrules import load_pack, evaluate, compile_rule, transpile

rules = load_pack(overrides={"MU-001": {"pass_through_pct": 90}})
hits = evaluate(rules[0], {"events": rows})  # set of row ids
sql = transpile(compile_rule(rules[0]), "bigquery")
```

## Sigma

The five account takeover rules and FA-007 read only events and are emitted as Sigma: `event_count`, `value_count` and `temporal_ordered` correlations (Sigma correlation specification 2.x) over base rules with `logsource: {product: fraudrules, category: events}`. Map that log source and the field names to your SIEM with a pySigma pipeline. Two things to know:

- Sigma's `not` is true when a field is missing; the pack's `!=` is false on a null. The emitter writes `x != v` as `not (x: v or x: null)` so the two agree.
- Sigma leaves the output of a correlation to the backend. The reference interpreter in `fraudrules.sigma_ref` reports the event at which the condition first holds in the trailing timespan, which is what the SQL reports. Backends that report a group instead will alert once per group.

Rules over transactions and applications are not emitted as Sigma; they need joins and arithmetic a SIEM is the wrong place for.

## Foreign-agent-directed payments (FIN-2026-Alert009)

On October 30, 2026 FinCEN published [FIN-2026-Alert009](https://www.fincen.gov/system/files/2026-10/FinCEN-Alert-Foreign-Agent-Directed-Transactions.pdf). A US money transmitter settles with its foreign agents through its own bank accounts. FinCEN found agents using that channel to have the US principal wire money to unrelated companies abroad (UAE exchange houses, Chinese banks and trading companies, recipients across East Africa), labelled as "settlement", in round amounts, often within hours of the funds arriving, with little or no paperwork. The alert puts the suspicious payments it identified in BSA reporting from 2021 to 2025 at more than $8 billion, and asks for the key term `FIN2026FOREIGNAGENT` in SAR field 2 and the narrative.

FA-001 to FA-008 turn the alert's nine red flags for principal MSBs and five for banks that serve MSBs into rules. Each rule file cites the bullet it implements:

| alert red flag | rules |
|---|---|
| Payment to a third party not covered by the agent clearing agreement | FA-001 |
| Regular payments to third parties in China, the UAE, Egypt, Kenya, Uganda, Djibouti | FA-002, FA-008 (bank side) |
| Generic or unsupported purpose; missing or inconsistent documents | FA-003, FA-007 |
| Payee with no apparent relationship or without a bulk-MSB-funds profile (textile or general trading company, no web presence, newly created) | FA-004 |
| No evidence of due diligence on the payee; no licensing or AML information | FA-007 |
| Timing, volume or nature inconsistent with settlement | FA-006 (funds out within a day of receipt) |
| Round or near-round dollar amounts | FA-005 |

They need eleven extra nullable columns on `transactions` and one event type, listed in [docs/data-model.md](docs/data-model.md). A bank that only has its MSB customer's wires gets FA-004, FA-005, FA-006 and FA-008; a principal MSB that records which agent instructed each payment gets all eight. All eight are `experimental`: they encode the alert's wording, and nobody has tuned them on real MSB traffic yet.

## Instant payments (RTP, FedNow, P2P)

IP-001 to IP-006 are the mule and takeover patterns from the money-mule and account-takeover families, re-cut for rails that settle in seconds. The difference is the clock. On ACH a bank has hours or days between a credit and the money leaving; on RTP and FedNow the receiving bank's only chance is between the credit landing and the next push out, and after that the sender's bank can ask for the money back but cannot make the other bank return it. TCH's [Request for Return guidelines](https://www.theclearinghouse.org/-/media/New/TCH/Documents/Payment-Systems/RTP_Request_for_Returns_v02-19-2021.pdf) say an RTP payment is irrevocable once sent and the receiver has no obligation to return funds; FedNow has a return request message (camt.056) and a payment return (pacs.004), which is the same arrangement.

| pattern | rule |
|---|---|
| New account receives and pushes out within minutes | IP-001 |
| Many senders into one young account in a day (fan-in) | IP-002 |
| Several first-time payees in an hour (fan-out) | IP-003 |
| First-time payee right after a new-device login or a SIM change | IP-004 |
| Me-to-me transfer to a destination linked in the last three days | IP-005 |
| Large transfer from a long-held account to a same-name account opened days ago | IP-006 |

They use `fednow` as a channel value, a `sim_change` event type, and three nullable transaction columns (`payee_self`, `counterparty_linked_ts`, `counterparty_opened_ts`), all in [docs/data-model.md](docs/data-model.md). IP-005 and IP-006 stay quiet where the bank does not know who owns the destination account or when it was opened. All six are `experimental`: tested on synthetic data only, never tuned on real payment traffic.

What the networks do and do not provide, checked against primary sources in November 2026:

- FedNow has a $10 million network transaction limit and a $100,000 default that each participant can raise up to that limit ([FedNow Operating Procedures v3.7, October 2026](https://www.frbservices.org/wp-content/uploads/101326-fednow-service-operating-procedures.pdf)). It also gives participants a negative list and account activity thresholds. The negative list belongs to one participant and is checked on that participant's payments; it is not shared with other banks.
- Neither network flags an account at every bank automatically. Fraud reports go from one bank to the network and to the other bank in the payment, and what happens next is that bank's decision. These rules run inside one institution for that reason.
- Velocity limits and cooling-off periods are not a legal requirement under the GENIUS Act (Pub. L. 119-27). The windows here are detection parameters you tune, not compliance thresholds.

## Results on synthetic data

`make bench` on 2,000 synthetic customers over 90 days (108k transactions, 132k events, 836 applications) with planted cases for every rule: every planted positive caught, no near miss flagged, all rules in one DuckDB query in about 0.1 s and in the Python evaluator in about 5 s. [docs/benchmarks.md](docs/benchmarks.md) has the details. The background population is deliberately plain, so the zero false-positive count there says nothing about precision on real data. It shows the rules do what they claim on the cases they claim.

## Limits

- Rules see one institution's data. Most synthetic identity and mule signals are far stronger across institutions; consortium data is out of scope.
- The SQL uses self-joins for windows. That is what guarantees identical results across engines, and it is quadratic in rows per key inside a window. Per-account and per-customer keys are fine; for keys that can be huge (a shared device at a large fintech) cap group sizes upstream.
- `aggregate` cannot express absence ("no call-back within an hour"). Use a sequence with the call-back as a later rule, or compute it upstream.
- Snowflake and BigQuery outputs are produced by sqlglot and checked by parsing them back; only the DuckDB and Postgres forms are executed in CI.

## Sources

Every rule file lists its own. The pack draws on: 31 CFR 1010.311, 1010.313 and 1010.314 and 31 U.S.C. 5324 (currency reporting and structuring); 12 CFR 229.13 (Regulation CC exception holds); FinCEN advisories FIN-2011-A016 (account takeover), FIN-2016-A003 and FIN-2019-A005 (email compromise), FIN-2020-A003 (money mules), FIN-2022-A002 (elder financial exploitation) and alerts FIN-2023-Alert003 (mail theft-related check fraud) and FIN-2026-Alert009 (foreign-agent-directed transactions); the FFIEC BSA/AML Examination Manual, Appendix F; the FFIEC guidance Authentication and Access to Financial Institution Services and Systems (2021); the Interagency Statement on Elder Financial Exploitation (2024); Nacha's 2026 fraud monitoring rules; the Federal Reserve's Synthetic Identity Fraud Mitigation Toolkit; the FedNow Service Operating Procedures and fraud guide; The Clearing House's RTP Request for Return guidelines; and FBI IC3 public service announcements I-020822-PSA (SIM swapping) and I-091223-PSA ("Phantom Hacker" scams).

## Development

```sh
python -m pip install -e '.[dev]'
make check   # ruff, content lint, strict mypy, pytest (Hypothesis), compiled/ up to date
make bench
```

## License

MIT. See [LICENSE](LICENSE).
