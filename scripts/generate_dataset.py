#!/usr/bin/env python3
"""Deterministic synthetic financial-transaction dataset generator (spec #6.2).

Produces exactly one file:  finsentry_master_dataset.csv

Connected histories (accounts/customers/institutions) are built first, then
transactions are generated over ~18 months with realistic timestamps,
behaviour features computed *only from prior transactions* (no leakage),
multiple currencies, lifecycle states, reconciliation fields and a controlled
number of labelled anomalies.

Usage:
    python scripts/generate_dataset.py [--rows 50000] [--seed 42] [--out PATH]
"""
from __future__ import annotations

import argparse
import csv
import random
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

# ------------------------------------------------------------------ config --
START = datetime(2024, 1, 1, 0, 0, 0)
END = datetime(2025, 6, 30, 23, 59, 59)

INSTITUTIONS = [
    ("INST_HDFC_01", "bank"), ("INST_ICICI_02", "bank"), ("INST_SBI_03", "bank"),
    ("INST_AXIS_04", "bank"), ("INST_KOTAK_05", "bank"), ("INST_IDFC_06", "bank"),
    ("INST_YES_07", "bank"), ("INST_PNB_08", "bank"),
    ("INST_RBI_PPI_09", "wallet"), ("INST_PAY_PPI_10", "wallet"),
    ("INST_CARD_V_11", "card_network"), ("INST_MC_12", "card_network"),
    ("INST_SWIFT_EU_13", "correspondent"), ("INST_SWIFT_US_14", "correspondent"),
    ("INST_UPI_15", "payment_aggregator"),
]

RAILS = {
    "UPI": {"currencies": ["INR"], "fee": (0.0, 0.5), "success": 0.985},
    "IMPS": {"currencies": ["INR"], "fee": (1.0, 6.0), "success": 0.982},
    "NEFT": {"currencies": ["INR"], "fee": (1.0, 5.0), "success": 0.991},
    "RTGS": {"currencies": ["INR"], "fee": (5.0, 25.0), "success": 0.994},
    "CARD": {"currencies": ["INR", "USD", "EUR", "GBP"], "fee": (0.5, 35.0), "success": 0.962},
    "WALLET": {"currencies": ["INR"], "fee": (0.0, 2.0), "success": 0.977},
    "SWIFT": {"currencies": ["USD", "EUR", "GBP", "AED", "SGD"], "fee": (8.0, 55.0), "success": 0.973},
    "SEPA": {"currencies": ["EUR"], "fee": (0.3, 4.0), "success": 0.989},
}

# synthetic reference rates (relative to INR) — labelled synthetic in docs
FX_TO_INR = {"INR": 1.0, "USD": 83.2, "EUR": 90.1, "GBP": 105.4, "AED": 22.65, "SGD": 61.8}

COUNTRIES = {
    "IN": ["MH", "DL", "KA", "TN", "TG", "GJ", "UP", "WB", "RJ", "KL"],
    "US": ["CA", "NY", "TX", "WA", "IL"],
    "GB": ["ENG", "SCT", "WLS"],
    "AE": ["DXB", "AUH", "SHJ"],
    "SG": ["CENTRAL", "EAST"],
    "DE": ["BE", "NW", "BY"],
    "FR": ["IDF", "ARA"],
}
COUNTRY_RISK_WEIGHT = [("IN", 0.72), ("US", 0.08), ("GB", 0.06), ("AE", 0.06),
                       ("SG", 0.04), ("DE", 0.025), ("FR", 0.015)]

CATEGORIES = [
    ("person_transfer", 0.34), ("salary", 0.10), ("merchant_payment", 0.18),
    ("bill_payment", 0.08), ("loan_emi", 0.06), ("refund", 0.04),
    ("investment", 0.05), ("rent", 0.05), ("subscription", 0.05),
    ("cash_withdrawal", 0.05),
]
STATUSES = [("success", 0.955), ("pending", 0.018), ("failed", 0.019),
            ("reversed", 0.004), ("refunded", 0.004)]
PURPOSES = ["family support", "monthly rent", "groceries", "utilities", "travel",
            "medical", "tuition", "equipment purchase", "invoice settlement",
            "freelance payout", "investment", "loan repayment", "gift"]

DEVICE_PLATFORMS = ["android", "ios", "web", "pos_terminal", "ussd", "api"]


def wchoice(rng: random.Random, pairs):
    names, weights = zip(*pairs)
    return rng.choices(names, weights=weights, k=1)[0]


def make_generator(seed: int, rows: int):
    rng = random.Random(seed)

    # ---------------------------------------------------------- entities ---
    n_customers = max(1500, rows // 14)
    n_accounts = int(n_customers * 1.6)
    n_merchants = max(400, rows // 110)

    customers = []
    for i in range(n_customers):
        country = wchoice(rng, COUNTRY_RISK_WEIGHT)
        customers.append({
            "id": f"CUST_{i:06d}",
            "country": country,
            "segment": wchoice(rng, [("retail", 0.68), ("sme", 0.18),
                                     ("corporate", 0.09), ("premium", 0.05)]),
            "type": "business" if rng.random() < 0.22 else "individual",
            "opened": START - timedelta(days=rng.randint(1, 2600)),
        })

    accounts = []
    for i in range(n_accounts):
        owner = customers[rng.randrange(n_customers)]
        inst = INSTITUTIONS[rng.randrange(len(INSTITUTIONS))][0]
        accounts.append({
            "id": f"ACC_{i:06d}",
            "owner": owner["id"],
            "type": wchoice(rng, [("savings", 0.55), ("current", 0.28),
                                  ("wallet", 0.12), ("card", 0.05)]),
            "status": wchoice(rng, [("active", 0.93), ("dormant", 0.045),
                                    ("frozen", 0.015), ("closed", 0.01)]),
            "country": owner["country"],
            "institution": inst,
            "age_days": max(1, (START - owner["opened"]).days + rng.randint(0, 400)),
            "opened": owner["opened"],
        })
    merchants = [f"MERC_{i:05d}" for i in range(n_merchants)]

    # deterministic activity profiles so behaviour is stable per account:
    # heavy-tailed (log-normal) — a minority of accounts drives most traffic
    activity = {a["id"]: rng.lognormvariate(0.0, 1.1) for a in accounts}
    act_w = [activity[a["id"]] for a in accounts]
    _cw, _acc = [], 0.0
    for _w in act_w:
        _acc += _w
        _cw.append(_acc)
    act_cum = _cw
    accounts_by_id = {a["id"]: a for a in accounts}
    customer_by_id = {c["id"]: c for c in customers}

    # per-account rolling history (used for leakage-free behaviour features)
    hist_out: dict[str, list[tuple[datetime, float, str]]] = defaultdict(list)
    hist_in: dict[str, list[tuple[datetime, float, str]]] = defaultdict(list)
    last_seen: dict[str, datetime] = {}
    last_amounts: dict[str, list[float]] = defaultdict(list)
    tx_counter = 0
    event_log: list[dict] = []

    def prior_stats(acc: str, now: datetime, counterparty: str):
        """Features from transactions strictly BEFORE `now` (no leakage)."""
        window = timedelta(days=30)
        out = [x for x in hist_out[acc] if now - window <= x[0] < now]
        inc = [x for x in hist_in[acc] if now - window <= x[0] < now]
        # latest strictly-prior outgoing event (history may hold later events
        # when injected scenario rows land mid-history)
        prior_times = [x[0] for x in hist_out[acc] if x[0] < now]
        prev = max(prior_times) if prior_times else None
        amts = [x[1] for x in out]
        return {
            "src_txn_count_30d": len(out),
            "dst_txn_count_30d": len(inc),
            "src_incoming_count_30d": len(inc),
            "src_outgoing_count_30d": len(out),
            "src_avg_amount_30d": round(sum(amts) / len(amts), 2) if amts else "",
            "src_volume_30d": round(sum(amts), 2) if amts else "",
            "src_unique_counterparties_30d": len({x[2] for x in out}),
            "dst_unique_counterparties_30d": len({x[2] for x in inc}),
            "seconds_since_previous_source": int((now - prev).total_seconds()) if prev else "",
            "seconds_since_previous_destination": "",
            "src_days_since_last_activity": round((now - prev).total_seconds() / 86400, 2)
            if prev else round((now - START).total_seconds() / 86400, 2),
            "dst_days_since_last_activity": "",
        }

    # -------------------------------------------------------- scenarios ----
    # Controlled anomaly scenarios injected as explicit batches later.
    scenario_events: list[dict] = []

    def next_tx_id() -> str:
        nonlocal tx_counter
        tx_counter += 1
        return f"TXN_{tx_counter:08d}"

    rows_out: list[dict] = []

    def emit(d: dict) -> None:
        rows_out.append(d)

    def rand_time(rng2: random.Random) -> datetime:
        span = int((END - START).total_seconds())
        # diurnal pattern: bias toward working hours
        base = START + timedelta(seconds=rng2.randrange(span))
        hour = base.hour
        if rng2.random() < 0.65 and (7 <= hour <= 22):
            pass
        else:
            base = base.replace(hour=rng2.choice([9, 10, 11, 14, 15, 16, 19, 20]))
        return base

    # ---- normal transactions ------------------------------------------
    n_normal = int(rows * 0.94)
    partners: dict[str, list[str]] = defaultdict(list)
    for i in range(n_normal):
        rng2 = random.Random(seed * 1000003 + i)
        src_acc = rng2.choices(accounts, cum_weights=act_cum, k=1)[0]
        t = rand_time(rng2)
        # organic clustering: accounts transact in bursts around recent
        # activity (payday / shopping sessions), not at uniform random
        prior = hist_out[src_acc["id"]]
        if prior:
            roll = rng2.random()
            anchor = prior[rng2.randrange(len(prior))][0]
            if roll < 0.010:
                # repeat-payment cadence: follow-ups seconds apart
                t = anchor + timedelta(seconds=rng2.randint(30, 900))
            elif roll < 0.260:
                # organic clustering around recent activity
                t = anchor + timedelta(seconds=rng2.randint(-2 * 86400, 2 * 86400))
        # NOTE: do NOT clamp t to the account's previous event time —
        # ratcheting times forward is a record-process bias that pushes busy
        # accounts to the very end of the span. prior_stats computes
        # "seconds since previous" from strictly-earlier events instead,
        # so out-of-order timestamps are handled correctly there.
        if t > END:
            t = END
        elif t < START:
            t = START
        # pick destination: 35% repeat counterparty, 35% other account,
        # 15% merchant, 15% new/random cross-border account
        roll = rng2.random()
        dst_country = src_acc["country"]
        rep = partners.get(src_acc["id"]) or []
        if rep and roll < 0.35:
            dst_acc = accounts_by_id[rep[rng2.randrange(len(rep))]]
            if dst_acc["id"] == src_acc["id"]:
                dst_acc = accounts[rng2.randrange(n_accounts)]
            merchant = ""
            dst_inst = dst_acc["institution"]
        elif roll < 0.70:
            dst_acc = accounts[rng2.randrange(n_accounts)]
            if dst_acc["id"] == src_acc["id"]:
                dst_acc = accounts[(accounts.index(dst_acc) + 1) % n_accounts]
            merchant = ""
            dst_inst = dst_acc["institution"]
        elif roll < 0.85:
            dst_acc = None
            merchant = merchants[rng2.randrange(n_merchants)]
            dst_inst = INSTITUTIONS[rng2.randrange(len(INSTITUTIONS))][0]
        else:
            dst_country = wchoice(rng2, COUNTRY_RISK_WEIGHT)
            dst_acc = accounts[rng2.randrange(n_accounts)]
            if dst_acc["id"] == src_acc["id"]:
                dst_acc = accounts[(accounts.index(dst_acc) + 2) % n_accounts]
            merchant = ""
            dst_inst = dst_acc["institution"]
        if dst_acc is not None:
            pl = partners[src_acc["id"]]
            if dst_acc["id"] != src_acc["id"] and len(pl) < 12:
                pl.append(dst_acc["id"])

        rail = wchoice(rng2, [("UPI", 0.34), ("IMPS", 0.14), ("NEFT", 0.11),
                              ("RTGS", 0.05), ("CARD", 0.18), ("WALLET", 0.08),
                              ("SWIFT", 0.06), ("SEPA", 0.04)])
        rail_cfg = RAILS[rail]
        category = wchoice(rng2, CATEGORIES)

        # amount distribution: log-normal with category shifts
        import math
        base_mu = {"person_transfer": 6.4, "salary": 9.7, "merchant_payment": 5.4,
                   "bill_payment": 5.9, "loan_emi": 8.4, "refund": 5.2,
                   "investment": 9.1, "rent": 9.0, "subscription": 4.6,
                   "cash_withdrawal": 7.0}[category]
        amount = round(min(max(rng2.lognormvariate(base_mu, 1.05), 1.0), 9_500_000), 2)
        if rng2.random() < 0.012:
            # large but legitimate settlements (invoices, treasury moves, bonus
            # payouts). Hard negatives: they share the amount band with the
            # injected scenarios, so amount alone must not separate the classes.
            amount = round(rng2.uniform(60_000, 900_000), 2)

        src_country = src_acc["country"]
        cross_border = src_country != dst_country or rail in ("SWIFT", "SEPA")
        src_ccy = "INR"
        if rail in ("SWIFT",) and rng2.random() < 0.8:
            src_ccy = wchoice(rng2, [("USD", 0.45), ("EUR", 0.2), ("GBP", 0.15),
                                     ("AED", 0.1), ("SGD", 0.1)])
        elif rail == "SEPA":
            src_ccy = "EUR"
        elif rail == "CARD" and cross_border:
            src_ccy = wchoice(rng2, [("USD", 0.5), ("EUR", 0.2), ("GBP", 0.15),
                                     ("INR", 0.15)])

        # convert the INR-denominated amount into source-currency units
        # (FX_TO_INR = INR per 1 unit of currency)
        amount_src = round(amount / FX_TO_INR[src_ccy], 2)
        dst_ccy = src_ccy
        fx_rate = 1.0
        if dst_acc is not None:
            dst_acc_country = dst_acc["country"]
        else:
            dst_acc_country = dst_country
        if src_ccy != dst_ccy or rng2.random() < 0.06:
            # destination currency by country
            dst_ccy = {"IN": "INR", "US": "USD", "GB": "GBP", "AE": "AED",
                       "SG": "SGD", "DE": "EUR", "FR": "EUR"}[dst_acc_country]
            fx_rate = round(FX_TO_INR[src_ccy] / FX_TO_INR[dst_ccy], 6)
        amount_dst = round(amount_src * fx_rate, 2)

        fee_rate = rail_cfg["fee"]
        fee = round(rng2.uniform(*fee_rate), 2) if amount > 0 else 0.0
        exch_fee = round(abs(amount_dst) * rng2.uniform(0.0005, 0.002), 2) \
            if fx_rate != 1.0 else 0.0

        status = wchoice(rng2, STATUSES)
        initiated = t
        authorized = initiated + timedelta(seconds=rng2.randint(1, 45))
        processed = authorized + timedelta(seconds=rng2.randint(1, 240))
        settled = processed + timedelta(seconds=rng2.randint(30, 7200)) \
            if status in ("success", "reversed", "refunded") else None
        failed_at = processed if status == "failed" else None

        src_owner = src_acc["owner"]
        dst_owner = dst_acc["owner"] if dst_acc else ""
        stats = prior_stats(src_acc["id"], initiated,
                            dst_acc["id"] if dst_acc else merchant)

        row = {
            "transaction_id": next_tx_id(),
            "parent_transaction_id": "",
            "reference_id": f"REF_{rng2.randrange(10**9):09d}" if rng2.random() < 0.7 else "",
            "transaction_status": status,
            "transaction_category": category,
            "transaction_description": f"{category} {rng2.choice(PURPOSES)}",
            "initiated_at_utc": initiated.strftime("%Y-%m-%d %H:%M:%S"),
            "authorized_at_utc": authorized.strftime("%Y-%m-%d %H:%M:%S"),
            "processed_at_utc": processed.strftime("%Y-%m-%d %H:%M:%S"),
            "settled_at_utc": settled.strftime("%Y-%m-%d %H:%M:%S") if settled else "",
            "failed_at_utc": failed_at.strftime("%Y-%m-%d %H:%M:%S") if failed_at else "",
            "is_reversal": "1" if status == "reversed" else "0",
            "is_refund": "1" if status == "refunded" else "0",
            "original_transaction_id": "",

            "source_account_id": src_acc["id"],
            "destination_account_id": dst_acc["id"] if dst_acc else f"MERCHANT_ACCT_{merchant[-5:]}",
            "sender_customer_id": src_owner,
            "receiver_customer_id": dst_owner,
            "source_account_type": src_acc["type"],
            "destination_account_type": (dst_acc["type"] if dst_acc else "merchant"),
            "source_customer_type": customer_by_id[src_owner]["type"],
            "destination_customer_type": (customer_by_id[dst_owner]["type"] if dst_owner else "business"),
            "source_customer_segment": customer_by_id[src_owner]["segment"],
            "destination_customer_segment": (customer_by_id[dst_owner]["segment"] if dst_owner else "sme"),
            "source_account_age_days": src_acc["age_days"],
            "destination_account_age_days": (dst_acc["age_days"] if dst_acc else rng2.randint(60, 3000)),
            "source_account_status": src_acc["status"],
            "destination_account_status": (dst_acc["status"] if dst_acc else "active"),

            **stats,

            "source_amount": amount_src,
            "source_currency": src_ccy,
            "destination_amount": amount_dst,
            "destination_currency": dst_ccy,
            "fx_rate_to_destination": fx_rate,
            "fx_rate_timestamp_utc": initiated.strftime("%Y-%m-%d %H:%M:%S"),
            "reference_fx_rate": round(fx_rate * (1 + rng2.uniform(-0.001, 0.001)), 6)
            if fx_rate != 1.0 else 1.0,
            "fee_amount": fee,
            "fee_currency": src_ccy,
            "exchange_fee_amount": exch_fee,
            "exchange_fee_currency": dst_ccy if exch_fee else "",
            "net_source_amount": round(amount_src - fee, 2),
            "net_destination_amount": round(amount_dst - exch_fee, 2) if status == "success" else "",

            "source_country": src_country,
            "destination_country": dst_acc_country,
            "source_region": COUNTRIES[src_country][rng2.randrange(len(COUNTRIES[src_country]))],
            "destination_region": COUNTRIES[dst_acc_country][rng2.randrange(len(COUNTRIES[dst_acc_country]))],
            "is_cross_border": "1" if cross_border else "0",
            "source_institution_id": src_acc["institution"],
            "destination_institution_id": dst_inst,
            "intermediary_institution_id": (INSTITUTIONS[rng2.randrange(len(INSTITUTIONS))][0]
                                            if cross_border and rng2.random() < 0.6 else ""),
            "source_institution_type": next(t for i, t in INSTITUTIONS if i == src_acc["institution"]),
            "destination_institution_type": next(t for i, t in INSTITUTIONS if i == dst_inst),
            "payment_rail": rail,
            "payment_channel": wchoice(rng2, [("mobile", 0.45), ("internet", 0.3),
                                              ("branch", 0.08), ("pos", 0.12), ("api", 0.05)]),
            "merchant_id": merchant,
            "device_id": f"DEV_{rng2.randrange(6000):05d}" if rng2.random() < 0.7 else "",
            "device_country": src_country,
            "ip_country": (src_country if rng2.random() < 0.93
                           else wchoice(rng2, COUNTRY_RISK_WEIGHT)),
            "transaction_purpose": rng2.choice(PURPOSES),

            "processing_duration_seconds": int((processed - authorized).total_seconds()),
            "settlement_duration_seconds": int((settled - processed).total_seconds()) if settled else "",
            "retry_count": rng2.choices([0, 1, 2, 3], weights=[0.9, 0.07, 0.02, 0.01])[0]
            if status != "success" else 0,
            "failure_reason_code": (wchoice(rng2, [("INSUFFICIENT_FUNDS", 0.3),
                                                   ("TIMEOUT", 0.25), ("LIMIT_EXCEEDED", 0.15),
                                                   ("ACCOUNT_CLOSED", 0.1), ("FRAUD_HOLD", 0.08),
                                                   ("NETWORK_ERROR", 0.12)])
                                    if status == "failed" else ""),
            "payment_provider": wchoice(rng2, [("PROV_ALPHA", 0.35), ("PROV_BETA", 0.3),
                                               ("PROV_GAMMA", 0.2), ("PROV_DELTA", 0.15)]),
            "payment_status_changed": "1" if status in ("reversed", "refunded", "failed") else "0",
            "settlement_delay_flag": "1" if settled and (settled - processed).seconds > 3600 else "0",

            "expected_settlement_amount": (amount_dst if rng2.random() < 0.65 else ""),
            "observed_settlement_amount": "",
            "reconciliation_currency": dst_ccy if rng2.random() < 0.65 else "",
            "expected_settlement_date": (settled.strftime("%Y-%m-%d") if settled and rng2.random() < 0.6 else ""),
            "observed_settlement_date": "",
            "reconciliation_status": "",
            "reconciliation_difference_amount": "",
            "synthetic_discrepancy_category": "",

            "synthetic_anomaly_label": "0",
            "synthetic_scenario_category": "normal",
            "synthetic_scenario_id": "",
        }

        # reconciliation population
        if row["expected_settlement_amount"] != "":
            exp = float(row["expected_settlement_amount"])
            if status == "success":
                roll_r = rng2.random()
                if roll_r < 0.86:
                    obs = exp
                    rstatus, disc = "matched", ""
                elif roll_r < 0.94:
                    obs = round(exp + rng2.uniform(-0.05, 0.05), 2)
                    rstatus, disc = "matched", "rounding"
                elif roll_r < 0.98:
                    obs = round(exp * rng2.uniform(0.97, 1.03), 2)
                    rstatus, disc = "amount_mismatch", "amount_variance"
                else:
                    obs = ""
                    rstatus, disc = "missing_settlement", "missing_data"
                row["observed_settlement_amount"] = obs
                row["reconciliation_status"] = rstatus
                row["synthetic_discrepancy_category"] = disc
                if obs != "":
                    row["reconciliation_difference_amount"] = round(float(obs) - exp, 4)
                    row["observed_settlement_date"] = (
                        (settled + timedelta(days=rng2.randint(0, 2))).strftime("%Y-%m-%d")
                        if settled else "")
            else:
                row["reconciliation_status"] = "not_applicable"

        # update histories AFTER prior_stats (leakage-free ordering)
        if row["transaction_status"] in ("success", "reversed", "refunded"):
            hist_out[src_acc["id"]].append((initiated, amount_src,
                                            row["destination_account_id"]))
            last_seen[src_acc["id"]] = initiated
            if dst_acc is not None:
                hist_in[dst_acc["id"]].append((initiated, amount_dst, src_acc["id"]))
                last_seen[dst_acc["id"]] = initiated

        emit(row)

    # ---- controlled anomaly scenarios (spec #6.1 / #10.4) --------------
    def pick_active(kind: str, i: int, n=1):
        # NOTE: the seed must include the scenario kind AND instance index —
        # an earlier version shadowed the loop variable, which pinned every
        # scenario instance onto the same handful of accounts (trivially
        # separable by account-level aggregates).
        opts = [a for a in accounts if a["status"] == "active"]
        return random.Random(f"{seed}:{kind}:{i}").sample(opts, n)

    anomalies: list[dict] = []

    # A) structuring: bursts just under a threshold
    n_split = max(40, int(rows * 0.0035))
    for i in range(n_split):
        grp = 3 + (i % 4)
        src, dst = pick_active("structuring", i, 2)
        t0 = START + timedelta(days=(i * 7) % 500, hours=10 + (i % 6))
        for k in range(grp):
            tt = t0 + timedelta(minutes=k * rng.randint(4, 35))
            amt = round(rng.uniform(88_000, 98_500), 2)   # below 100k "threshold"
            anomalies.append(("structuring", "structuring_under_threshold", tt, src, dst, amt,
                              "success", "person_transfer", "UPI"))

    # B) rapid pass-through
    n_pass = max(30, int(rows * 0.002))
    for i in range(n_pass):
        a, b, c = pick_active("passthrough", i, 3)
        t0 = START + timedelta(days=(i * 11) % 500, hours=9 + (i % 8))
        amt = round(rng.uniform(40_000, 900_000), 2)
        anomalies.append(("passthrough", "rapid_pass_through", t0, a, b, amt,
                          "success", "person_transfer", "IMPS"))
        anomalies.append(("passthrough", "rapid_pass_through", t0 + timedelta(minutes=rng.randint(5, 50)),
                          b, c, round(amt * rng.uniform(0.75, 0.97), 2),
                          "success", "person_transfer", "IMPS"))

    # C) circular transfers (3-hop cycles)
    n_cyc = max(15, int(rows * 0.0012))
    for i in range(n_cyc):
        a, b, c = pick_active("cycle", i, 3)
        t0 = START + timedelta(days=(i * 13) % 500, hours=12)
        amt = round(rng.uniform(60_000, 1_500_000), 2)
        for k, (x, y) in enumerate([(a, b), (b, c), (c, a)]):
            anomalies.append(("cycle", "circular_transfer", t0 + timedelta(hours=k * 6),
                              x, y, amt if k < 2 else round(amt * 0.99, 2),
                              "success", "investment", "RTGS"))

    # D) fan-out burst from one account
    n_fan = max(10, int(rows * 0.0006))
    for i in range(n_fan):
        src = pick_active("fanout", i, 1)[0]
        t0 = START + timedelta(days=(i * 17) % 500, hours=11)
        for k in range(rng.randint(15, 40)):
            dst = accounts[rng.randrange(n_accounts)]
            if dst["id"] == src["id"]:
                continue
            anomalies.append(("fanout", "fan_out_burst", t0 + timedelta(minutes=k * 3),
                              src, dst, round(rng.uniform(5_000, 45_000), 2),
                              "success", "person_transfer", "UPI"))

    # E) amount outliers
    n_out = max(30, int(rows * 0.0015))
    for i in range(n_out):
        a, b = pick_active("amount", i, 2)
        t0 = START + timedelta(days=(i * 19) % 500, hours=15)
        anomalies.append(("amount", "extreme_amount", t0, a, b,
                          round(rng.uniform(4_000_000, 9_500_000), 2),
                          "success", "investment", "RTGS"))

    # emit anomalies
    for kind, scen, t, src, dst, amt, status, cat, rail in anomalies:
        # category drifts like real traffic: the scenario name lives in
        # transaction_purpose/description, not in the broad category
        cat = wchoice(rng, [("person_transfer", 0.5), ("investment", 0.18),
                            ("rent", 0.12), ("merchant_payment", 0.12),
                            ("bill_payment", 0.08)])
        src_ccy = "INR"
        dst_ccy = "INR"
        fx_rate = 1.0
        fee = round(rng.uniform(*RAILS[rail]["fee"]), 2)
        processed = t + timedelta(seconds=rng.randint(2, 120))
        settled = processed + timedelta(seconds=rng.randint(60, 5400)) if status == "success" else None
        stats = prior_stats(src["id"], t, dst["id"])
        row = {
            "transaction_id": next_tx_id(),
            "parent_transaction_id": "",
            "reference_id": f"REF_{rng.randrange(10**9):09d}",
            "transaction_status": status,
            "transaction_category": cat,
            "transaction_description": f"{scen.replace('_', ' ')}",
            "initiated_at_utc": t.strftime("%Y-%m-%d %H:%M:%S"),
            "authorized_at_utc": (t + timedelta(seconds=5)).strftime("%Y-%m-%d %H:%M:%S"),
            "processed_at_utc": processed.strftime("%Y-%m-%d %H:%M:%S"),
            "settled_at_utc": settled.strftime("%Y-%m-%d %H:%M:%S") if settled else "",
            "failed_at_utc": "",
            "is_reversal": "0", "is_refund": "0", "original_transaction_id": "",

            "source_account_id": src["id"], "destination_account_id": dst["id"],
            "sender_customer_id": src["owner"], "receiver_customer_id": dst["owner"],
            "source_account_type": src["type"], "destination_account_type": dst["type"],
            "source_customer_type": customer_by_id[src["owner"]]["type"],
            "destination_customer_type": customer_by_id[dst["owner"]]["type"],
            "source_customer_segment": customer_by_id[src["owner"]]["segment"],
            "destination_customer_segment": customer_by_id[dst["owner"]]["segment"],
            "source_account_age_days": src["age_days"],
            "destination_account_age_days": dst["age_days"],
            "source_account_status": src["status"],
            "destination_account_status": dst["status"],
            **stats,

            "source_amount": amt, "source_currency": src_ccy,
            "destination_amount": amt, "destination_currency": dst_ccy,
            "fx_rate_to_destination": 1.0,
            "fx_rate_timestamp_utc": t.strftime("%Y-%m-%d %H:%M:%S"),
            "reference_fx_rate": 1.0,
            "fee_amount": fee, "fee_currency": src_ccy,
            "exchange_fee_amount": 0, "exchange_fee_currency": "",
            "net_source_amount": round(amt - fee, 2),
            "net_destination_amount": round(amt, 2) if status == "success" else "",

            "source_country": src["country"], "destination_country": dst["country"],
            "source_region": COUNTRIES[src["country"]][rng.randrange(len(COUNTRIES[src["country"]]))],
            "destination_region": COUNTRIES[dst["country"]][rng.randrange(len(COUNTRIES[dst["country"]]))],
            "is_cross_border": "1" if src["country"] != dst["country"] else "0",
            "source_institution_id": src["institution"], "destination_institution_id": dst["institution"],
            "intermediary_institution_id": "",
            "source_institution_type": next(t2 for i2, t2 in INSTITUTIONS if i2 == src["institution"]),
            "destination_institution_type": next(t2 for i2, t2 in INSTITUTIONS if i2 == dst["institution"]),
            "payment_rail": rail,
            # fraud metadata is not uniform: rails, providers, channels and
            # categories vary just like legitimate traffic (only fan-out
            # bursts stay API-driven — that is what makes them bursts)
            "payment_channel": ("api" if kind == "fanout" else
                                wchoice(rng, [("mobile", 0.5), ("internet", 0.22),
                                              ("api", 0.15), ("branch", 0.08),
                                              ("pos", 0.05)])),
            "merchant_id": "", "device_id": f"DEV_{rng.randrange(6000):05d}",
            "device_country": src["country"], "ip_country": src["country"],
            "transaction_purpose": scen.replace("_", " "),

            "processing_duration_seconds": int((processed - t).total_seconds()),
            "settlement_duration_seconds": int((settled - processed).total_seconds()) if settled else "",
            "retry_count": 0, "failure_reason_code": "",
            "payment_provider": wchoice(rng, [("PROV_ALPHA", 0.35), ("PROV_BETA", 0.3),
                                               ("PROV_GAMMA", 0.2), ("PROV_DELTA", 0.15)]),
            "payment_status_changed": "0",
            "settlement_delay_flag": "1" if settled and (settled - processed).total_seconds() > 3600 else "0",

            "expected_settlement_amount": amt if status == "success" else "",
            "observed_settlement_amount": (round(amt * rng.uniform(0.985, 1.015), 2)
                                           if status == "success" and kind == "amount"
                                           else (amt if status == "success" else "")),
            "reconciliation_currency": dst_ccy if status == "success" else "",
            "expected_settlement_date": settled.strftime("%Y-%m-%d") if settled else "",
            "observed_settlement_date": settled.strftime("%Y-%m-%d") if settled else "",
            "reconciliation_status": ("amount_mismatch" if kind == "amount" and status == "success"
                                      else ("matched" if status == "success" else "not_applicable")),
            "reconciliation_difference_amount": (round(amt * rng.uniform(-0.015, 0.015), 2)
                                                 if kind == "amount" and status == "success" else ""),
            "synthetic_discrepancy_category": ("amount_variance" if kind == "amount"
                                               and status == "success" else ""),

            "synthetic_anomaly_label": "1",
            "synthetic_scenario_category": kind,
            "synthetic_scenario_id": f"SCEN_{scen.upper()}_{abs(hash((kind, t.isoformat(), amt))) % 10**6:06d}",
        }
        # update histories for behaviour consistency
        hist_out[src["id"]].append((t, amt, dst["id"]))
        last_seen[src["id"]] = t
        hist_in[dst["id"]].append((t, amt, src["id"]))
        last_seen[dst["id"]] = t
        emit(row)

    # ---- legitimate batch payments (payroll / contractor runs) ----------
    # Structurally identical to structuring (several near-threshold payments
    # within hours) but perfectly legal — the honest false-positive pressure
    # that keeps hold-out metrics from reading as trivially perfect.
    n_batches = max(6, int(rows * 0.0006))
    payroll: list[tuple[datetime, dict, dict, float]] = []
    for i in range(n_batches):
        src, _ = pick_active("payroll", i, 2)
        t0 = START + timedelta(days=rng.randrange(500), hours=rng.randint(9, 16))
        for _ in range(rng.randint(4, 6)):
            dst = accounts[rng.randrange(n_accounts)]
            if dst["id"] == src["id"]:
                continue
            payroll.append((t0 + timedelta(minutes=rng.randint(3, 40)), src, dst,
                            round(rng.uniform(88_000, 99_000), 2)))
    for t, src, dst, amt in payroll:
        processed = t + timedelta(seconds=rng.randint(2, 90))
        settled = processed + timedelta(seconds=rng.randint(60, 3600))
        stats = prior_stats(src["id"], t, dst["id"])
        rail = wchoice(rng, [("IMPS", 0.45), ("NEFT", 0.4), ("RTGS", 0.15)])
        fee = round(rng.uniform(*RAILS[rail]["fee"]), 2)
        exp_amt = amt if rng.random() < 0.65 else ""
        row = {
            "transaction_id": next_tx_id(),
            "parent_transaction_id": "",
            "reference_id": f"REF_{rng.randrange(10**9):09d}",
            "transaction_status": "success",
            "transaction_category": "salary",
            "transaction_description": f"salary {rng.choice(PURPOSES)}",
            "initiated_at_utc": t.strftime("%Y-%m-%d %H:%M:%S"),
            "authorized_at_utc": (t + timedelta(seconds=rng.randint(1, 30))).strftime("%Y-%m-%d %H:%M:%S"),
            "processed_at_utc": processed.strftime("%Y-%m-%d %H:%M:%S"),
            "settled_at_utc": settled.strftime("%Y-%m-%d %H:%M:%S"),
            "failed_at_utc": "",
            "is_reversal": "0", "is_refund": "0", "original_transaction_id": "",

            "source_account_id": src["id"], "destination_account_id": dst["id"],
            "sender_customer_id": src["owner"], "receiver_customer_id": dst["owner"],
            "source_account_type": src["type"], "destination_account_type": dst["type"],
            "source_customer_type": customer_by_id[src["owner"]]["type"],
            "destination_customer_type": customer_by_id[dst["owner"]]["type"],
            "source_customer_segment": customer_by_id[src["owner"]]["segment"],
            "destination_customer_segment": customer_by_id[dst["owner"]]["segment"],
            "source_account_age_days": src["age_days"],
            "destination_account_age_days": dst["age_days"],
            "source_account_status": src["status"],
            "destination_account_status": dst["status"],
            **stats,

            "source_amount": amt, "source_currency": "INR",
            "destination_amount": amt, "destination_currency": "INR",
            "fx_rate_to_destination": 1.0,
            "fx_rate_timestamp_utc": t.strftime("%Y-%m-%d %H:%M:%S"),
            "reference_fx_rate": 1.0,
            "fee_amount": fee, "fee_currency": "INR",
            "exchange_fee_amount": 0, "exchange_fee_currency": "",
            "net_source_amount": round(amt - fee, 2),
            "net_destination_amount": round(amt, 2),

            "source_country": src["country"], "destination_country": dst["country"],
            "source_region": COUNTRIES[src["country"]][rng.randrange(len(COUNTRIES[src["country"]]))],
            "destination_region": COUNTRIES[dst["country"]][rng.randrange(len(COUNTRIES[dst["country"]]))],
            "is_cross_border": "1" if src["country"] != dst["country"] else "0",
            "source_institution_id": src["institution"],
            "destination_institution_id": dst["institution"],
            "intermediary_institution_id": "",
            "source_institution_type": next(t2 for i2, t2 in INSTITUTIONS if i2 == src["institution"]),
            "destination_institution_type": next(t2 for i2, t2 in INSTITUTIONS if i2 == dst["institution"]),
            "payment_rail": rail,
            "payment_channel": wchoice(rng, [("api", 0.6), ("internet", 0.3), ("mobile", 0.1)]),
            "merchant_id": "", "device_id": f"DEV_{rng.randrange(6000):05d}",
            "device_country": src["country"], "ip_country": src["country"],
            "transaction_purpose": rng.choice(PURPOSES),

            "processing_duration_seconds": int((processed - t).total_seconds()),
            "settlement_duration_seconds": int((settled - processed).total_seconds()),
            "retry_count": 0, "failure_reason_code": "",
            "payment_provider": wchoice(rng, [("PROV_ALPHA", 0.35), ("PROV_BETA", 0.3),
                                               ("PROV_GAMMA", 0.2), ("PROV_DELTA", 0.15)]),
            "payment_status_changed": "0",
            "settlement_delay_flag": "1" if (settled - processed).seconds > 3600 else "0",

            "expected_settlement_amount": exp_amt,
            "observed_settlement_amount": exp_amt,
            "reconciliation_currency": "INR" if exp_amt else "",
            "expected_settlement_date": settled.strftime("%Y-%m-%d") if exp_amt else "",
            "observed_settlement_date": settled.strftime("%Y-%m-%d") if exp_amt else "",
            "reconciliation_status": "matched" if exp_amt else "not_applicable",
            "reconciliation_difference_amount": "",
            "synthetic_discrepancy_category": "",

            "synthetic_anomaly_label": "0",
            "synthetic_scenario_category": "normal",
            "synthetic_scenario_id": "",
        }
        hist_out[src["id"]].append((t, amt, dst["id"]))
        hist_in[dst["id"]].append((t, amt, src["id"]))
        emit(row)

    # ---- data-quality defects (controlled, small) ----------------------
    defects = max(50, int(rows * 0.0025))
    for i in range(defects):
        idx = rng.randrange(len(rows_out))
        kind = i % 5
        r = rows_out[idx]
        if kind == 0:
            r["transaction_description"] = ""                     # missing text
        elif kind == 1:
            r["device_id"] = ""                                   # missing id
        elif kind == 2:
            r["fee_amount"] = "N/A"                               # invalid numeric
        elif kind == 3:
            r["initiated_at_utc"] = "31/02/2025 25:61:00"         # impossible date
        elif kind == 4:
            r["source_region"] = "unknown"                        # unknown category
    # duplicate rows (exact)
    for i in range(max(10, int(rows * 0.0003))):
        idx = rng.randrange(100, len(rows_out) - 1)
        rows_out.insert(idx + 1, dict(rows_out[idx]))

    # ---- sort chronologically for realism ----------------------------
    rows_out.sort(key=lambda r: r["initiated_at_utc"])

    return rows_out


FIELDNAMES = [
    "transaction_id", "parent_transaction_id", "reference_id", "transaction_status",
    "transaction_category", "transaction_description", "initiated_at_utc",
    "authorized_at_utc", "processed_at_utc", "settled_at_utc", "failed_at_utc",
    "is_reversal", "is_refund", "original_transaction_id",
    "source_account_id", "destination_account_id", "sender_customer_id",
    "receiver_customer_id", "source_account_type", "destination_account_type",
    "source_customer_type", "destination_customer_type", "source_customer_segment",
    "destination_customer_segment", "source_account_age_days",
    "destination_account_age_days", "source_account_status",
    "destination_account_status", "src_txn_count_30d", "dst_txn_count_30d",
    "src_incoming_count_30d", "src_outgoing_count_30d", "src_avg_amount_30d",
    "src_volume_30d", "src_unique_counterparties_30d",
    "dst_unique_counterparties_30d", "seconds_since_previous_source",
    "seconds_since_previous_destination", "src_days_since_last_activity",
    "dst_days_since_last_activity", "source_amount", "source_currency",
    "destination_amount", "destination_currency", "fx_rate_to_destination",
    "fx_rate_timestamp_utc", "reference_fx_rate", "fee_amount", "fee_currency",
    "exchange_fee_amount", "exchange_fee_currency", "net_source_amount",
    "net_destination_amount", "source_country", "destination_country",
    "source_region", "destination_region", "is_cross_border",
    "source_institution_id", "destination_institution_id",
    "intermediary_institution_id", "source_institution_type",
    "destination_institution_type", "payment_rail", "payment_channel",
    "merchant_id", "device_id", "device_country", "ip_country",
    "transaction_purpose", "processing_duration_seconds",
    "settlement_duration_seconds", "retry_count", "failure_reason_code",
    "payment_provider", "payment_status_changed", "settlement_delay_flag",
    "expected_settlement_amount", "observed_settlement_amount",
    "reconciliation_currency", "expected_settlement_date",
    "observed_settlement_date", "reconciliation_status",
    "reconciliation_difference_amount", "synthetic_discrepancy_category",
    "synthetic_anomaly_label", "synthetic_scenario_category",
    "synthetic_scenario_id",
]


def validate(path: Path) -> list[str]:
    """Self-check the generated file (spec #6.4)."""
    problems: list[str] = []
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        ids = set()
        dup = 0
        n = 0
        labels = defaultdict(int)
        status_bad = 0
        date_bad = 0
        for row in reader:
            n += 1
            tid = row["transaction_id"]
            if tid in ids:
                dup += 1
            ids.add(tid)
            labels[row["synthetic_anomaly_label"]] += 1
            if row["transaction_status"] == "failed" and row["settled_at_utc"]:
                status_bad += 1
            try:
                datetime.strptime(row["initiated_at_utc"], "%Y-%m-%d %H:%M:%S")
            except ValueError:
                date_bad += 1
    print(f"  rows={n:,} unique_ids={len(ids):,} duplicate_ids={dup}")
    print(f"  labels={dict(labels)}")
    if dup:
        problems.append(f"{dup} duplicate transaction_ids (excluding intentional row dups)")
    if status_bad:
        problems.append(f"{status_bad} failed rows carry settled_at")
    if date_bad:
        problems.append(f"{date_bad} unparseable initiated_at values (intentional defects ok)")
    return problems


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--rows", type=int, default=50_000)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", type=str, default="")
    args = ap.parse_args()

    root = Path(__file__).resolve().parent.parent
    out = Path(args.out) if args.out else root / "data" / "finsentry_master_dataset.csv"
    out.parent.mkdir(parents=True, exist_ok=True)

    print(f"Generating {args.rows:,} rows (seed={args.seed}) → {out}")
    rows = make_generator(args.seed, args.rows)
    with out.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDNAMES, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)
    size = out.stat().st_size
    print(f"Wrote {len(rows):,} rows, {size / 1e6:.1f} MB")
    problems = validate(out)
    if problems:
        print("Validation notes:")
        for p in problems:
            print(f"  - {p}")
    else:
        print("Validation: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
