# Data model

Rules read three flat views. Build them from your own systems; the rules see nothing else. The conventions below are what make one rule mean the same thing in every engine.

- `id` is unique within its table and is what a hit reports.
- `ts` is integer seconds since the Unix epoch, UTC.
- Money is integer cents in `amount_cents`, always positive; `direction` says which way it moved.
- Flags are integers 0 or 1.
- Tokens (`ssn_token`, `phone_token`, `address_token`, `ip_token`, ...) are keyed hashes (for example HMAC-SHA-256 with a key that never leaves your environment) of normalized values. Rules only test them for equality. Normalize before hashing: case, whitespace and punctuation for names, E.164 for phones, USPS-standardized address with the unit.
- Vocabulary columns are lower case.

## Point-in-time fields

`counterparty_new`, `device_new`, `geo_new` and `customer_age` must be computed as of the row's `ts`, from rows with a smaller `ts`. `counterparty_new` is 1 when the account has no earlier entry with that counterparty in either direction. `device_new` is 1 when the customer has no earlier event from that device. `geo_new` is 1 when the customer has no earlier successful login from the IP's country. Computing any of them over the whole table leaks the future into the rule. `fraudrules.synth.Builder.finalize` shows the derivation.

For cash debits with no counterparty, set `counterparty_new` to 1 unless you record a reason; EL-001 relies on it.

## applications

| column | type | null | meaning |
|---|---|---|---|
| `id` | str | no | Row identifier, unique within the table. |
| `ts` | int | no | Event time, Unix epoch seconds, UTC. |
| `customer_id` | str | yes | Person or business the row belongs to. |
| `ssn_token` | str | no | Keyed hash of the SSN or ITIN given on the application. |
| `name_token` | str | no | Keyed hash of the normalized full name. |
| `dob_day` | int | no | Date of birth as days since 1970-01-01. |
| `phone_token` | str | yes | Keyed hash of the E.164 phone number. |
| `email_token` | str | yes | Keyed hash of the lower-cased email address. |
| `address_token` | str | yes | Keyed hash of the standardized address with unit. |
| `device_id` | str | yes | Device identifier from the application session. |
| `ip_token` | str | yes | Keyed hash of the source IP, or its /24 for IPv4. |
| `applicant_age` | int | no | Age in whole years on the application date. |
| `credit_file_age_months` | int | yes | Months since the oldest tradeline. |
| `au_tradelines` | int | yes | Authorized-user tradelines on the credit file. |
| `product` | str | no | card, loan, dda or bnpl. |

## transactions

| column | type | null | meaning |
|---|---|---|---|
| `id` | str | no | Row identifier, unique within the table. |
| `ts` | int | no | Event time, Unix epoch seconds, UTC. |
| `customer_id` | str | yes | Person or business the row belongs to. |
| `account_id` | str | no | Account the entry posted to. |
| `account_type` | str | no | dda, savings, card or loan. |
| `txn_type` | str | no | deposit, withdrawal, payment, purchase, cash_advance, transfer, return. |
| `direction` | str | no | in (credit to the account) or out (debit). |
| `channel` | str | no | ach, wire, rtp, check, cash, atm, card, p2p or internal. |
| `amount_cents` | int | no | Absolute amount in cents. |
| `counterparty_id` | str | yes | Other party: payee, originator or check maker. |
| `counterparty_type` | str | yes | individual, business, crypto_exchange, gift_card_merchant, money_transmitter. |
| `counterparty_new` | int | yes | 1 if no earlier entry with this counterparty. |
| `return_code` | str | yes | Return reason on a return entry, e.g. a Nacha R code. |
| `location_id` | str | yes | Branch or ATM for cash entries. |
| `account_opened_ts` | int | no | Account open time, epoch seconds. |
| `customer_age` | int | yes | Customer age in whole years at ts. |
| `credit_limit_cents` | int | yes | Credit limit at ts, card and credit lines only. |

## events

| column | type | null | meaning |
|---|---|---|---|
| `id` | str | no | Row identifier, unique within the table. |
| `ts` | int | no | Event time, Unix epoch seconds, UTC. |
| `customer_id` | str | yes | Person or business the row belongs to. |
| `account_id` | str | yes | Account the event refers to, if any. |
| `event_type` | str | no | See docs/data-model.md for the vocabulary. |
| `outcome` | str | no | success, failure or denied. |
| `channel` | str | no | web, mobile, ivr, call_center or branch. |
| `device_id` | str | yes | Device identifier. |
| `device_new` | int | yes | 1 if the device was never seen for this customer before ts. |
| `ip_token` | str | yes | Keyed hash of the source IP. |
| `geo_new` | int | yes | 1 if the IP country was never seen for this customer. |
| `payee_id` | str | yes | Payee affected by payee_added or payee_changed. |
| `customer_age` | int | yes | Customer age in whole years at ts. |

## Vocabularies

- `transactions.txn_type`: deposit, withdrawal, payment, purchase, cash_advance, transfer, return. A card payment is `payment` with direction `in` on the card account. A returned item is `return` with its `return_code` (Nacha R codes for ACH).
- `transactions.channel`: ach, wire, rtp, check, cash, atm, card, p2p, internal.
- `transactions.counterparty_type`: individual, business, crypto_exchange, gift_card_merchant, money_transmitter.
- `events.event_type`: login, mfa_challenge, password_reset, mfa_change, email_change, phone_change, address_change, device_enrolled, payee_added, payee_changed.
- `events.outcome`: success, failure, denied. An MFA prompt that timed out is `failure`.
- `events.channel`: web, mobile, ivr, call_center, branch.
- `applications.product`: card, loan, dda, bnpl.
