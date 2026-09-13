"""Buy or Wait? deterministic core: event loader, recurrence detector,
day-by-day 90-day balance simulator.

Calibrated against dataset/sample_requests.csv (see run_samples.py).

Key rules implemented (AGENTS.md §6.3 / problem_statement.md):
- failed / cancelled events ignored; unrealized (non_cash) ignored
- pending debits reserved; pending credits not counted
- scheduled rows counted on settlement_date
- salary projected forward from history (recurrence), unless evidence says it
  ended (e.g. description "Final employer payroll")
- blank event amounts come from OCR-extracted image values (images.csv link)
- balance may never fall below minimum_balance_to_keep
"""
import csv
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "dataset"
HORIZON = 90

# OCR-extracted amounts for blank-amount events (dataset/media/images/<id>.png)
IMAGE_AMOUNTS = {
    "event_253":  4365000.0,   # image_01 payslip net pay (IDR)
    "event_1442": 100000.0,    # image_02 rent receipt - Balance Due (INR): scheduled outstanding rent balance
    "event_1545": 41272.0,    # image_03 grocery cash paid (INR)
    "event_1700": 2854.0,     # image_04 delivery item bill (INR)
    "event_1786": 704.05,      # image_05 utility amount due (INR)
    "event_3051": 1995.0,      # image_06 grocery total (INR)
    "event_3231": 8528.10,     # image_07 restaurant grand total (INR)
    "event_4535": 15339.0,     # image_08 maintenance total received (INR)
    "event_5170": 723.0,       # image_09 water bill (INR)
    "event_6033": 79679.26,    # image_10 invoice (INR) - see confidence note
    "event_6859": 3650.0,      # image_11 hospital bill amount payable (INR)
    "event_7307": 33.50,       # image_12 taxi total (USD)
    "event_7941": 2298.0,      # image_13 order total paid (INR)
    "event_7941": 2298.0,      # image_13 order total paid (INR)
    "event_9421": 4543.0,     # image_14 handwritten pharmacy bill (INR)

    "event_9806": 9968.0,      # image_15 flight grand total (INR)
    "event_10521": 393.22,     # image_16 EV charging total (INR)
}

def d(s):
    return date.fromisoformat(s) if s else None

def load(name):
    with open(DATA / f"{name}.csv", newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))

def parse_pipe(s):
    return [x for x in (s or "").split("|") if x]


class UserState:
    def __init__(self, uid, events, profiles, rates):
        self.id = uid
        row = profiles[uid]
        self.currency = row["home_currency"]
        self.balance = float(row["current_available_balance"])
        self.min_bal = float(row["minimum_balance_to_keep"])
        self.protect = set(parse_pipe(row["expense_categories_to_protect"]))
        self.reduce_ok = set(parse_pipe(row["expense_categories_user_is_willing_to_reduce"]))
        self.stop_ok = set(parse_pipe(row["expense_categories_user_is_willing_to_stop"]))
        self.methods = set(parse_pipe(row["payment_methods_user_will_consider"]))
        self.max_inst = int(row["max_installment_months"]) if row["max_installment_months"] else None
        self.events = [dict(e) for e in events if e["user_id"] == uid]
        for e in self.events:
            if not e["amount"] and e["event_id"] in IMAGE_AMOUNTS:
                e["amount"] = repr(IMAGE_AMOUNTS[e["event_id"]])
        self.rates = rates

    def convert(self, amount, currency, on_date):
        if currency == self.currency:
            return amount
        key = (on_date, currency, self.currency)
        if key in self.rates:
            return amount * self.rates[key]
        # nearest earlier rate for the same pair (dataset supplies dated rates)
        cands = [(k[0], v) for k, v in self.rates.items()
                 if k[1] == currency and k[2] == self.currency and k[0] <= on_date]
        if not cands:
            raise KeyError(f"no {currency}->{self.currency} rate on/before {on_date}")
        return amount * max(cands)[1]


def infer_series(events, as_of):
    """Group settled rows into series; infer cadence + history.

    Expenses are grouped by category (descriptions rotate within a series,
    e.g. groceries). Income is grouped by description: 'Base salary' vs
    'Performance commission' vs weekly gig payouts are distinct streams with
    distinct cadences (verified against sample ground truth, e.g. user_11).
    """
    by = defaultdict(list)
    for e in events:
        if e["status"] != "settled" or e["direction"] == "non_cash" or not e["amount"]:
            continue
        ed = d(e["settlement_date"]) or d(e["event_date"])
        if ed >= as_of:
            continue
        key = ((e["direction"], e["description"]) if e["direction"] == "credit"
               else (e["direction"], e["category"]))
        by[key].append((ed, float(e["amount"]), e))
    series = {}
    for k, items in by.items():
        items.sort()
        dates = [x[0] for x in items]
        gaps = defaultdict(int)
        for a, b in zip(dates, dates[1:]):
            if (b - a).days > 0:  # same-day duplicates must not create a 0-day cadence
                gaps[(b - a).days] += 1
        cadence = max(gaps, key=lambda g: (gaps[g], -abs(g - 30))) if gaps else 30
        doms = defaultdict(int)
        for dt in dates:
            doms[dt.day] += 1
        # recurrence is projected only when history supports it: >= 2
        # occurrences and the last one is recent (within 1.5x cadence + 7d).
        # Stopped income streams (user_13's 'Second household income') drop.
        supported = len(dates) >= 2 and (as_of - dates[-1]).days <= 1.5 * cadence + 7
        series[k] = {
            "dates": dates,
            "values": [x[1] for x in items],
            "cadence": cadence,
            "mode_dom": max(doms, key=doms.get),
            "last_desc": items[-1][2]["description"],
            "category": items[-1][2]["category"],
            "currency": items[-1][2]["currency"],
            "supported": supported,
        }
    return series


def forecast_value(values, rule="round_mean"):
    if rule == "last":
        return values[-1]
    if all(v == values[0] for v in values):
        return values[0]  # constant series: exact value
    m = sum(values) / len(values)
    if rule == "mean":
        return m
    if rule == "max":
        return max(values)
    if rule == "round_mean":
        return round(m)
    raise ValueError(rule)


def salary_terminated(series):
    desc = series["last_desc"].lower()
    return "final" in desc


def project_occurrences(series, start, horizon):
    """Occurrence dates in [start, start+horizon]. Monthly series anchor on
    their modal day-of-month; other series continue at their modal gap.
    NOTE: an occurrence landing exactly on `start` (request date) counts -
    the sample ground truth reserves same-day rent (request_19)."""
    out = []
    if series["cadence"] >= 27:  # monthly-ish
        dom = series["mode_dom"]
        t = start
        while t <= start + timedelta(days=horizon):
            try:
                cand = t.replace(day=dom)
            except ValueError:
                cand = None
            if cand and start <= cand <= start + timedelta(days=horizon):
                out.append(cand)
            t += timedelta(days=27)
        out = sorted(set(out))
    else:
        t = series["dates"][-1]
        cad = series["cadence"]
        while t < start:
            t += timedelta(days=cad)
        while t <= start + timedelta(days=horizon):
            out.append(t)
            t += timedelta(days=cad)
    return out


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Message-derived amendments (deterministic parsers for the generator's
# message phrasings; production design may replace this with the LLM layer)
# ---------------------------------------------------------------------------
import re as _re

_CUR = r"(?:IDR|INR|ZAR|USD|EUR)\s?"
_AMT_PAT = _re.compile(_CUR + r"([\d,]+(?:\.\d+)?)", _re.I)
_DATE_PAT = _re.compile(r"(\d{4}-\d{2}-\d{2})")
_NEXT_PAY_PAT = _re.compile(r"next (?:payroll|salary|payslip|pay\b)|penggajian berikutnya|upcoming pay", _re.I)
_RENT_PCT_PAT = _re.compile(r"increases monthly rent by\s+(\d+)%", _re.I)
_TERMINATION_PAT = _re.compile(
    r"contract has ended|no[- ]season income|will not be renewed|"
    r"employment has ended|no .*income.*confirmed", _re.I)


def parse_messages(user_id, messages):
    """Extract salary amendment, salary termination, rent increase for a user.

    Returns dict: {salary: (amount, effective_date_or_None),
                   terminated: bool, rent_pct: float}
    """
    out = {"salary": None, "terminated": False, "rent_pct": 0.0}
    for m in messages or []:
        if m.get("user_id") != user_id:
            continue
        text = m.get("message_text", "")
        if _TERMINATION_PAT.search(text):
            out["terminated"] = True
            continue
        if "rent" in text.lower() and "increases" in text.lower():
            mp = _RENT_PCT_PAT.search(text)
            if mp:
                out["rent_pct"] = float(mp.group(1))
            continue
        m_amt = _AMT_PAT.search(text)
        if not m_amt:
            continue
        m_date = _DATE_PAT.search(text)
        if any(k in text.lower() for k in ("salary", "pay", "payroll", "gaji")):
            amt = float(m_amt.group(1).replace(",", ""))
            eff = d(m_date.group(1)) if m_date else None
            out["salary"] = (amt, eff)
    return out


VARIABLE_INCOME_KEYWORDS = ("commission", "payout", "bonus", "arrears",
                             "earnings", "windfall", "dividend")


def salary_terminated(series):
    return "final" in series["last_desc"].lower()


def stream_is_variable_income(desc):
    dl = desc.lower()
    return any(k in dl for k in VARIABLE_INCOME_KEYWORDS)


def user_salary_terminated(events, as_of):
    """True if the LATEST settled salary event for the user signals the end of
    employment (e.g. user_05's 'Final employer payroll'). User-level: a final
    paycheck terminates all salary projection."""
    latest = None
    for e in events:
        if e["status"] == "settled" and e["direction"] == "credit" \
                and e["category"] == "salary" and e["amount"]:
            ed = d(e["settlement_date"]) or d(e["event_date"])
            if ed < as_of and (latest is None or ed > latest[0]):
                latest = (ed, e)
    return bool(latest) and "final" in latest[1]["description"].lower()


def income_stream_confirmed(s):
    """A salary stream is projected only when history supports it and it is
    not a variable-income stream (commissions / gig payouts / bonuses are
    unconfirmed until settled - see the sample messages and AGENTS.md 6.3
    'Do not count pending ... bonuses, commissions ...')."""
    return (s["category"] == "salary"
            and s["supported"]
            and not salary_terminated(s)
            and not stream_is_variable_income(s["last_desc"]))


def _next_month(t):
    y, m = (t.year + 1, 1) if t.month == 12 else (t.year, t.month + 1)
    import calendar
    try:
        return date(y, m, t.day)
    except ValueError:
        return date(y, m, calendar.monthrange(y, m)[1])


def build_flows(user, request_date, messages=None, horizon=HORIZON,
                value_rule="round_mean", essential_cats=None):
    """Projected flows over the horizon: recurring essentials (with rent
    amendments), confirmed income (with message amendments and scheduled-row
    anchors), pending debits, scheduled rows."""
    end = request_date + timedelta(days=horizon)
    series = infer_series(user.events, request_date)
    amend = parse_messages(user.id, messages)
    if user_salary_terminated(user.events, request_date):
        amend["terminated"] = True
    flows = []

    # ---- essentials (recurring debits) ----
    for (direction, name), s in series.items():
        if direction != "debit":
            continue
        if essential_cats is not None and name not in essential_cats:
            continue
        if not s["supported"]:
            continue
        amt = forecast_value(s["values"], value_rule)
        if name == "rent" and amend["rent_pct"]:
            amt = round(amt * (1 + amend["rent_pct"] / 100.0))
        for t in project_occurrences(s, request_date, horizon):
            flows.append((t, -amt, f"{name}:recurrent"))

    # ---- income ----
    covered = set()  # dates already credited by an authoritative source

    # (a) scheduled salary rows anchor recurring monthly income
    if not amend["terminated"]:
        for e in user.events:
            if (e["status"] == "scheduled" and e["direction"] == "credit"
                    and e["category"] == "salary" and e["amount"]):
                sd = d(e["settlement_date"]) or d(e["event_date"])
                if not (request_date <= sd <= end):
                    continue
                t = sd
                while t <= end:
                    amt_t = user.convert(float(e["amount"]), e["currency"], t)
                    flows.append((t, +amt_t, f"{e['event_id']}:salary-anchor"))
                    covered.add(t)
                    t = _next_month(t)

    # (b) confirmed recurring salary streams, with message amendments
    sal_streams = [] if amend["terminated"] else \
        [(name, s) for (dr, name), s in series.items()
         if dr == "credit" and income_stream_confirmed(s)]
    for name, s in sal_streams:
        amt = s["values"][-1]
        for t in project_occurrences(s, request_date, horizon):
            if t in covered:
                continue
            eff_amt = amt
            if amend["salary"]:
                a_amt, a_eff = amend["salary"]
                sent = None
                for m in messages or []:
                    if m.get("user_id") == user.id:
                        sent = d(m["sent_at"][:10])
                if a_eff is None:
                    a_eff = sent  # "next payroll" -> occurrences after message
                if a_eff and t >= a_eff:
                    eff_amt = a_amt
            flows.append((t, +user.convert(eff_amt, s["currency"], t),
                          f"{name}:recurrent"))

    # (c) salary amendment with no supported stream anchors a new stream
    if not sal_streams and amend["salary"] and not amend["terminated"]:
        a_amt, a_eff = amend["salary"]
        if a_eff and request_date <= a_eff <= end:
            t = a_eff
            while t <= end:
                flows.append((t, +a_amt, "salary:amendment-anchor"))
                t = _next_month(t)

    # ---- pending / scheduled non-income rows ----
    for e in user.events:
        st, sd = e["status"], d(e["settlement_date"]) or d(e["event_date"])
        if not (request_date <= sd <= end) or not e["amount"]:
            continue
        if st == "scheduled" and e["direction"] == "credit" and e["category"] == "salary":
            continue  # handled above
        amt = user.convert(float(e["amount"]), e["currency"], sd)
        if st == "pending" and e["direction"] == "debit":
            flows.append((sd, -amt, f"{e['event_id']}:pending"))
        elif st == "scheduled":
            sign = 1 if e["direction"] == "credit" else -1
            flows.append((sd, sign * amt, f"{e['event_id']}:scheduled"))
    return flows


def simulate(user, request_date, payments, flows, horizon=HORIZON):
    """payments: list of (date, amount). Returns (ok, min_balance_seen, binding_day,
    daily_log). ok iff balance >= min_bal every day through horizon."""
    end = request_date + timedelta(days=horizon)
    allf = [(t, -a, "plan") for t, a in payments] + list(flows)
    # same-day ordering: credits (income) land before debits/plan payments
    allf.sort(key=lambda x: (x[0], 0 if x[1] > 0 else 1))
    bal = user.balance
    min_seen = bal
    binding = request_date
    log = []
    day = request_date
    i = 0
    while day <= end:
        while i < len(allf) and allf[i][0] == day:
            t, amt, lbl = allf[i]
            bal += amt
            log.append((day, amt, lbl, bal))
            if bal < min_seen:
                min_seen, binding = bal, day
            i += 1
        day += timedelta(days=1)
    return min_seen, binding, log


def amount_safe_to_pay(user, request_date, requested, flows, horizon=HORIZON):
    """Max X payable on request_date keeping balance >= min_bal throughout.
    Within a day, credits land before the plan payment (a salary-day payment
    may rely on that day's income), debits land after it."""
    byday = defaultdict(lambda: [0.0, 0.0])  # day -> [credits, debits]
    for t, amt, lbl in flows:
        if amt > 0:
            byday[t][0] += amt
        else:
            byday[t][1] -= amt
    bal = user.balance
    best = user.balance - user.min_bal
    day = request_date
    while day <= request_date + timedelta(days=horizon):
        bal += byday[day][0]
        bal -= byday[day][1]
        room = bal - user.min_bal
        if room < best:
            best = room
        day += timedelta(days=1)
    return max(0.0, min(best, requested))


def _daily_arrays(user, flows, horizon=HORIZON):
    """Per-day credits c(u) and net flows f(u) over the horizon (O(D) once).

    Same-day semantics match simulate(): credits land before any plan
    payment, other debits land after it.
    """
    n = horizon + 1
    f = [0.0] * n
    c = [0.0] * n
    for t, amt, lbl in flows:
        idx = (t - request_date_key[0]).days
        if 0 <= idx < n:
            f[idx] += amt
            if amt > 0:
                c[idx] += amt
    return f, c


def safe_on_date(user, requested, t_idx, f, c, F, M):
    """Max amount payable on day t_idx (0-based) keeping balance >= min_bal
    through the horizon. Credits of day t_idx land before the payment."""
    room = user.balance - user.min_bal
    # mid-day trough on t_idx: after credits, after payment, before debits
    mid = room + (F[t_idx - 1] if t_idx > 0 else 0.0) + c[t_idx]
    # end-of-day and later days
    end = room + M[t_idx] + 0.0
    return max(0.0, min(mid, end))


def earliest_full_payment_fast(user, request_date, requested, flows, horizon=HORIZON):
    """Suffix-min formulation of earliest_full_payment - O(D) instead of
    O(D^2 * F). F(u) = cumulative net flow; M(t) = min_{u>=t} F(u) is
    non-decreasing in t, so the first valid t is found in one scan."""
    global request_date_key
    request_date_key = (request_date,)
    n = horizon + 1
    f, c = _daily_arrays(user, flows, horizon)
    F = [0.0] * n
    acc = 0.0
    for i in range(n):
        acc += f[i]
        F[i] = acc
    M = [0.0] * n
    M[n - 1] = F[n - 1]
    for i in range(n - 2, -1, -1):
        M[i] = min(F[i], M[i + 1])
    room = user.balance - user.min_bal
    for t in range(n):
        mid = room + (F[t - 1] if t > 0 else 0.0) + c[t]
        end = room + M[t]
        if requested <= max(0.0, min(mid, end)) + 1e-9:
            return request_date + timedelta(days=t)
    return None


def earliest_full_payment(user, request_date, requested, flows, horizon=HORIZON):
    """First date t in [request_date, +horizon] such that paying `requested`
    on t keeps balance >= min_bal through the horizon."""
    t = request_date
    while t <= request_date + timedelta(days=horizon):
        min_seen, _, _ = simulate(user, request_date, [(t, requested)], flows, horizon)
        if min_seen >= user.min_bal - 1e-9:
            return t
        t += timedelta(days=1)
    return None