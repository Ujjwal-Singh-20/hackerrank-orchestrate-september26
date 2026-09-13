"""Diagnostic: per sample x rule, print binding day + computed safe vs expected."""
import csv
from collections import defaultdict
from datetime import date, timedelta
import numpy as np

DATA = "../dataset/"
def d(s): return date.fromisoformat(s) if s else None
def load(name):
    with open(DATA + f"{name}.csv", newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))

events = load("financial_events")
profiles = {r["user_id"]: r for r in load("financial_profiles")}
samples = load("sample_requests")
IMAGE = {"event_253": 4365000.0, "event_1442": 200000.0, "event_1700": 2854.0}
H = 90

RULES = ["last", "mean", "max", "round_mean", "ceil_mean", "floor_mean"]
def val(vals, rule):
    m = sum(vals) / len(vals)
    return {"last": vals[-1], "mean": m, "max": max(vals),
            "round_mean": round(m), "ceil_mean": int(np.ceil(m)),
            "floor_mean": int(np.floor(m))}[rule]

for s in samples:
    uid = s["user_id"]; prof = profiles[uid]; rd = d(s["request_date"])
    B = float(prof["current_available_balance"]); mn = float(prof["minimum_balance_to_keep"])
    exp = float(s["amount_safe_to_pay"]); amt = float(s["requested_amount"])
    ev = [dict(e) for e in events if e["user_id"] == uid]
    for e in ev:
        if not e["amount"] and e["event_id"] in IMAGE:
            e["amount"] = str(IMAGE[e["event_id"]])
    # series
    by = defaultdict(list)
    for e in ev:
        if e["status"] != "settled" or e["direction"] == "non_cash" or not e["amount"]:
            continue
        ed = d(e["settlement_date"]) or d(e["event_date"])
        if ed < rd:
            by[(e["direction"], e["category"])].append((ed, float(e["amount"])))
    occs = {}
    for k, items in by.items():
        items.sort()
        dates = [x[0] for x in items]
        gaps = defaultdict(int)
        for a, b in zip(dates, dates[1:]):
            gaps[(b - a).days] += 1
        cad = max(gaps, key=lambda g: (gaps[g], -abs(g - 30))) if gaps else 30
        doms = defaultdict(int)
        for dt in dates: doms[dt.day] += 1
        occs[k] = (dates, [x[1] for x in items], cad, max(doms, key=doms.get))
    print(f"\n=== {s['request_id']} {s['request_type']} rd={rd} B={B} min={mn} expected_safe={exp} (req={amt})")
    for rule in RULES:
        deb = np.zeros(H + 1); inc = np.zeros(H + 1)
        labels = defaultdict(list)
        for (dr, cat), (dates, vals, cad, dom) in occs.items():
            # anchor: try day-of-month for monthly-ish, gap for others
            out = []
            if dr == "debit":
                t = dates[-1]
                while t <= rd: t += timedelta(days=cad)
                while (t - rd).days <= H:
                    out.append(t); t += timedelta(days=cad)
                v = val(vals, rule)
                for t in out:
                    deb[(t - rd).days] += v; labels[(t - rd).days].append(f"{cat}={v}")
            elif cat == "salary":
                t = dates[-1]
                while t <= rd: t += timedelta(days=cad)
                while (t - rd).days <= H:
                    inc[(t - rd).days] += val(vals, rule); t += timedelta(days=cad)
        for e in ev:
            if e["status"] in ("pending", "scheduled") and e["amount"]:
                sd = d(e["settlement_date"]) or d(e["event_date"])
                if rd < sd <= rd + timedelta(days=H):
                    if e["direction"] == "debit":
                        deb[(sd - rd).days] += float(e["amount"]); labels[(sd - rd).days].append(f"{e['event_id']}:{e['status']}={e['amount']}")
                    else:
                        inc[(sd - rd).days] += float(e["amount"])
        cum = np.cumsum(inc - deb)
        room = B - mn + cum
        k = int(room.argmin())
        safe = min(room[k], B - mn)
        flag = "OK " if (abs(safe - exp) < 0.005 if exp < amt else safe >= amt - 0.005) else "   "
        print(f"  {flag}{rule:11s} safe={safe:>13.2f} exp={exp:>13.2f} trough=rd+{k} ({rd+timedelta(days=k)})")
        if rule == "round_mean" and abs(safe - exp) > 0.005 and exp < amt:
            for day in sorted(labels):
                if day <= k:
                    print(f"      d+{day}: {labels[day]}")