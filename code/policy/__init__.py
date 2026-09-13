"""policy: plan eligibility, spending changes, and the 6-rule ranking.

Pure functions on typed inputs; no I/O. The ranking is exactly the order in
problem_statement.md ("Choosing Between Safe Plans"):
  1. completes the request by desired_completion_date
  2. requires no spending changes
  3. minimizes total amount paid
  4. starts payment earlier
  5. uses fewer payments
  6. lowest payment_option_id
"""

from __future__ import annotations
import math
import dataclasses

from datetime import date, timedelta
from typing import Optional

import config
from schemas import (Affordability, Decision, ForecastResult, LedgerEvent,
                     PaymentMethod, PaymentOption, PlanCandidate, Request,
                     SpendingChange, UserProfile)
import forecast as F


# ---------------- spending changes ----------------

def _change_candidates(profile: UserProfile, events: list[LedgerEvent],
                       request: Request, fr: ForecastResult) -> list[dict]:
    """Recurring, non-protected, flexible events in categories the user
    permits. Each candidate is applied to its category series from the
    request date onward."""
    c = config.get()
    out = []
    # per category, the change references the LATEST settled instance
    # (sample ground truth: stop:event_476, reduce_to:event_989 are the most
    # recent instances of their categories)
    latest_by_cat = {}
    for e in events:
        if e.status != "settled" or e.direction != "debit":
            continue
        key = (e.event_date, e.event_id)
        if e.category not in latest_by_cat or key > latest_by_cat[e.category][0]:
            latest_by_cat[e.category] = (key, e)
    for category, (_, e) in sorted(latest_by_cat.items()):
        if category in profile.protected_categories:
            continue
        # only recurring categories actually projected in the forecast
        s = next((si for si in fr.series
                  if si.category == category and si.supported), None)
        if s is None or s.forecast_value <= 0:
            continue
        can_stop = (e.flexibility in c.STOP_FLEXIBILITY
                    and category in profile.stop_ok_categories)
        can_reduce = (e.flexibility in c.REDUCE_FLEXIBILITY
                      and category in profile.reduce_ok_categories
                      and e.minimum_allowed_amount is not None)
        if not (can_stop or can_reduce):
            continue
        occurrences = _occurrences_in_horizon(s.cadence_days, request)
        if can_stop:
            out.append({"event_id": e.event_id, "category": category,
                        "action": "stop", "new_amount": None,
                        "saving": s.forecast_value * occurrences})
        if can_reduce:
            floor = e.minimum_allowed_amount
            out.append({"event_id": e.event_id, "category": category,
                        "action": "reduce_to", "new_amount": floor,
                        "saving": (s.forecast_value - floor) * occurrences})
    # deterministic order: biggest saving first; stop before reduce on ties
    out.sort(key=lambda x: (-x["saving"], 0 if x["action"] == "stop" else 1,
                            x["event_id"]))
    return out


def _occurrences_in_horizon(cadence: int, request: Request) -> int:
    c = config.get()
    if cadence <= 0:
        return 0
    return max(1, c.HORIZON_DAYS // max(cadence, 1))


def apply_changes_to_flows(profile, events, request, amendments,
                           image_amounts, rates, changes: list[dict]):
    """Rebuild flows with a set of spending changes applied.

    A change targets a category's recurring series from the request date on:
    'stop' removes future occurrences, 'reduce_to' lowers their amount.
    """
    c = config.get()
    import dataclasses
    stop_categories = {x["category"] for x in changes if x["action"] == "stop"}
    reduce_map = {x["category"]: x["new_amount"] for x in changes
                  if x["action"] == "reduce_to"}
    adjusted = []
    for e in events:
        adjusted.append(e)
    flows, series = F.build_flows(profile, adjusted, request, amendments,
                                  image_amounts, rates)
    out = []
    for fl in flows:
        if not fl.label.endswith(":recurrent") or fl.amount >= 0:
            out.append(fl)
            continue
        cat = fl.label.split(":")[0]
        if cat in stop_categories:
            continue  # stopped: occurrence removed
        if cat in reduce_map:
            out.append(F.Flow(fl.day, -reduce_map[cat], fl.label))
            continue
        out.append(fl)
    return out


def find_changes_for_safety(profile, events, request, amendments,
                            image_amounts, rates, fr: ForecastResult,
                            payments) -> list[dict]:
    """Smallest set of permitted spending changes (greedy by saving, capped)
    that makes `payments` safe. Empty list if the plan is already safe."""
    if F.payments_are_safe(profile, list(fr.flows), request, payments):
        return []
    c = config.get()
    cands = _change_candidates(profile, events, request, fr)
    chosen = []
    for cand in cands:
        if len(chosen) >= c.MAX_SPENDING_CHANGES:
            break
        chosen.append(cand)
        flows = apply_changes_to_flows(profile, events, request, amendments,
                                       image_amounts, rates, chosen)
        if F.payments_are_safe(profile, flows, request, payments):
            return chosen
    return []  # no combination within the cap makes it safe


# ---------------- eligibility ----------------

def _option_months(opt: PaymentOption) -> int:
    """Installment duration in months; single payments take 1."""
    if opt.number_of_payments <= 1:
        return 1
    freq = opt.payment_frequency_days or 30
    return math.ceil(opt.number_of_payments * freq / 30.0)


def _option_schedule(opt: PaymentOption, request: Request):
    """Dated payments for an installment option, exactly as supplied."""
    pays = []
    t = opt.first_payment_date
    for i in range(opt.number_of_payments):
        pays.append((t, opt.payment_amount))
        if i + 1 < opt.number_of_payments:
            t = t + timedelta(days=opt.payment_frequency_days or 0)
    return pays


def _safe_with(flows, profile, request, payments):
    return F.payments_are_safe(profile, flows, request, payments)


def enumerate_candidates(profile: UserProfile, events: list[LedgerEvent],
                         request: Request, fr: ForecastResult,
                         options: list[PaymentOption],
                         amendments, image_amounts, rates) -> list[PlanCandidate]:
    c = config.get()
    out: list[PlanCandidate] = []
    safe = fr.amount_safe_to_pay
    edfp = fr.earliest_full_payment
    methods = profile.payment_methods_considered
    full_pay_date = edfp if (safe >= request.requested_amount - c.EPSILON) \
        else None

    # ---- full payment (today) ----
    if PaymentMethod.FULL.value in methods:
        pays = [(request.request_date, request.requested_amount)]
        changes = []
        if _safe_with(list(fr.flows), profile, request, pays):
            changes = []
            status_ok = True
        else:
            changes = find_changes_for_safety(profile, events, request,
                                              amendments, image_amounts,
                                              rates, fr, pays)
            status_ok = bool(changes)
        if status_ok:
            out.append(PlanCandidate(
                kind=PaymentMethod.FULL, payments=tuple(pays),
                total_paid=request.requested_amount,
                spending_changes=tuple(_mk_change(x) for x in changes),
                completes_by_deadline=request.request_date <= request.desired_completion_date,
                eligible=True, ineligible_reason="",
                start_date=request.request_date))

    # ---- partial payment ----
    if (PaymentMethod.PARTIAL.value in methods
            and request.allows_partial_payment
            and 0 < safe < request.requested_amount - c.EPSILON
            and edfp is not None
            and edfp <= request.desired_completion_date):
        pays = [(request.request_date, safe),
                (edfp, request.requested_amount - safe)]
        if _safe_with(list(fr.flows), profile, request, pays):
            out.append(PlanCandidate(
                kind=PaymentMethod.PARTIAL, payments=tuple(pays),
                total_paid=request.requested_amount,
                spending_changes=(),
                completes_by_deadline=edfp <= request.desired_completion_date,
                eligible=True, ineligible_reason="",
                start_date=request.request_date))

    # ---- installments ----
    if PaymentMethod.INSTALLMENTS.value in methods:
        for opt in sorted(options, key=lambda o: o.payment_option_id):
            if opt.method != "installments":
                continue
            months = _option_months(opt)
            if profile.max_installment_months is not None \
                    and months > profile.max_installment_months:
                continue
            pays = _option_schedule(opt, request)
            last_date = pays[-1][0]
            if last_date > request.desired_completion_date:
                continue
            changes = find_changes_for_safety(profile, events, request,
                                              amendments, image_amounts,
                                              rates, fr, pays)
            if not changes and not _safe_with(list(fr.flows), profile, request, pays):
                continue
            out.append(PlanCandidate(
                kind=PaymentMethod.INSTALLMENTS, payments=tuple(pays),
                total_paid=opt.total_payable_amount,
                spending_changes=tuple(_mk_change(x) for x in changes),
                completes_by_deadline=True, eligible=True,
                ineligible_reason="", option_id=opt.payment_option_id,
                start_date=pays[0][0]))

    # ---- wait ----
    if PaymentMethod.FULL.value in methods and edfp is not None \
            and edfp > request.request_date:
        out.append(PlanCandidate(
            kind=PaymentMethod.WAIT, payments=((edfp, request.requested_amount),),
            total_paid=request.requested_amount, spending_changes=(),
            completes_by_deadline=edfp <= request.desired_completion_date,
            eligible=True, ineligible_reason="", start_date=edfp))

    return out


def _mk_change(cand: dict) -> SpendingChange:
    return SpendingChange(event_id=cand["event_id"], action=cand["action"],
                          new_amount=cand["new_amount"])


# ---------------- ranking ----------------

def rank(candidates: list[PlanCandidate]) -> list[PlanCandidate]:
    """The 6 lexicographic criteria from problem_statement.md, minimized."""
    def key(pc: PlanCandidate):
        return (
            0 if pc.completes_by_deadline else 1,                 # 1
            len(pc.spending_changes),                              # 2
            round(pc.total_paid, 2),                               # 3
            pc.start_date.toordinal() if pc.start_date else 0,     # 4
            len(pc.payments),                                      # 5
            int(pc.option_id.split("_")[-1]) if pc.option_id else 0,  # 6
        )
    return sorted(candidates, key=key)


# ---------------- decision ----------------

def decide(profile: UserProfile, events: list[LedgerEvent], request: Request,
           fr: ForecastResult, options: list[PaymentOption],
           amendments, image_amounts, rates) -> Decision:
    c = config.get()
    cands = enumerate_candidates(profile, events, request, fr, options,
                                 amendments, image_amounts, rates)
    if not cands:
        # No eligible plan exists: the forecast's raw safe-date finding is
        # irrelevant once no eligible plan exists - the Decision carries no
        # earliest full-payment date. (Sample ground truth: every
        # not_affordable row leaves earliest_date_for_full_payment empty.)
        return Decision(
            request_id=request.request_id,
            amount_safe_to_pay=fr.amount_safe_to_pay,
            affordability=Affordability.NEVER,
            method=PaymentMethod.NOT_RECOMMENDED,
            plan=PlanCandidate(kind=PaymentMethod.NOT_RECOMMENDED, payments=(),
                                total_paid=0.0, spending_changes=(),
                                completes_by_deadline=False, eligible=False,
                                ineligible_reason="No payment method you are willing to consider can complete this request safely within 90 days."),
            earliest_full_payment=None,
            spending_changes=())
    best = rank(cands)[0]
    # status mapping
    if best.kind is PaymentMethod.FULL and not best.spending_changes \
            and best.start_date == request.request_date:
        status = Affordability.NOW
    elif best.kind is PaymentMethod.WAIT:
        status = Affordability.LATER
    else:
        status = Affordability.WITH_PLAN
    return Decision(
        request_id=request.request_id,
        amount_safe_to_pay=fr.amount_safe_to_pay,
        affordability=status,
        method=best.kind,
        plan=best,
        earliest_full_payment=fr.earliest_full_payment,
        spending_changes=best.spending_changes,
    )