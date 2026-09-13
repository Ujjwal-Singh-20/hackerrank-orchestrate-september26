"""pipeline: ONE composition point. route_one(request_id) is the only place
where modules are wired together; nothing imports across two layers."""

from __future__ import annotations
from typing import Optional

import config
import emit
from errors import RouterError
from ingest import cached_dataset
from perception import get_provider, resolve_blank_amounts
from forecast import run as forecast_run
from policy import decide
from compose import build_explanation
from validate import validate_row
from schemas import (Affordability, ExplanationInputs, OutputRow,
                     PaymentMethod)


def _monthly_essential_total(fr, profile) -> float:
    """Sum of projected recurring debit flows over the horizon / months."""
    horizon_days = config.get().HORIZON_DAYS
    total = -sum(f.amount for f in fr.flows
                 if f.amount < 0 and f.label.endswith(":recurrent"))
    return total / max(horizon_days / 30.0, 1.0)


def _next_income_date(fr, request) -> Optional[str]:
    nxt = [f.day for f in fr.flows
           if f.amount > 0 and f.day >= request.request_date]
    return min(nxt) if nxt else None


def route_one(request_id: str) -> OutputRow:
    """Compose ingest -> perception -> forecast -> policy -> compose ->
    validate for a single request. Raises RouterError subclasses on failure."""
    c = config.get()
    ds = cached_dataset()
    provider = get_provider()

    request = ds.requests[request_id]
    profile = ds.profiles[request.user_id]
    events = ds.events_for_user(request.user_id)

    amendments = provider.extract_amendments(ds, request.user_id)
    image_amounts = resolve_blank_amounts(ds, provider)

    fr = forecast_run(profile, events, request, amendments, image_amounts, ds.rates)
    decision = decide(profile, events, request, fr,
                      ds.options.get(request_id, []), amendments,
                      image_amounts, ds.rates)

    plan = decision.plan
    reason = plan.ineligible_reason
    if decision.method is PaymentMethod.WAIT:
        reason = ("by_deadline" if plan.completes_by_deadline else "after_deadline")

    explanation = build_explanation(ExplanationInputs(
        currency=profile.home_currency,
        requested_amount=request.requested_amount,
        amount_safe_to_pay=decision.amount_safe_to_pay,
        min_balance=profile.min_balance,
        balance=profile.balance,
        method=decision.method.value,
        affordability=decision.affordability.value,
        payments=plan.payments,
        earliest_full_payment=decision.earliest_full_payment,
        spending_changes=tuple(sc.encode() for sc in decision.spending_changes),
        monthly_essential_total=_monthly_essential_total(fr, profile),
        next_income_date=_next_income_date(fr, request),
        reason=reason,
    ))

    row = OutputRow(
        request_id=request.request_id,
        amount_safe_to_pay=round(decision.amount_safe_to_pay, 2),
        affordability_status=decision.affordability.value,
        recommended_payment_method=decision.method.value,
        payment_plan=plan.payment_plan_string(),
        earliest_date_for_full_payment=(decision.earliest_full_payment.isoformat()
                                         if decision.earliest_full_payment else ""),
        spending_changes_needed=("|".join(sc.encode() for sc in decision.spending_changes)
                                 if decision.spending_changes else "none"),
        decision_explanation=explanation,
    )
    # affordable_now must carry request_date as earliest date per the contract
    if row.affordability_status == "affordable_now":
        row = OutputRow(**{**row.__dict__,
                           "earliest_date_for_full_payment": request.request_date.isoformat()})
    validate_row(row, request)
    return row


def route_all() -> list[OutputRow]:
    ds = cached_dataset()
    rows = []
    failures = []
    for rid in sorted(ds.requests):
        try:
            rows.append(route_one(rid))
        except RouterError as e:
            failures.append((rid, type(e).__name__, str(e)))
    if failures:
        # emit what succeeded, but surface the failures loudly
        import sys
        print(f"WARNING: {len(failures)} requests failed routing:", file=sys.stderr)
        for rid, kind, msg in failures[:10]:
            print(f"  {rid}: {kind}: {msg}", file=sys.stderr)
    return rows