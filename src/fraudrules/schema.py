"""The canonical tables rules are written against.

Every rule reads one or more of three flat tables. They are views, not a storage
format: a bank builds them from its core, card, digital-banking and origination
systems, and the rules never see anything else. Keeping the surface this small is
what lets one rule compile to SQL, to Sigma and to Python and mean the same thing
in each.

Conventions shared by every table:

- ``id`` is unique within the table and is what a rule reports back.
- ``ts`` is the event time in integer seconds since the Unix epoch, UTC. Integer
  time keeps window arithmetic identical across SQL dialects (no interval types,
  no time zones) and in Python.
- Money is integer cents in ``amount_cents``. No floats anywhere.
- Flags are integers, 0 or 1, because BigQuery, Snowflake and Postgres disagree
  on boolean literals and casts.
- Tokens (``ssn_token``, ``phone_token`` and so on) are keyed hashes of the raw
  value, computed upstream. The rules only ever test them for equality.
- Point-in-time fields (``customer_age``, ``counterparty_new``, ``device_new``)
  must be computed as of ``ts`` from data available at that moment. Computing
  them from later data leaks the future into the rule and inflates any back-test.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

ColType = Literal["int", "str"]


@dataclass(frozen=True)
class Column:
    name: str
    type: ColType
    nullable: bool
    doc: str


def _c(name: str, type_: ColType, doc: str, nullable: bool = False) -> Column:
    return Column(name, type_, nullable, doc)


_COMMON = (
    _c("id", "str", "Row identifier, unique within the table."),
    _c("ts", "int", "Event time, Unix epoch seconds, UTC."),
    _c("customer_id", "str", "Person or business the row belongs to.", nullable=True),
)

APPLICATIONS = (
    *_COMMON,
    _c("ssn_token", "str", "Keyed hash of the SSN or ITIN given on the application."),
    _c("name_token", "str", "Keyed hash of the normalized full name."),
    _c("dob_day", "int", "Date of birth as days since 1970-01-01."),
    _c("phone_token", "str", "Keyed hash of the E.164 phone number.", nullable=True),
    _c("email_token", "str", "Keyed hash of the lower-cased email address.", nullable=True),
    _c("address_token", "str", "Keyed hash of the standardized address with unit.", True),
    _c("device_id", "str", "Device identifier from the application session.", True),
    _c("ip_token", "str", "Keyed hash of the source IP, or its /24 for IPv4.", True),
    _c("applicant_age", "int", "Age in whole years on the application date."),
    _c("credit_file_age_months", "int", "Months since the oldest tradeline.", True),
    _c("au_tradelines", "int", "Authorized-user tradelines on the credit file.", True),
    _c("product", "str", "card, loan, dda or bnpl."),
)

TRANSACTIONS = (
    *_COMMON,
    _c("account_id", "str", "Account the entry posted to."),
    _c("account_type", "str", "dda, savings, card or loan."),
    _c("txn_type", "str", "deposit, withdrawal, payment, purchase, cash_advance, transfer, return."),
    _c("direction", "str", "in (credit to the account) or out (debit)."),
    _c("channel", "str", "ach, wire, rtp, fednow, check, cash, atm, card, p2p or internal."),
    _c("amount_cents", "int", "Absolute amount in cents."),
    _c("counterparty_id", "str", "Other party: payee, originator or check maker.", True),
    _c(
        "counterparty_type",
        "str",
        "individual, business, crypto_exchange, gift_card_merchant, money_transmitter.",
        True,
    ),
    _c("counterparty_new", "int", "1 if no earlier entry with this counterparty.", True),
    _c("return_code", "str", "Return reason on a return entry, e.g. a Nacha R code.", True),
    _c("location_id", "str", "Branch or ATM for cash entries.", True),
    _c("account_opened_ts", "int", "Account open time, epoch seconds."),
    _c("customer_age", "int", "Customer age in whole years at ts.", True),
    _c("credit_limit_cents", "int", "Credit limit at ts, card and credit lines only.", True),
    # Money services business columns. Null for ordinary retail rows.
    _c("customer_segment", "str", "retail, business or msb.", True),
    _c(
        "directing_agent_id",
        "str",
        "Foreign agent that instructed this payment, when an MSB pays on an agent's instruction.",
        True,
    ),
    _c(
        "in_agent_agreement",
        "int",
        "1 if the payee is the directing agent or a party named in its clearing agreement.",
        True,
    ),
    _c("counterparty_country", "str", "ISO 3166-1 alpha-2 country of the payee, lower case.", True),
    _c(
        "counterparty_sector",
        "str",
        "general_trading, textile, import_export, exchange_house, bank, msb or other.",
        True,
    ),
    _c("counterparty_formed_ts", "int", "Payee's registration or incorporation date.", True),
    _c("counterparty_web_presence", "int", "1 if the payee had a findable web presence at ts.", True),
    _c("purpose", "str", "Stated payment purpose, normalized to a short lower-case code.", True),
    _c("supporting_docs", "int", "1 if an invoice, contract or order was on file before ts.", True),
    _c("round_amount", "int", "1 if amount_cents is within $10 of a multiple of $1,000.", True),
    _c(
        "corridor_expected",
        "int",
        "1 if counterparty_country is a corridor the customer declared for this account.",
        True,
    ),
    # Instant-payment columns. Null where the bank does not know them.
    _c(
        "payee_self",
        "int",
        "1 if the bank verified the payee account is held by this customer (me-to-me).",
        True,
    ),
    _c("counterparty_linked_ts", "int", "When the payee account was added or linked as a destination.", True),
    _c("counterparty_opened_ts", "int", "Open date of the payee account, when the bank knows it.", True),
)

EVENTS = (
    *_COMMON,
    _c("account_id", "str", "Account the event refers to, if any.", True),
    _c("event_type", "str", "See docs/data-model.md for the vocabulary."),
    _c("outcome", "str", "success, failure or denied."),
    _c("channel", "str", "web, mobile, ivr, call_center or branch."),
    _c("device_id", "str", "Device identifier.", True),
    _c("device_new", "int", "1 if the device was never seen for this customer before ts.", True),
    _c("ip_token", "str", "Keyed hash of the source IP.", True),
    _c("geo_new", "int", "1 if the IP country was never seen for this customer.", True),
    _c("payee_id", "str", "Payee affected by payee_added or payee_changed.", True),
    _c("customer_age", "int", "Customer age in whole years at ts.", True),
)

TABLES: dict[str, tuple[Column, ...]] = {
    "applications": APPLICATIONS,
    "transactions": TRANSACTIONS,
    "events": EVENTS,
}


def column(table: str, name: str) -> Column:
    for col in TABLES[table]:
        if col.name == name:
            return col
    raise KeyError(f"{table}.{name}")


def has_column(table: str, name: str) -> bool:
    return any(c.name == name for c in TABLES[table])


def sql_type(t: ColType) -> str:
    return "BIGINT" if t == "int" else "VARCHAR"
