"""Synthetic bank data with planted ground truth.

Nothing here comes from a real institution. Identifiers are sequential, tokens
are random hex, people and businesses are numbers. The background population
behaves like ordinary retail customers (biweekly payroll, card spending, bills,
the odd ATM withdrawal, logins from a known phone), and on top of it every rule
gets two planted scenarios built on fresh customers and accounts:

- a *positive* that the rule must flag, and
- a *near miss* that looks like the positive but falls on the wrong side of
  one threshold, window or ordering, and that the rule must not flag.

The near misses are what make the tests worth something: a rule that flags
everything passes every positive.

Point-in-time fields (``counterparty_new``, ``device_new``, ``geo_new``) are
derived after generation, in timestamp order, the same way a correct upstream
view would derive them.
"""

from __future__ import annotations

import random
from collections import defaultdict
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Literal

T0 = 1767225600  # 2026-01-01T00:00:00Z
DAY = 86400
HOUR = 3600
MIN = 60

Row = dict[str, int | str | None]


@dataclass(frozen=True)
class Planted:
    rule_id: str
    kind: Literal["positive", "near_miss"]
    rows: frozenset[str]


@dataclass
class Dataset:
    tables: dict[str, list[Row]]
    planted: list[Planted]
    seed: int

    def size(self) -> dict[str, int]:
        return {k: len(v) for k, v in self.tables.items()}


@dataclass
class _Account:
    id: str
    customer: str
    type: str
    opened: int
    limit: int | None
    age: int


@dataclass
class Builder:
    rng: random.Random
    tables: dict[str, list[Row]] = field(
        default_factory=lambda: {"applications": [], "transactions": [], "events": []}
    )
    planted: list[Planted] = field(default_factory=list)
    _n: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    _capture: list[str] | None = None
    _ages: dict[str, int] = field(default_factory=dict)
    _country: dict[str, str] = field(default_factory=dict)

    def next_id(self, prefix: str) -> str:
        self._n[prefix] += 1
        return f"{prefix}{self._n[prefix]:07d}"

    def token(self, kind: str) -> str:
        return f"{kind}_{self.rng.getrandbits(64):016x}"

    def customer(self, age: int) -> str:
        cid = self.next_id("c")
        self._ages[cid] = age
        return cid

    def account(
        self, customer: str, type_: str = "dda", opened: int = T0 - 900 * DAY, limit: int | None = None
    ) -> _Account:
        return _Account(self.next_id("a"), customer, type_, opened, limit, self._ages[customer])

    def _add(self, table: str, row: Row) -> str:
        self.tables[table].append(row)
        rid = str(row["id"])
        if self._capture is not None:
            self._capture.append(rid)
        return rid

    def txn(
        self,
        acct: _Account,
        ts: int,
        txn_type: str,
        direction: str,
        channel: str,
        amount_cents: int,
        counterparty_id: str | None = None,
        counterparty_type: str | None = None,
        return_code: str | None = None,
        location_id: str | None = None,
    ) -> str:
        return self._add(
            "transactions",
            {
                "id": self.next_id("t"),
                "ts": ts,
                "customer_id": acct.customer,
                "account_id": acct.id,
                "account_type": acct.type,
                "txn_type": txn_type,
                "direction": direction,
                "channel": channel,
                "amount_cents": amount_cents,
                "counterparty_id": counterparty_id,
                "counterparty_type": counterparty_type,
                "counterparty_new": None,
                "return_code": return_code,
                "location_id": location_id,
                "account_opened_ts": acct.opened,
                "customer_age": acct.age,
                "credit_limit_cents": acct.limit,
            },
        )

    def event(
        self,
        customer: str,
        ts: int,
        event_type: str,
        outcome: str = "success",
        device_id: str | None = None,
        ip_token: str | None = None,
        country: str = "US",
        payee_id: str | None = None,
        account_id: str | None = None,
        channel: str = "mobile",
    ) -> str:
        eid = self.next_id("e")
        self._country[eid] = country
        return self._add(
            "events",
            {
                "id": eid,
                "ts": ts,
                "customer_id": customer,
                "account_id": account_id,
                "event_type": event_type,
                "outcome": outcome,
                "channel": channel,
                "device_id": device_id,
                "device_new": None,
                "ip_token": ip_token,
                "geo_new": None,
                "payee_id": payee_id,
                "customer_age": self._ages.get(customer),
            },
        )

    def application(
        self,
        ts: int,
        ssn: str,
        name: str,
        dob_day: int,
        age: int,
        phone: str | None = None,
        address: str | None = None,
        device: str | None = None,
        file_months: int | None = 120,
        au_lines: int | None = 0,
        product: str = "card",
    ) -> str:
        return self._add(
            "applications",
            {
                "id": self.next_id("p"),
                "ts": ts,
                "customer_id": None,
                "ssn_token": ssn,
                "name_token": name,
                "dob_day": dob_day,
                "phone_token": phone or self.token("ph"),
                "email_token": self.token("em"),
                "address_token": address or self.token("ad"),
                "device_id": device or self.token("dv"),
                "ip_token": self.token("ip"),
                "applicant_age": age,
                "credit_file_age_months": file_months,
                "au_tradelines": au_lines,
                "product": product,
            },
        )

    @contextmanager
    def plant(self, rule_id: str, kind: Literal["positive", "near_miss"]) -> Iterator[None]:
        self._capture = []
        try:
            yield
        finally:
            self.planted.append(Planted(rule_id, kind, frozenset(self._capture)))
            self._capture = None

    def finalize(self) -> None:
        txns = self.tables["transactions"]
        txns.sort(key=lambda r: (int(r["ts"] or 0), str(r["id"])))
        seen: dict[str, set[str]] = defaultdict(set)
        for r in txns:
            acct, cp = str(r["account_id"]), r["counterparty_id"]
            if cp is None:
                cash_out = r["direction"] == "out" and r["channel"] in ("cash", "atm")
                r["counterparty_new"] = 1 if cash_out else None
            else:
                r["counterparty_new"] = 0 if cp in seen[acct] else 1
                seen[acct].add(str(cp))
        events = self.tables["events"]
        events.sort(key=lambda r: (int(r["ts"] or 0), str(r["id"])))
        devices: dict[str, set[str]] = defaultdict(set)
        countries: dict[str, set[str]] = defaultdict(set)
        for r in events:
            cust = str(r["customer_id"])
            dev = r["device_id"]
            if dev is not None:
                r["device_new"] = 0 if dev in devices[cust] else 1
                devices[cust].add(str(dev))
            if r["event_type"] == "login" and r["outcome"] == "success":
                c = self._country[str(r["id"])]
                r["geo_new"] = 0 if c in countries[cust] else 1
                countries[cust].add(c)
        self.tables["applications"].sort(key=lambda r: (int(r["ts"] or 0), str(r["id"])))


# Background population ----------------------------------------------------


def _background(b: Builder, customers: int, days: int) -> None:
    rng = b.rng
    employers = [b.next_id("biz") for _ in range(max(5, customers // 40))]
    billers = [b.next_id("biz") for _ in range(30)]
    end = T0 + days * DAY
    for _ in range(customers):
        age = rng.randint(19, 88)
        cid = b.customer(age)
        dda = b.account(cid, "dda", T0 - rng.randint(200, 4000) * DAY)
        card = (
            b.account(cid, "card", T0 - rng.randint(200, 3000) * DAY, rng.choice([2000, 5000, 12000]) * 100)
            if rng.random() < 0.6
            else None
        )
        phone_dev = b.token("dv")
        home_ip = b.token("ip")
        # a login before the period so the usual device and country are known
        b.event(cid, T0 - rng.randint(5, 60) * DAY, "login", device_id=phone_dev, ip_token=home_ip)
        employer = rng.choice(employers)
        pay = rng.randint(1200, 4500) * 100
        my_billers = rng.sample(billers, 3)
        friends = [f"friend_{cid}_{i}" for i in range(rng.randint(0, 4))]
        t = T0 + rng.randint(0, 13) * DAY + 9 * HOUR
        while t < end:
            b.txn(dda, t, "deposit", "in", "ach", pay, employer, "business")
            t += 14 * DAY
        for d in range(days):
            day = T0 + d * DAY
            if rng.random() < 0.7:
                b.event(cid, day + rng.randint(7, 22) * HOUR, "login", device_id=phone_dev, ip_token=home_ip)
            if rng.random() < 0.02:
                b.event(cid, day + rng.randint(7, 22) * HOUR, "login", "failure", phone_dev, home_ip)
            if card is not None and rng.random() < 0.5:
                b.txn(
                    card,
                    day + rng.randint(8, 21) * HOUR,
                    "purchase",
                    "out",
                    "card",
                    rng.randint(5, 180) * 100,
                    b.next_id("m"),
                    "business",
                )
            if rng.random() < 0.05:
                b.txn(
                    dda,
                    day + rng.randint(8, 20) * HOUR,
                    "withdrawal",
                    "out",
                    "atm",
                    rng.choice([60, 100, 200, 300]) * 100,
                    location_id=f"atm{rng.randint(1, 40)}",
                )
            if rng.random() < 0.02:
                b.txn(
                    dda,
                    day + rng.randint(9, 16) * HOUR,
                    "deposit",
                    "in",
                    "cash",
                    rng.randint(50, 2500) * 100,
                    location_id=f"br{rng.randint(1, 12)}",
                )
            if friends and rng.random() < 0.04:
                b.txn(
                    dda,
                    day + rng.randint(9, 22) * HOUR,
                    "transfer",
                    rng.choice(["in", "out"]),
                    "p2p",
                    rng.randint(10, 150) * 100,
                    rng.choice(friends),
                    "individual",
                )
            if d % 30 == 3:
                for biller in my_billers:
                    b.txn(
                        dda,
                        day + 6 * HOUR,
                        "payment",
                        "out",
                        "ach",
                        rng.randint(40, 400) * 100,
                        biller,
                        "business",
                    )
            if card is not None and d % 30 == 20:
                assert card.limit is not None
                b.txn(
                    card,
                    day + 7 * HOUR,
                    "payment",
                    "in",
                    "ach",
                    rng.randint(100, max(101, card.limit // 400)) * 100,
                    f"self_{cid}",
                    "individual",
                )
        if rng.random() < 0.03:
            day = T0 + rng.randint(0, days - 1) * DAY + 10 * HOUR
            b.event(cid, day, "password_reset", device_id=phone_dev, ip_token=home_ip)
            b.event(cid, day + 5 * MIN, "login", device_id=phone_dev, ip_token=home_ip)
        if rng.random() < 0.02:
            day = T0 + rng.randint(0, days - 1) * DAY + 12 * HOUR
            b.event(cid, day, "payee_added", device_id=phone_dev, ip_token=home_ip, payee_id=b.next_id("py"))
    # new-to-bank applications, a few households sharing a phone or address
    for _ in range(customers // 3):
        ts = T0 + rng.randint(0, days * DAY - 1)
        age = rng.randint(19, 80)
        phone = b.token("ph")
        address = b.token("ad")
        b.application(
            ts,
            b.token("ssn"),
            b.token("nm"),
            3650 + rng.randint(0, 20000),
            age,
            phone,
            address,
            file_months=rng.randint(24, 400) if age > 22 else rng.randint(6, 60),
            au_lines=rng.choice([0, 0, 0, 1, 2]),
        )
        if rng.random() < 0.15:  # spouse on the same phone and address
            b.application(
                ts + rng.randint(1, 20) * DAY,
                b.token("ssn"),
                b.token("nm"),
                3650 + rng.randint(0, 20000),
                age,
                phone,
                address,
            )


# Planted scenarios ----------------------------------------------------------

Scenario = Callable[[Builder, int, bool], None]


def _apps_sharing(
    b: Builder,
    t: int,
    n: int,
    gap: int,
    *,
    phone: str | None = None,
    address: str | None = None,
    device: str | None = None,
) -> None:
    for i in range(n):
        b.application(t + i * gap, b.token("ssn"), b.token("nm"), 9000 + i, 35, phone, address, device)


def si001(b: Builder, t: int, pos: bool) -> None:
    ssn, dob = b.token("ssn"), 8100
    b.application(t, ssn, b.token("nm"), dob, 34)
    name2 = b.token("nm") if pos else b.tables["applications"][-1]["name_token"]
    b.application(t + 30 * DAY, ssn, str(name2), dob, 34)


def si002(b: Builder, t: int, pos: bool) -> None:
    phone = b.token("ph")
    _apps_sharing(b, t, 2, 10 * DAY, phone=phone)
    gap = 20 * DAY if pos else 100 * DAY
    b.application(t + 10 * DAY + gap, b.token("ssn"), b.token("nm"), 9100, 40, phone)


def si003(b: Builder, t: int, pos: bool) -> None:
    _apps_sharing(b, t, 4 if pos else 3, 15 * DAY, address=b.token("ad"))


def si004(b: Builder, t: int, pos: bool) -> None:
    _apps_sharing(b, t, 3 if pos else 2, 3 * DAY, device=b.token("dv"))


def si005(b: Builder, t: int, pos: bool) -> None:
    b.application(t, b.token("ssn"), b.token("nm"), 5000, 41 if pos else 22, file_months=14, au_lines=4)


def fp001(b: Builder, t: int, pos: bool) -> None:
    card = b.account(b.customer(38), "card", t - 400 * DAY, 500000)
    for i, amt in enumerate((180000, 160000, 130000) if pos else (180000, 130000, 90000)):
        b.txn(card, t + i * 2 * DAY, "purchase" if i else "cash_advance", "out", "card", amt, b.next_id("m"))


def fp002(b: Builder, t: int, pos: bool) -> None:
    card = b.account(b.customer(45), "card", t - 300 * DAY, 300000)
    b.txn(card, t, "payment", "in", "ach", 200000, "ext_acct_x", "individual")
    b.txn(card, t + DAY, "purchase", "out", "card", 150000, b.next_id("m"), "business")
    b.txn(
        card,
        t + (5 if pos else 12) * DAY,
        "return",
        "out",
        "ach",
        200000,
        "ext_acct_x",
        "individual",
        return_code="R01",
    )


def fp003(b: Builder, t: int, pos: bool) -> None:
    card = b.account(b.customer(29), "card", t - 500 * DAY, 300000)
    amts = (100000, 120000, 110000) if pos else (160000, 170000)
    for i, a in enumerate(amts):
        b.txn(card, t + i * DAY, "payment", "in", "ach", a, f"ext_{i}", "individual")


def mu001(b: Builder, t: int, pos: bool) -> None:
    acct = b.account(b.customer(23), "dda", t - (20 if pos else 200) * DAY)
    b.txn(acct, t, "deposit", "in", "ach", 400000, b.next_id("biz"), "business")
    b.txn(acct, t + 20 * HOUR, "transfer", "in", "p2p", 100000, b.next_id("ind"), "individual")
    b.txn(acct, t + 40 * HOUR, "transfer", "out", "wire", 450000, b.next_id("ind"), "individual")


def mu002(b: Builder, t: int, pos: bool) -> None:
    acct = b.account(b.customer(27), "dda", t - 10 * DAY)
    for i in range(6 if pos else 4):
        b.txn(
            acct, t + i * 18 * HOUR, "transfer", "in", "p2p", 45000 + i * 1000, b.next_id("ind"), "individual"
        )


def mu003(b: Builder, t: int, pos: bool) -> None:
    acct = b.account(b.customer(33))
    for i in range(5):
        b.txn(
            acct,
            t + i * 6 * HOUR,
            "transfer",
            "out",
            "rtp",
            150000 if pos else 50000,
            b.next_id("ind"),
            "individual",
        )


def mu004(b: Builder, t: int, pos: bool) -> None:
    acct = b.account(b.customer(24))
    for i in range(4):
        b.txn(acct, t + i * 5 * HOUR, "transfer", "in", "p2p", 50000, b.next_id("ind"), "individual")
    b.txn(acct, t + 26 * HOUR, "withdrawal", "out", "atm", 160000 if pos else 60000, location_id="atm7")


def ck001(b: Builder, t: int, pos: bool) -> None:
    acct = b.account(b.customer(51))
    other = b.next_id("ext")
    b.txn(acct, t, "deposit", "in", "check", 300000, other, "individual")
    b.txn(acct, t + DAY, "withdrawal", "out", "check", 310000, other, "individual")
    b.txn(acct, t + 2 * DAY, "deposit", "in", "check", 340000, other, "individual")
    if pos:
        b.txn(acct, t + 3 * DAY, "withdrawal", "out", "check", 350000, other, "individual")


def ck002(b: Builder, t: int, pos: bool) -> None:
    acct = b.account(b.customer(31))
    b.txn(acct, t, "deposit", "in", "check", 400000, b.next_id("ext"), "individual")
    b.txn(acct, t + 20 * HOUR, "withdrawal", "out", "cash", 300000 if pos else 100000, location_id="br3")


def st001(b: Builder, t: int, pos: bool) -> None:
    acct = b.account(b.customer(47))
    b.txn(acct, t, "deposit", "in", "cash", 600000, location_id="br2")
    b.txn(acct, t + 6 * HOUR, "deposit", "in", "cash", 500000 if pos else 300000, location_id="br2")


def st002(b: Builder, t: int, pos: bool) -> None:
    acct = b.account(b.customer(52))
    for d, a in ((0, 950000), (4, 980000), (9, 920000 if pos else 850000)):
        b.txn(acct, t + d * DAY, "deposit", "in", "cash", a, location_id="br5")


def st003(b: Builder, t: int, pos: bool) -> None:
    acct = b.account(b.customer(39))
    branches = ("br1", "br4", "br9") if pos else ("br1", "br4", "br4")
    for i, br in enumerate(branches):
        b.txn(acct, t + i * 3 * HOUR, "deposit", "in", "cash", 300000, location_id=br)


def _known_device(b: Builder, cid: str, t: int) -> tuple[str, str]:
    dev, ip = b.token("dv"), b.token("ip")
    b.event(cid, t - 20 * DAY, "login", device_id=dev, ip_token=ip)
    return dev, ip


def at001(b: Builder, t: int, pos: bool) -> None:
    cid = b.customer(44)
    dev, _ = _known_device(b, cid, t)
    b.event(cid, t, "password_reset", channel="ivr")
    b.event(cid, t + 2 * HOUR, "login", device_id=b.token("dv") if pos else dev, ip_token=b.token("ip"))
    b.event(cid, t + 3 * HOUR, "payee_added", device_id=dev, payee_id=b.next_id("py"))


def at002(b: Builder, t: int, pos: bool) -> None:
    cid = b.customer(36)
    ips = [b.token("ip") for _ in range(6 if pos else 2)]
    for i in range(6):
        b.event(cid, t + i * 40, "login", "failure", b.token("dv"), ips[i % len(ips)], channel="web")


def at003(b: Builder, t: int, pos: bool) -> None:
    cid = b.customer(58)
    dev, ip = _known_device(b, cid, t)
    payee = b.next_id("py")
    if pos:
        b.event(cid, t, "email_change", device_id=dev, ip_token=ip)
        b.event(cid, t + 10 * HOUR, "payee_changed", device_id=dev, ip_token=ip, payee_id=payee)
    else:  # same two events, wrong order
        b.event(cid, t, "payee_changed", device_id=dev, ip_token=ip, payee_id=payee)
        b.event(cid, t + 10 * HOUR, "email_change", device_id=dev, ip_token=ip)


def at004(b: Builder, t: int, pos: bool) -> None:
    cid = b.customer(49)
    dev, ip = _known_device(b, cid, t)
    for i in range(6 if pos else 4):
        b.event(cid, t + i * 45, "mfa_challenge", "denied", dev, ip)


def at005(b: Builder, t: int, pos: bool) -> None:
    cid = b.customer(37)
    _known_device(b, cid, t)
    b.event(
        cid,
        t,
        "login",
        device_id=b.token("dv"),
        ip_token=b.token("ip"),
        country="RO" if pos else "US",
        channel="web",
    )
    b.event(cid, t + 20 * MIN, "mfa_change", channel="web")


def pf001(b: Builder, t: int, pos: bool) -> None:
    cid = b.customer(55)
    acct = b.account(cid, "dda")
    payee, other = b.next_id("py"), b.next_id("py")
    b.txn(acct, t - 40 * DAY, "payment", "out", "wire", 2500000, payee, "business")
    b.event(cid, t, "payee_changed", payee_id=payee if pos else other, device_id=b.token("dv"))
    b.txn(acct, t + 2 * DAY, "payment", "out", "wire", 2500000, payee, "business")


def pf002(b: Builder, t: int, pos: bool) -> None:
    acct = b.account(b.customer(46))
    payees = [b.next_id("biz") for _ in range(3)]
    for i, p in enumerate(payees):
        b.txn(acct, t - 85 * DAY + i * DAY, "payment", "out", "ach", 150000, p, "business")
        b.txn(acct, t - 40 * DAY + i * 7 * DAY, "payment", "out", "ach", 200000 - i * 20000, p, "business")
    b.txn(acct, t, "payment", "out", "wire", 900000 if pos else 500000, b.next_id("biz"), "business")


def el001(b: Builder, t: int, pos: bool) -> None:
    acct = b.account(b.customer(72 if pos else 55))
    b.txn(acct, t, "transfer", "out", "wire", 1500000, b.next_id("ind"), "individual")


def el002(b: Builder, t: int, pos: bool) -> None:
    acct = b.account(b.customer(68))
    for i in range(3 if pos else 2):
        b.txn(acct, t + i * 2 * DAY, "payment", "out", "ach", 200000, b.next_id("cx"), "crypto_exchange")


SCENARIOS: dict[str, Scenario] = {
    "SI-001": si001,
    "SI-002": si002,
    "SI-003": si003,
    "SI-004": si004,
    "SI-005": si005,
    "FP-001": fp001,
    "FP-002": fp002,
    "FP-003": fp003,
    "MU-001": mu001,
    "MU-002": mu002,
    "MU-003": mu003,
    "MU-004": mu004,
    "CK-001": ck001,
    "CK-002": ck002,
    "ST-001": st001,
    "ST-002": st002,
    "ST-003": st003,
    "AT-001": at001,
    "AT-002": at002,
    "AT-003": at003,
    "AT-004": at004,
    "AT-005": at005,
    "PF-001": pf001,
    "PF-002": pf002,
    "EL-001": el001,
    "EL-002": el002,
}


def generate(seed: int = 7, customers: int = 300, days: int = 60, copies: int = 1) -> Dataset:
    """Background population plus ``copies`` positive and near-miss scenarios per rule."""
    if days < 30:
        raise ValueError("days must be at least 30 so every scenario fits")
    b = Builder(random.Random(seed))
    _background(b, customers, days)
    for _ in range(copies):
        for rule_id, fn in SCENARIOS.items():
            for kind in ("positive", "near_miss"):
                t = T0 + b.rng.randint(5, days - 20) * DAY + b.rng.randint(0, 12) * HOUR
                with b.plant(rule_id, kind):
                    fn(b, t, kind == "positive")
    b.finalize()
    return Dataset(b.tables, b.planted, seed)
