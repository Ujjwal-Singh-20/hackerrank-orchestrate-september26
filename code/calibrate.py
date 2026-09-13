"""Calibrate engine parameters against the 25 solved samples.

Score = number of samples where computed amount_safe_to_pay matches exactly
(when the expected value is below requested_amount, i.e. not capped) and
computed safe >= requested when expected == requested (capped case).
"""
import csv, itertools, sys
from datetime import date
sys.path.insert(0, ".")
from engine import load, User, simulate, d

events = load("financial_events")
profiles = {r["user_id"]: r for r in load("financial_profiles")}
samples = load("sample_requests")
rates = {}
for r in load("exchange_rates"):
    rates[(d(r["rate_date"]), r["from_currency"], r["to_currency"])] = float(r["rate"])

users = {}
for uid, row in profiles.items():
    users[uid] = User(row, events, rates)

def run(params):
    res = []
    for s in samples:
        rd = d(s["request_date"])
        amt = float(s["requested_amount"])
        exp_safe = float(s["amount_safe_to_pay"])
        u = users[s["user_id"]]
        safe, binding, days = simulate(u, rd, 90, params)
        capped = exp_safe >= amt
        if capped:
            ok = safe >= amt - 1e-6
        else:
            ok = abs(safe - exp_safe) < 0.005
        res.append((s["request_id"], safe, exp_safe, ok, binding))
    return res

grid = []
for mode in ["all", "fixed_only", "protected_core"]:
    for vr in ["last", "mean", "max"]:
        for ir in ["last", "mean"]:
            grid.append({"essential_mode": mode, "value_rule": vr, "income_rule": ir})

best = []
for params in grid:
    res = run(params)
    n = sum(r[3] for r in res)
    best.append((n, params, res))
best.sort(key=lambda x: -x[0])
for n, params, res in best[:5]:
    print(n, params)
    if n >= 12:
        for r in res:
            print("  ", r[0], f"computed={r[1]:.2f} expected={r[2]:.2f}", "OK" if r[3] else "MISS", "binding:", r[4])