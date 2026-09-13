"""validate: hard invariant checks on OutputRows before writing output.csv.
Every rule here comes from problem_statement.md / AGENTS.md 6.2."""

from __future__ import annotations
from datetime import date
from typing import Iterable, Sequence

import config
from errors import OutputContractError
from schemas import OutputRow, Request


ALLOWED_STATUS = {"affordable_now", "affordable_with_plan",
                  "affordable_later", "not_affordable"}
ALLOWED_METHOD = {"full_payment", "partial_payment", "installments",
                  "wait", "not_recommended"}


def validate_row(row: OutputRow, request: Request) -> None:
    c = config.get()
    eps = c.EPSILON

    def fail(msg: str):
        raise OutputContractError(f"{row.request_id}: {msg}")

    if row.affordability_status not in ALLOWED_STATUS:
        fail(f"bad affordability_status {row.affordability_status!r}")
    if row.recommended_payment_method not in ALLOWED_METHOD:
        fail(f"bad method {row.recommended_payment_method!r}")

    # 0 <= amount_safe_to_pay <= requested_amount  (problem_statement.md)
    if not (-eps <= row.amount_safe_to_pay <= request.requested_amount + eps):
        fail(f"amount_safe_to_pay {row.amount_safe_to_pay} outside "
             f"[0, {request.requested_amount}]")

    # affordable_now => earliest date == request_date
    if row.affordability_status == "affordable_now":
        if row.earliest_date_for_full_payment != request.request_date.isoformat():
            fail("affordable_now requires earliest_date_for_full_payment == request_date")

    # not_affordable => no earliest date (symmetric invariant; a raw forecast
    # safe-date must never leak into a row where no eligible plan exists)
    if row.affordability_status == "not_affordable":
        if row.earliest_date_for_full_payment != "":
            fail("not_affordable requires earliest_date_for_full_payment to be empty")

    # payment_plan parse + checks
    if row.payment_plan != "none":
        try:
            pays = [(date.fromisoformat(p.split(":")[0]),
                     float(p.split(":")[1]))
                    for p in row.payment_plan.split("|")]
        except (ValueError, IndexError):
            fail(f"unparseable payment_plan {row.payment_plan!r}")
            return
        if pays != sorted(pays, key=lambda x: x[0]):
            fail("payment_plan not chronological")
        if any(a <= 0 for _, a in pays):
            fail("non-positive payment in plan")
        if row.recommended_payment_method == "partial_payment":
            if len(pays) != c.PARTIAL_PAYMENT_COUNT:
                fail("partial_payment must have exactly two payments")
            if abs(pays[0][0] - request.request_date).days != 0:
                fail("partial_payment first payment must be on request_date")
            if abs(sum(a for _, a in pays) - request.requested_amount) > eps:
                fail("partial payments must sum to requested_amount")
            if pays[1][0] > request.desired_completion_date:
                fail("partial second payment after desired_completion_date")
            if abs(pays[0][1] - row.amount_safe_to_pay) > eps:
                fail("partial first payment must equal amount_safe_to_pay")
        if row.recommended_payment_method in ("full_payment", "wait") \
                and len(pays) != 1:
            fail("full_payment/wait must be a single payment")
        if row.recommended_payment_method == "not_recommended" \
                and row.payment_plan != "none":
            fail("not_recommended must have payment_plan none")
    else:
        if row.recommended_payment_method not in ("not_recommended",):
            fail(f"{row.recommended_payment_method} with payment_plan none")

    # spending changes
    if row.spending_changes_needed != "none":
        changes = row.spending_changes_needed.split("|")
        if len(changes) > c.MAX_SPENDING_CHANGES:
            fail("more than three spending changes")
        ids = [x.split(":")[1] for x in changes]
        if len(ids) != len(set(ids)):
            fail("stop and reduce on the same event are mutually exclusive")
        for ch in changes:
            if not (ch.startswith("stop:") or ch.startswith("reduce_to:")):
                fail(f"bad spending change {ch!r}")

    # status/method coherence
    if row.recommended_payment_method == "partial_payment" \
            and row.affordability_status != "affordable_with_plan":
        fail("partial_payment requires affordable_with_plan")
    if row.affordability_status == "affordable_later" \
            and row.recommended_payment_method != "wait":
        fail("affordable_later requires wait")
    if row.affordability_status == "not_affordable" \
            and row.recommended_payment_method != "not_recommended":
        fail("not_affordable requires not_recommended")


def validate_all(rows: Iterable[OutputRow], requests: dict) -> None:
    rows = list(rows)
    if len(rows) != len(requests):
        raise OutputContractError(
            f"row count {len(rows)} != request count {len(requests)}")
    seen = set()
    for row in rows:
        if row.request_id in seen:
            raise OutputContractError(f"duplicate row {row.request_id}")
        seen.add(row.request_id)
        validate_row(row, requests[row.request_id])