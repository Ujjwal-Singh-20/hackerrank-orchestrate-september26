"""compose: decision_explanation built ONLY from values the forecast and
policy modules actually computed. No re-derivation, no raw dataset access."""

from __future__ import annotations
from schemas import ExplanationInputs


def build_explanation(x: ExplanationInputs) -> str:
    """Short, grounded explanation in the style of the solved samples:
    what to do, when, and the two or three financial facts behind it."""
    cur = x.currency
    parts: list[str] = []

    if x.method == "full_payment" and not x.payments:
        parts.append(f"Do not proceed. {x.reason}")
    elif x.method == "full_payment":
        pay = x.payments[0]
        parts.append(
            f"Pay {cur} {pay[1]:,.2f} today. This keeps at least "
            f"{cur} {x.min_balance:,.2f} available over the next 90 days "
            f"(essentials about {cur} {x.monthly_essential_total:,.2f} per month).")
        if x.spending_changes:
            parts.append("Requires adjusting: " + ", ".join(x.spending_changes) + ".")
    elif x.method == "partial_payment":
        first, second = x.payments[0], x.payments[1]
        parts.append(
            f"Pay {cur} {first[1]:,.2f} today and the remaining "
            f"{cur} {second[1]:,.2f} on {second[0].isoformat()}; both payments "
            f"stay within your {cur} {x.min_balance:,.2f} floor.")
    elif x.method == "installments":
        n = len(x.payments)
        parts.append(
            f"Use {n} installments of about {cur} {x.payments[0][1]:,.2f}, "
            f"starting {x.payments[0][0].isoformat()}; total payable "
            f"{cur} {sum(a for _, a in x.payments):,.2f}.")
        if x.spending_changes:
            parts.append("Requires adjusting: " + ", ".join(x.spending_changes) + ".")
    elif x.method == "wait":
        parts.append(
            f"Wait until {x.earliest_full_payment.isoformat()}: paying the full "
            f"{cur} {x.requested_amount:,.2f} becomes safe then"
            + (f", within your deadline." if x.reason == "by_deadline"
               else ", after your deadline.")
            + f" Only {cur} {x.amount_safe_to_pay:,.2f} is safely payable today.")
    else:  # not_recommended
        parts.append(
            f"Do not proceed: the full {cur} {x.requested_amount:,.2f} cannot be "
            f"paid safely within 90 days while keeping your "
            f"{cur} {x.min_balance:,.2f} floor. Essentials run about "
            f"{cur} {x.monthly_essential_total:,.2f} per month.")
        if x.next_income_date:
            parts.append(f"Next confirmed income: {x.next_income_date.isoformat()}.")
        if x.earliest_full_payment is None and x.reason:
            r = x.reason.strip()
            r = r[0].upper() + r[1:]
            if not r.endswith("."):
                r += "."
            parts.append(r)

    return " ".join(p.strip() for p in parts if p.strip())