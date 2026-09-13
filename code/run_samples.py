"""Run the deterministic engine against all 25 sample_requests rows.
Prints computed vs expected amount_safe_to_pay and earliest_date_for_full_payment,
plus the itemized essential-expense breakdown used at the binding trough."""
import csv, sys
from datetime import date, timedelta
sys.path.insert(0, str(__file__).rsplit("/", 1)[0])
from engine import (load, UserState, build_flows, amount_safe_to_pay,
                    earliest_full_payment_fast as earliest_full_payment, d, HORIZON)
from collections import defaultdict

events = load("financial_events")
profiles = {r["user_id"]: r for r in load("financial_profiles")}
samples = load("sample_requests")
MSGS = load("messages")
rates = {}
for r in load("exchange_rates"):
    rates[(d(r["rate_date"]), r["from_currency"], r["to_currency"])] = float(r["rate"])

n_ok_safe = n_ok_edfp = 0
rows = []
for s in samples:
    uid = s["user_id"]
    user = UserState(uid, events, profiles, rates)
    rd = d(s["request_date"])
    req = float(s["requested_amount"])
    ESSENTIAL = {"rent","housing","utilities","groceries","transport","dining",
                 "healthcare","education","family_support","insurance",
                 "debt_repayment","shopping","entertainment","cloud_storage",
                 "streaming","music_subscription","delivery_membership","gym",
                 "work_expense"}  # investment contributions are NOT reserved
    flows = build_flows(user, rd, messages=MSGS, essential_cats=ESSENTIAL)
    safe = amount_safe_to_pay(user, rd, req, flows)
    edfp = earliest_full_payment(user, rd, req, flows)
    exp_safe = float(s["amount_safe_to_pay"])
    exp_edfp = s["earliest_date_for_full_payment"] or None
    ok_safe = abs(safe - exp_safe) < 0.005 if exp_safe < req else safe >= req - 0.005
    ok_edfp = (str(edfp) if edfp else None) == exp_edfp
    n_ok_safe += ok_safe; n_ok_edfp += ok_edfp
    # itemized breakdown of debits up to binding day
    byday = defaultdict(list)
    for t, amt, lbl in flows:
        byday[t].append((amt, lbl))
    cum = 0.0
    trough_day, trough_E = rd, 0.0
    bal = user.balance
    best = user.balance - user.min_bal
    day = rd
    items = []
    while day <= rd + timedelta(days=HORIZON):
        for amt, lbl in byday[day]:
            bal += amt
            items.append((day, amt, lbl))
            if bal - user.min_bal < best:
                best = bal - user.min_bal
                trough_day, trough_E = day, sum(a for _, a, _ in items if a < 0)
        day += timedelta(days=1)
    rows.append((s["request_id"], safe, exp_safe, ok_safe, edfp, exp_edfp, ok_edfp,
                 trough_day, trough_E, items, req))

print(f"exact amount_safe_to_pay matches: {n_ok_safe}/25")
print(f"exact earliest_date_for_full_payment matches: {n_ok_edfp}/25\n")
for r in rows:
    rid, safe, exp_safe, ok_s, edfp, exp_e, ok_e, tday, tE, items, req = r
    mark = "OK " if ok_s else "MISS"
    print(f"{rid}: safe computed={safe:.2f} expected={exp_safe:.2f} [{mark}] "
          f"edfp computed={edfp} expected={exp_e} [{'OK' if ok_e else 'MISS'}] "
          f"trough={tday} cumDebits@trough={tE:.2f}")
    if not ok_s:
        for day, amt, lbl in items:
            if day <= tday and amt < 0:
                print(f"    {day} {amt:>12.2f} {lbl}")