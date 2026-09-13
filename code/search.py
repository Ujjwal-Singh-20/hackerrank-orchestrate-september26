"""Large-scale hypothesis search: per-category inclusion masks x value rules.

For each sample and each category we precompute a 91-day cumulative-flow vector
per value rule; a mask evaluation is then a vector sum + min, done in numpy.
Scoring: uncapped samples must match expected amount_safe_to_pay exactly
(< 0.005); capped samples must compute safe >= requested_amount.
"""
import csv, sys
from collections import defaultdict
from datetime import date, timedelta
import numpy as np

DATA = "../dataset/"

def d(s):
    return date.fromisoformat(s) if s else None

def load(name):
    with open(DATA + f"{name}.csv", newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))

events = load("financial_events")
profiles = {r["user_id"]: r for r in load("financial_profiles")}
samples = load("sample_requests")
rates = {}
for r in load("exchange_rates"):
    rates[(d(r["rate_date"]), r["from_currency"], r["to_currency"])] = float(r["rate"])

# image-extracted amounts (OCR) for blank-amount events
IMAGE_AMOUNTS = {"event_253": 4365000.0, "event_1442": 200000.0, "event_1700": 2854.0}

H = 90  # horizon days

def build_context(sample):
    uid = sample["user_id"]
    prof = profiles[uid]
    rd = d(sample["request_date"])
    home = prof["home_currency"]
    B = float(prof["current_available_balance"])
    mn = float(prof["minimum_balance_to_keep"])
    ev = [e for e in events if e["user_id"] == uid]
    for e in ev:
        if not e["amount"] and e["event_id"] in IMAGE_AMOUNTS:
            e["amount"] = str(IMAGE_AMOUNTS[e["event_id"]])
    return prof, rd, B, mn, ev, home

def infer_series(ev, as_of):
    by = defaultdict(list)
    for e in ev:
        if e["status"] != "settled" or e["direction"] == "non_cash" or not e["amount"]:
            continue
        ed = d(e["settlement_date"]) or d(e["event_date"])
        if ed >= as_of:
            continue
        by[(e["direction"], e["category"], e["event_type"])].append((ed, float(e["amount"]), e))
    series = {}
    for k, items in by.items():
        items.sort()
        dates = [x[0] for x in items]
        gaps = defaultdict(int)
        for a, b in zip(dates, dates[1:]):
            gaps[(b - a).days] += 1
        cad = max(gaps, key=lambda g: (gaps[g], -abs(g - 30))) if gaps else 30
        doms = defaultdict(int)
        for dt in dates:
            doms[dt.day] += 1
        series[k] = {"dates": dates, "values": [x[1] for x in items],
                     "cadence": cad, "mode_dom": max(doms, key=doms.get),
                     "flex": items[-1][2]["flexibility"]}
    return series

VALUE_RULES = ["last", "mean", "max", "round_mean", "round_last", "ceil_mean"]

def vrule(vals, rule):
    if rule == "last": return vals[-1]
    if rule == "mean": return sum(vals) / len(vals)
    if rule == "max": return max(vals)
    if rule == "round_mean": return round(sum(vals) / len(vals))
    if rule == "round_last": return round(vals[-1])
    if rule == "ceil_mean": return -(-sum(vals) // len(vals))
    raise ValueError(rule)

def occurrences(series, start, anchor):
    """Projected occurrence dates in (start, start+H]."""
    out = []
    if anchor == "gap":
        t = series["dates"][-1]
        cad = series["cadence"]
        while t <= start:
            t += timedelta(days=cad)
        while (t - start).days <= H:
            out.append(t)
            t += timedelta(days=cad)
    else:  # mode day-of-month
        dom = series["mode_dom"]
        t = start
        for _ in range(H // 30 + 2):
            try:
                cand = t.replace(day=dom)
            except ValueError:
                cand = None
            if cand and t < cand <= start + timedelta(days=H):
                out.append(cand)
            t += timedelta(days=30)
        # dedupe
        out = sorted(set(out))
    return out

def flows_for_context(ctx):
    prof, rd, B, mn, ev, home = ctx
    series = infer_series(ev, rd)
    end = rd + timedelta(days=H)
    # per (category, rule, anchor) daily debit vectors
    vecs = {}  # (category, rule, anchor) -> np.array(91) of daily debit amounts
    for (direction, cat, etype), s in series.items():
        if direction != "debit":
            continue
        if etype in ("investment_purchase",):
            continue
        for rule in VALUE_RULES:
            for anchor in ("gap", "dom"):
                v = np.zeros(H + 1)
                amt = vrule(s["values"], rule)
                for t in occurrences(s, rd, anchor):
                    v[(t - rd).days] += amt
                vecs[(cat, rule, anchor)] = vecs.get((cat, rule, anchor), np.zeros(H + 1)) + v
    # income vectors (salary only), rule in {last, mean}; anchors both
    inc = {}
    for (direction, cat, etype), s in series.items():
        if direction != "credit" or cat != "salary":
            continue
        for rule in ["last", "mean"]:
            for anchor in ("gap", "dom"):
                v = np.zeros(H + 1)
                amt = vrule(s["values"], rule)
                for t in occurrences(s, rd, anchor):
                    v[(t - rd).days] += amt
                inc[(rule, anchor)] = inc.get((rule, anchor), np.zeros(H + 1)) + v
    # scheduled income rows (dedupe against recurrence later per-month)
    sched_inc = np.zeros(H + 1)
    for e in ev:
        if e["status"] == "scheduled" and e["direction"] == "credit" and e["amount"]:
            sd = d(e["settlement_date"]) or d(e["event_date"])
            if rd < sd <= end:
                sched_inc[(sd - rd).days] += float(e["amount"])
    # pending debits
    pend = np.zeros(H + 1)
    for e in ev:
        if e["status"] == "pending" and e["direction"] == "debit" and e["amount"]:
            sd = d(e["settlement_date"]) or d(e["event_date"])
            if rd < sd <= end:
                pend[(sd - rd).days] += float(e["amount"])
    # scheduled debits (non-pending scheduled expenses)
    sched_deb = np.zeros(H + 1)
    for e in ev:
        if e["status"] == "scheduled" and e["direction"] == "debit" and e["amount"]:
            sd = d(e["settlement_date"]) or d(e["event_date"])
            if rd < sd <= end:
                sched_deb[(sd - rd).days] += float(e["amount"])
    return vecs, inc, sched_inc, pend, sched_deb, B, mn

CATS = ["rent", "housing", "utilities", "groceries", "transport", "dining",
        "healthcare", "education", "family_support", "insurance", "debt_repayment",
        "shopping", "entertainment", "subscriptions", "work_expense"]
SUBS = {"cloud_storage", "streaming", "music_subscription", "delivery_membership", "gym"}

contexts = {}
for s in samples:
    ctx = build_context(s)
    contexts[s["request_id"]] = (s, flows_for_context(ctx))

def eval_params(mask, rule, anchor, inc_rule, inc_anchor, dedupe_sched):
    score = 0
    details = []
    for s in samples:
        rid = s["request_id"]
        sample, (vecs, inc, sched_inc, pend, sched_deb, B, mn) = contexts[rid]
        deb = pend + sched_deb
        for i, c in enumerate(CATS):
            if not (mask >> i) & 1:
                continue
            key = (c if c != "subscriptions" else None, rule, anchor)
            # sum subscription vectors
            if c == "subscriptions":
                for sc in SUBS:
                    if (sc, rule, anchor) in vecs:
                        deb = deb + vecs[(sc, rule, anchor)]
            elif (c, rule, anchor) in vecs:
                deb = deb + vecs[(c, rule, anchor)]
        income = inc.get((inc_rule, inc_anchor), np.zeros(H + 1)) + sched_inc
        cum = np.cumsum(income - deb)
        safe = min((B - mn + cum).min(), B - mn)
        exp = float(sample["amount_safe_to_pay"])
        amt = float(sample["requested_amount"])
        if exp >= amt - 1e-9:
            ok = safe >= amt - 0.005
        else:
            ok = abs(safe - exp) < 0.005
        score += ok
        details.append((rid, safe, exp, ok))
    return score, details

best = []
import itertools
n_masks = 1 << len(CATS)
# prune: rent+housing+utilities+groceries near-certain? test all but skip masks with <3 cats
for mask in range(n_masks):
    if bin(mask).count("1") < 3:
        continue
    for rule in VALUE_RULES:
        for anchor in ("gap", "dom"):
            for inc_rule in ("last", "mean"):
                for inc_anchor in ("gap", "dom"):
                    sc, det = eval_params(mask, rule, anchor, inc_rule, inc_anchor, True)
                    best.append((sc, mask, rule, anchor, inc_rule, inc_anchor))
best.sort(key=lambda x: -x[0])
print("TOP 10:")
for sc, mask, rule, anchor, ir, ia in best[:10]:
    on = [CATS[i] for i in range(len(CATS)) if (mask >> i) & 1]
    print(sc, rule, anchor, "inc:", ir, ia, on)