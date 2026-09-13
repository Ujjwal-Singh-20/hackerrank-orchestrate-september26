"""ingest: load and join the dataset CSVs into typed objects. Nothing else."""

from __future__ import annotations
import csv
from datetime import date
from pathlib import Path
from typing import Optional
from functools import lru_cache

from errors import DatasetError
from schemas import (Dataset, ImageEvidence, LedgerEvent, Message,
                     PaymentOption, Request, UserProfile)

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "dataset"


def _d(s: str) -> Optional[date]:
    if not s:
        return None
    try:
        return date.fromisoformat(s)
    except ValueError as e:
        raise DatasetError(f"bad date {s!r}: {e}") from e


def _f(s: str, ctx: str) -> Optional[float]:
    if s is None or s == "":
        return None
    try:
        return float(s)
    except ValueError as e:
        raise DatasetError(f"bad amount {s!r} in {ctx}") from e


def _pipe(s: str) -> tuple:
    return tuple(x for x in (s or "").split("|") if x)


def _rows(name: str):
    path = DATA_DIR / f"{name}.csv"
    if not path.exists():
        raise DatasetError(f"missing required file: {path}")
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def load_dataset() -> Dataset:
    profiles = {}
    for r in _rows("financial_profiles"):
        uid = r["user_id"]
        try:
            max_inst = int(r["max_installment_months"]) if r["max_installment_months"] else None
        except ValueError as e:
            raise DatasetError(f"bad max_installment_months for {uid}") from e
        profiles[uid] = UserProfile(
            user_id=uid,
            home_currency=r["home_currency"],
            balance=_f(r["current_available_balance"], uid) or 0.0,
            min_balance=_f(r["minimum_balance_to_keep"], uid) or 0.0,
            priorities=_pipe(r["financial_priorities"]),
            protected_categories=frozenset(_pipe(r["expense_categories_to_protect"])),
            reduce_ok_categories=frozenset(_pipe(r["expense_categories_user_is_willing_to_reduce"])),
            stop_ok_categories=frozenset(_pipe(r["expense_categories_user_is_willing_to_stop"])),
            payment_methods_considered=frozenset(_pipe(r["payment_methods_user_will_consider"])),
            max_installment_months=max_inst,
        )

    events = {}
    for r in _rows("financial_events"):
        eid = r["event_id"]
        events[eid] = LedgerEvent(
            event_id=eid,
            user_id=r["user_id"],
            event_type=r["event_type"],
            description=r["description"],
            category=r["category"],
            direction=r["direction"],
            amount=_f(r["amount"], eid),
            currency=r["currency"],
            event_date=_d(r["event_date"]),
            settlement_date=_d(r["settlement_date"]),
            status=r["status"],
            linked_event_id=r["linked_event_id"] or None,
            flexibility=r["flexibility"],
            minimum_allowed_amount=_f(r["minimum_allowed_amount"], eid),
        )

    requests = {}
    for r in _rows("requests"):
        rid = r["request_id"]
        requests[rid] = Request(
            request_id=rid,
            user_id=r["user_id"],
            request_date=_d(r["request_date"]),
            request_type=r["request_type"],
            requested_amount=_f(r["requested_amount"], rid) or 0.0,
            desired_completion_date=_d(r["desired_completion_date"]),
            allows_partial_payment=r["allows_partial_payment"].strip().lower() == "true",
            request_text=r["request_text"],
        )

    options: dict[str, list[PaymentOption]] = {}
    for r in _rows("request_payment_options"):
        oid = r["payment_option_id"]
        opt = PaymentOption(
            payment_option_id=oid,
            request_id=r["request_id"],
            method=r["payment_method"],
            payment_amount=_f(r["payment_amount"], oid) or 0.0,
            number_of_payments=int(r["number_of_payments"]),
            first_payment_date=_d(r["first_payment_date"]),
            payment_frequency_days=int(r["payment_frequency_days"]) if r["payment_frequency_days"] else None,
            financing_fee=_f(r["financing_fee"], oid) or 0.0,
            total_payable_amount=_f(r["total_payable_amount"], oid) or 0.0,
        )
        options.setdefault(opt.request_id, []).append(opt)

    messages = [Message(
        message_id=r["message_id"],
        user_id=r["user_id"],
        request_id=r["request_id"] or None,
        related_event_id=r["related_event_id"] or None,
        sent_at=r["sent_at"],
        source_type=r["source_type"],
        text=r["message_text"],
    ) for r in _rows("messages")]

    images = [ImageEvidence(
        image_id=r["image_id"],
        user_id=r["user_id"],
        request_id=r["request_id"] or None,
        related_event_id=r["related_event_id"] or None,
    ) for r in _rows("images")]

    rates = {}
    for r in _rows("exchange_rates"):
        rates[(_d(r["rate_date"]), r["from_currency"], r["to_currency"])] = float(r["rate"])

    # join integrity checks
    for req in requests.values():
        if req.user_id not in profiles:
            raise DatasetError(f"request {req.request_id} references unknown user {req.user_id}")
    for eid, e in events.items():
        if e.user_id not in profiles:
            raise DatasetError(f"event {eid} references unknown user {e.user_id}")

    return Dataset(profiles=profiles, events=events, requests=requests,
                   options=options, messages=messages, images=images, rates=rates)


@lru_cache(maxsize=1)
def cached_dataset() -> Dataset:
    return load_dataset()