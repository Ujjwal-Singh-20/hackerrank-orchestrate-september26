"""Typed objects for every stage of the pipeline. Nothing crosses a module
boundary as a raw dict/CSV row."""

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import Optional, Sequence


def fmt_amount(a: float) -> str:
    """Two decimals, trailing zeros stripped (sample style: 25256, 594.88)."""
    s = f"{a:.2f}"
    return s.rstrip("0").rstrip(".") if "." in s else s


# ---------------- ingest layer ----------------

@dataclass(frozen=True)
class UserProfile:
    user_id: str
    home_currency: str
    balance: float
    min_balance: float
    priorities: tuple[str, ...]
    protected_categories: frozenset[str]
    reduce_ok_categories: frozenset[str]
    stop_ok_categories: frozenset[str]
    payment_methods_considered: frozenset[str]
    max_installment_months: Optional[int]


@dataclass(frozen=True)
class LedgerEvent:
    event_id: str
    user_id: str
    event_type: str
    description: str
    category: str
    direction: str
    amount: Optional[float]        # None = blank, resolved via images
    currency: str
    event_date: date
    settlement_date: Optional[date]
    status: str
    linked_event_id: Optional[str]
    flexibility: str
    minimum_allowed_amount: Optional[float]


@dataclass(frozen=True)
class Request:
    request_id: str
    user_id: str
    request_date: date
    request_type: str
    requested_amount: float
    desired_completion_date: date
    allows_partial_payment: bool
    request_text: str


@dataclass(frozen=True)
class PaymentOption:
    payment_option_id: str
    request_id: str
    method: str                   # full_payment | installments
    payment_amount: float
    number_of_payments: int
    first_payment_date: date
    payment_frequency_days: Optional[int]
    financing_fee: float
    total_payable_amount: float


@dataclass(frozen=True)
class Message:
    message_id: str
    user_id: str
    request_id: Optional[str]
    related_event_id: Optional[str]
    sent_at: str
    source_type: str
    text: str


@dataclass(frozen=True)
class ImageEvidence:
    image_id: str
    user_id: str
    request_id: Optional[str]
    related_event_id: Optional[str]
    amount: Optional[float] = None  # from perception layer


@dataclass(frozen=True)
class Dataset:
    profiles: dict[str, UserProfile]
    events: dict[str, LedgerEvent]
    requests: dict[str, Request]
    options: dict[str, list[PaymentOption]]
    messages: list[Message]
    images: list[ImageEvidence]
    rates: dict[tuple[date, str, str], float]

    def events_for_user(self, user_id: str) -> list[LedgerEvent]:
        return [e for e in self.events.values() if e.user_id == user_id]


# ---------------- perception layer ----------------

class AmendmentType(Enum):
    SALARY_AMOUNT = "salary_amount"
    SALARY_TERMINATION = "salary_termination"
    RENT_INCREASE_PCT = "rent_increase_pct"
    EXPENSE_CANCELLED = "expense_cancelled"


@dataclass(frozen=True)
class Amendment:
    kind: AmendmentType
    amount: Optional[float]
    effective_date: Optional[date]
    note: str = ""


@dataclass(frozen=True)
class PerceptionResult:
    """Everything the perception layer contributes for one user."""
    amendments: tuple[Amendment, ...]
    image_amounts: dict[str, float]  # event_id -> amount


# ---------------- forecast layer ----------------

@dataclass(frozen=True)
class Flow:
    day: date
    amount: float                 # signed
    label: str


@dataclass(frozen=True)
class SeriesInfo:
    key: str
    category: str
    cadence_days: int
    forecast_value: float
    n_history: int
    supported: bool


@dataclass(frozen=True)
class ForecastResult:
    request_id: str
    flows: tuple[Flow, ...]
    series: tuple[SeriesInfo, ...]
    amount_safe_to_pay: float
    earliest_full_payment: Optional[date]
    trough_day: date
    base_path_min_balance: float


# ---------------- policy layer ----------------

class PaymentMethod(Enum):
    FULL = "full_payment"
    PARTIAL = "partial_payment"
    INSTALLMENTS = "installments"
    WAIT = "wait"
    NOT_RECOMMENDED = "not_recommended"


class Affordability(Enum):
    NOW = "affordable_now"
    WITH_PLAN = "affordable_with_plan"
    LATER = "affordable_later"
    NEVER = "not_affordable"


@dataclass(frozen=True)
class SpendingChange:
    event_id: str
    action: str                    # "stop" | "reduce_to"
    new_amount: Optional[float]    # for reduce_to

    def encode(self) -> str:
        if self.action == "stop":
            return f"stop:{self.event_id}"
        return f"reduce_to:{self.event_id}:{fmt_amount(self.new_amount)}"


@dataclass(frozen=True)
class PlanCandidate:
    kind: PaymentMethod
    payments: tuple[tuple[date, float], ...]
    total_paid: float
    spending_changes: tuple[SpendingChange, ...]
    completes_by_deadline: bool
    eligible: bool
    ineligible_reason: str
    option_id: Optional[str] = None
    start_date: Optional[date] = None

    _fmt = staticmethod(fmt_amount)

    def payment_plan_string(self) -> str:
        if not self.payments:
            return "none"
        return "|".join(f"{t.isoformat()}:{self._fmt(a)}" for t, a in self.payments)


@dataclass(frozen=True)
class Decision:
    request_id: str
    amount_safe_to_pay: float
    affordability: Affordability
    method: PaymentMethod
    plan: PlanCandidate
    earliest_full_payment: Optional[date]
    spending_changes: tuple[SpendingChange, ...]


# ---------------- compose/emit layer ----------------

@dataclass(frozen=True)
class ExplanationInputs:
    """Only values computed by forecast/policy — compose may not re-derive."""
    currency: str
    requested_amount: float
    amount_safe_to_pay: float
    min_balance: float
    balance: float
    method: str
    affordability: str
    payments: tuple[tuple[date, float], ...]
    earliest_full_payment: Optional[date]
    spending_changes: tuple[str, ...]
    monthly_essential_total: float
    next_income_date: Optional[date]
    reason: str                   # policy's one-line eligibility/safety note


@dataclass(frozen=True)
class OutputRow:
    request_id: str
    amount_safe_to_pay: float
    affordability_status: str
    recommended_payment_method: str
    payment_plan: str
    earliest_date_for_full_payment: str   # "" when none
    spending_changes_needed: str
    decision_explanation: str

    HEADER = ("request_id,amount_safe_to_pay,affordability_status,"
              "recommended_payment_method,payment_plan,"
              "earliest_date_for_full_payment,spending_changes_needed,"
              "decision_explanation")

    def as_csv_row(self) -> list[str]:
        return [
            self.request_id,
            fmt_amount(self.amount_safe_to_pay),
            self.affordability_status,
            self.recommended_payment_method,
            self.payment_plan,
            self.earliest_date_for_full_payment,
            self.spending_changes_needed,
            self.decision_explanation,
        ]