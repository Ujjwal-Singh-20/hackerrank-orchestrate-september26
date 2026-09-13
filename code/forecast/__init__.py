"""forecast: the pure deterministic 90-day balance simulation.

No I/O, no LLM. Everything here is a pure function of
(profile, ledger, request, amendments, image_amounts, config).
"""

from __future__ import annotations
from collections import defaultdict
from datetime import date, timedelta
from typing import Optional

import config
from errors import ForecastError
from schemas import (Amendment, AmendmentType, Flow, ForecastResult,
                     LedgerEvent, Request, SeriesInfo, UserProfile)


# ---------------- conversion ----------------

def convert(amount: float, currency: str, home: str, on: date, rates) -> float:
    if currency == home:
        return amount
    key = (on, currency, home)
    if key in rates:
        return amount * rates[key]
    cands = [(k[0], v) for k, v in rates.items()
             if k[1] == currency and k[2] == home and k[0] <= on]
    if not cands:
        raise ForecastError(f"no {currency}->{home} rate on/before {on}")
    return amount * max(cands)[1]


# ---------------- series inference ----------------

def infer_series(events: list[LedgerEvent], as_of: date) -> dict:
    """Group settled rows into recurring series.

    Expenses group by category (descriptions rotate within a series, e.g.
    groceries); income groups by description (a payroll and a commission are
    distinct streams with distinct cadences).
    """
    by = defaultdict(list)
    for e in events:
        if e.status != "settled" or e.direction == "non_cash" or e.amount is None:
            continue
        ed = e.settlement_date or e.event_date
        if ed >= as_of:
            continue
        key = ((e.direction, e.description) if e.direction == "credit"
               else (e.direction, e.category))
        by[key].append((ed, e.amount, e))
    c = config.get()
    series = {}
    for k, items in by.items():
        items.sort()
        dates = [x[0] for x in items]
        gaps = defaultdict(int)
        for a, b in zip(dates, dates[1:]):
            if (b - a).days > 0:
                gaps[(b - a).days] += 1
        cadence = max(gaps, key=lambda g: (gaps[g], -abs(g - 30))) if gaps else 30  # (b) prefer the modal gap, ties toward ~monthly
        doms = defaultdict(int)
        for dt in dates:
            doms[dt.day] += 1
        supported = (len(dates) >= c.MIN_SERIES_OCCURRENCES
                     and (as_of - dates[-1]).days <= c.RECENCY_MULTIPLIER * cadence + c.RECENCY_GRACE_DAYS)
        series[k] = {
            "dates": dates,
            "values": [x[1] for x in items],
            "cadence": cadence,
            "mode_dom": max(doms, key=doms.get),
            "last_desc": items[-1][2].description,
            "category": items[-1][2].category,
            "currency": items[-1][2].currency,
            "supported": supported,
        }
    return series


def forecast_value(values: list[float]) -> float:
    """Constant series use the exact value; variable series use round(mean)."""
    if all(v == values[0] for v in values):
        return values[0]
    return round(sum(values) / len(values))


def user_salary_terminated(events: list[LedgerEvent], as_of: date) -> bool:
    """True if the LATEST settled salary event signals the end of employment."""
    c = config.get()
    latest = None
    for e in events:
        if (e.status == "settled" and e.direction == "credit"
                and e.category == c.SALARY_CATEGORY and e.amount is not None):
            ed = e.settlement_date or e.event_date
            if ed < as_of and (latest is None or ed > latest[0]):
                latest = (ed, e)
    return bool(latest) and c.SALARY_TERMINATION_KEYWORD in latest[1].description.lower()


def _next_month(t: date) -> date:
    y, m = (t.year + 1, 1) if t.month == 12 else (t.year, t.month + 1)
    import calendar
    try:
        return date(y, m, t.day)
    except ValueError:
        return date(y, m, calendar.monthrange(y, m)[1])


def project_occurrences(s: dict, start: date, horizon: int) -> list[date]:
    """Occurrence dates in [start, start+horizon]. Monthly series anchor on
    their modal day-of-month; others continue at their modal gap. An occurrence
    landing exactly on `start` counts (sample ground truth reserves same-day
    rent)."""
    c = config.get()
    out = []
    if s["cadence"] >= c.MONTHLY_CADENCE_MIN:
        dom = s["mode_dom"]
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
        t = s["dates"][-1]
        cad = s["cadence"]
        while t < start:
            t += timedelta(days=cad)
        while t <= start + timedelta(days=horizon):
            out.append(t)
            t += timedelta(days=cad)
    return out


# ---------------- flow construction ----------------

def build_flows(profile: UserProfile, events: list[LedgerEvent], request: Request,
               amendments: tuple[Amendment, ...], image_amounts: dict[str, float],
               rates) -> tuple[list[Flow], dict]:
    """Projected flows: recurring essentials, confirmed income, pending debits
    and scheduled rows, all currency-converted to the user's home currency."""
    c = config.get()
    rd = request.request_date
    end = rd + timedelta(days=c.HORIZON_DAYS)
    home = profile.home_currency
    flows: list[Flow] = []
    series = infer_series(events, rd)

    # amendments
    salary_amend = None     # (amount, effective_date_or_None)
    rent_pct = 0.0
    terminated = user_salary_terminated(events, rd)
    for a in amendments:
        if a.kind is AmendmentType.SALARY_TERMINATION:
            terminated = True
        elif a.kind is AmendmentType.RENT_INCREASE_PCT:
            rent_pct = a.amount
        elif a.kind is AmendmentType.SALARY_AMOUNT:
            salary_amend = (a.amount, a.effective_date)

    # essentials
    for (direction, name), s in series.items():
        if direction != "debit" or name not in c.ESSENTIAL_CATEGORIES:
            continue
        if not s["supported"]:
            continue
        amt = forecast_value(s["values"])
        if name == "rent" and rent_pct:
            amt = round(amt * (1 + rent_pct / 100.0))
        for t in project_occurrences(s, rd, c.HORIZON_DAYS):
            flows.append(Flow(t, -amt, f"{name}:recurrent"))

    covered = set()

    # (a) scheduled salary rows anchor recurring monthly income
    if not terminated:
        for e in events:
            if (e.status == "scheduled" and e.direction == "credit"
                    and e.category == c.SALARY_CATEGORY and e.amount is not None):
                sd = e.settlement_date or e.event_date
                if not (rd <= sd <= end):
                    continue
                t = sd
                while t <= end:
                    amt_t = convert(e.amount, e.currency, home, t, rates)
                    flows.append(Flow(t, amt_t, f"{e.event_id}:salary-anchor"))
                    covered.add(t)
                    t = _next_month(t)

    # (b) confirmed recurring salary streams
    sal_streams = [] if terminated else [
        (name, s) for (dr, name), s in series.items()
        if dr == "credit" and _income_confirmed(s)]
    for name, s in sal_streams:
        amt = s["values"][-1]
        for t in project_occurrences(s, rd, c.HORIZON_DAYS):
            if t in covered:
                continue
            eff_amt = amt
            if salary_amend:
                a_amt, a_eff = salary_amend
                if a_eff is None:
                    a_eff = rd  # "next payroll": occurrences from request on
                if t >= a_eff:
                    eff_amt = a_amt
            flows.append(Flow(t, convert(eff_amt, s["currency"], home, t, rates),
                              f"{name}:recurrent"))

    # (c) amendment with no supported stream anchors a new stream
    if not sal_streams and salary_amend and not terminated:
        a_amt, a_eff = salary_amend
        if a_eff and rd <= a_eff <= end:
            t = a_eff
            while t <= end:
                flows.append(Flow(t, a_amt, "salary:amendment-anchor"))
                t = _next_month(t)

    # pending / scheduled rows
    for e in events:
        sd = e.settlement_date or e.event_date
        if not (rd <= sd <= end):
            continue
        amount = e.amount if e.amount is not None else image_amounts.get(e.event_id)
        if amount is None:
            continue
        amt = convert(amount, e.currency, home, sd, rates)
        if e.status == "pending" and e.direction == "debit":
            flows.append(Flow(sd, -amt, f"{e.event_id}:pending"))
        elif e.status == "scheduled" and not (e.direction == "credit"
                                               and e.category == c.SALARY_CATEGORY):
            sign = 1 if e.direction == "credit" else -1
            flows.append(Flow(sd, sign * amt, f"{e.event_id}:scheduled"))
    return flows, series


def _income_confirmed(s: dict) -> bool:
    c = config.get()
    dl = s["last_desc"].lower()
    return (s["category"] == c.SALARY_CATEGORY
            and s["supported"]
            and c.SALARY_TERMINATION_KEYWORD not in dl
            and not any(k in dl for k in c.VARIABLE_INCOME_KEYWORDS))


# ---------------- simulation core ----------------

def daily_arrays(flows: list[Flow], request_date: date, horizon: int):
    """Per-day credits c(u) and net flows f(u). Same-day semantics: credits
    land before any plan payment; other debits land after it."""
    n = horizon + 1
    f = [0.0] * n
    c = [0.0] * n
    for fl in flows:
        idx = (fl.day - request_date).days
        if 0 <= idx < n:
            f[idx] += fl.amount
            if fl.amount > 0:
                c[idx] += fl.amount
    return f, c


def prefix_and_suffix(f: list[float]):
    n = len(f)
    F = [0.0] * n
    acc = 0.0
    for i in range(n):
        acc += f[i]
        F[i] = acc
    M = [0.0] * n
    M[n - 1] = F[n - 1]
    for i in range(n - 2, -1, -1):
        M[i] = min(F[i], M[i + 1])
    return F, M


def max_payable_on(profile: UserProfile, t_idx: int, f, c, F, M) -> float:
    """Max amount payable on day index t_idx keeping balance >= min_balance
    through the horizon (credits of that day land before the payment)."""
    room = profile.balance - profile.min_balance
    mid = room + (F[t_idx - 1] if t_idx > 0 else 0.0) + c[t_idx]
    end = room + M[t_idx]
    return max(0.0, min(mid, end))


def base_path_min_balance(profile: UserProfile, f) -> float:
    bal = profile.balance
    seen = bal
    acc = 0.0
    for x in f:
        acc += x
        seen = min(seen, profile.balance + acc)
    return seen


def amount_safe_to_pay(profile: UserProfile, flows: list[Flow],
                       request: Request) -> float:
    c = config.get()
    f, cr = daily_arrays(flows, request.request_date, c.HORIZON_DAYS)
    F, M = prefix_and_suffix(f)
    x = max_payable_on(profile, 0, f, cr, F, M)
    return max(0.0, min(x, request.requested_amount))


def earliest_full_payment(profile: UserProfile, flows: list[Flow],
                          request: Request) -> Optional[date]:
    """First date t in [request_date, +horizon] where one full payment is safe.
    Suffix-min formulation; M(t) is non-decreasing so a scan finds the first."""
    c = config.get()
    f, cr = daily_arrays(flows, request.request_date, c.HORIZON_DAYS)
    F, M = prefix_and_suffix(f)
    for t in range(c.HORIZON_DAYS + 1):
        x = max_payable_on(profile, t, f, cr, F, M)
        if request.requested_amount <= x + c.EPSILON:
            return request.request_date + timedelta(days=t)
    return None


def payments_are_safe(profile: UserProfile, flows: list[Flow],
                      request: Request,
                      payments: list[tuple[date, float]],
                      spending_delta_by_day: Optional[dict] = None) -> bool:
    """Exact day-by-day verification of an arbitrary payment schedule
    (installments, partials). Optionally applies spending-change deltas
    (day -> net reduction of debits) before checking."""
    c = config.get()
    rd = request.request_date
    n = c.HORIZON_DAYS + 1
    f, cred = daily_arrays(flows, rd, c.HORIZON_DAYS)
    if spending_delta_by_day:
        for day, delta in spending_delta_by_day.items():
            idx = (day - rd).days
            if 0 <= idx < n and delta > 0:
                f[idx] += delta  # delta = reduction in debits = positive flow
    bal = profile.balance
    pays = defaultdict(float)
    for t, amt in payments:
        pays[t] += amt
    for i in range(n):
        day = rd + timedelta(days=i)
        bal += cred[i]          # credits land first
        bal -= pays.get(day, 0.0)  # then the plan payment
        if bal < profile.min_balance - c.EPSILON:
            return False
        bal += (f[i] - cred[i])  # then the day's remaining net (debits are negative)
        if bal < profile.min_balance - c.EPSILON:
            return False
    return True


def run(profile: UserProfile, events: list[LedgerEvent], request: Request,
        amendments: tuple[Amendment, ...], image_amounts: dict[str, float],
        rates) -> ForecastResult:
    c = config.get()
    # resolve blank-amount events from perception BEFORE series inference:
    # they are settled history and shift series means (e.g. event_1700)
    import dataclasses
    events = [dataclasses.replace(e, amount=image_amounts[e.event_id])
              if e.amount is None and e.event_id in image_amounts else e
              for e in events]
    flows, series = build_flows(profile, events, request, amendments,
                                image_amounts, rates)
    safe = amount_safe_to_pay(profile, flows, request)
    edfp = earliest_full_payment(profile, flows, request)
    f, _ = daily_arrays(flows, request.request_date, c.HORIZON_DAYS)
    base_min = base_path_min_balance(profile, f)
    # trough day: day with minimum room
    F, M = prefix_and_suffix(f)
    room = profile.balance - profile.min_balance
    trough_idx = min(range(c.HORIZON_DAYS + 1), key=lambda i: room + M[i])
    sinfos = tuple(SeriesInfo(
        key=str(k), category=s["category"], cadence_days=s["cadence"],
        forecast_value=forecast_value(s["values"]), n_history=len(s["values"]),
        supported=s["supported"]) for k, s in series.items())
    return ForecastResult(
        request_id=request.request_id,
        flows=tuple(sorted(flows, key=lambda x: (x.day, x.amount > 0))),
        series=sinfos,
        amount_safe_to_pay=safe,
        earliest_full_payment=edfp,
        trough_day=request.request_date + timedelta(days=trough_idx),
        base_path_min_balance=base_min,
    )