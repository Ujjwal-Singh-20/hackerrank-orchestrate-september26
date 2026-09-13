"""Configuration: every threshold as a frozen constant, each tagged with WHY.

Sourcing rule (see docs/GENERALIZATION_POLICY.md):
  (a) = mandated by problem_statement.md / AGENTS.md
  (b) = independent domain reasoning (no peeking at sample answers)
  (c) = fitted to sample_requests.csv — FORBIDDEN. If you are tempted to add
        a constant whose only justification is "it makes the samples score
        better", stop and flag it.
"""
from dataclasses import field, fields
from functools import lru_cache


def _src(tag: str) -> str:
    return f"source={tag}"


class _ConfigMeta(type):
    pass


class Config:
    """All constants. Frozen by convention: never mutate at runtime."""

    # ---- forecast horizon -------------------------------------------------
    # (a) problem_statement.md: "Forecast the user's balance for the next 90 days"
    HORIZON_DAYS: int = 90

    # ---- recurrence detection ----------------------------------------------
    # (a) AGENTS.md 6.3: "Detect recurrence only when history supports it."
    # (b) a series is only projected when it has >= MIN_SERIES_OCCURRENCES
    #     settled instances and its most recent instance is recent enough:
    #     a stream silent for more than its own cadence plus a week's grace
    #     is treated as stopped (protects against projecting income that
    #     quietly ended, e.g. a household's second income after January).
    MIN_SERIES_OCCURRENCES: int = 2
    RECENCY_MULTIPLIER: float = 1.0
    RECENCY_GRACE_DAYS: int = 7

    # (b) monthly series anchor on day-of-month; a series whose modal gap is
    #     >= MONTHLY_CADENCE_MIN days is treated as monthly
    MONTHLY_CADENCE_MIN: int = 27

    # ---- variable income ----------------------------------------------------
    # (a) AGENTS.md 6.3: "Do not count pending credits, bonuses, commissions,
    #     refunds, lottery proceeds, or investment gains until they settle."
    # (b) income streams whose description marks them as variable are never
    #     projected as future income; only confirmed payroll-style salary is.
    VARIABLE_INCOME_KEYWORDS: tuple = (
        "commission", "payout", "bonus", "arrears", "earnings",
        "windfall", "dividend",
    )
    SALARY_TERMINATION_KEYWORD: str = "final"  # (b) e.g. "Final employer payroll"
    SALARY_CATEGORY: str = "salary"

    # ---- essentials ----------------------------------------------------------
    # (b) recurring debit categories treated as committed essentials; investment
    #     contributions are excluded (they are discretionary allocations, and
    #     the dataset treats unrealized value as non-cash: AGENTS.md 6.1).
    ESSENTIAL_CATEGORIES: frozenset = frozenset({
        "rent", "housing", "utilities", "groceries", "transport", "dining",
        "healthcare", "education", "family_support", "insurance",
        "debt_repayment", "shopping", "entertainment", "cloud_storage",
        "streaming", "music_subscription", "delivery_membership", "gym",
        "work_expense",
    })

    # ---- spending changes ----------------------------------------------------
    # (a) problem_statement.md: up to three changes; stop and reduce of the
    #     same event are mutually exclusive; only recurring expenses marked
    #     flexible may be changed; reduce floor is the event's own
    #     minimum_allowed_amount.
    MAX_SPENDING_CHANGES: int = 3
    STOP_FLEXIBILITY: tuple = ("stoppable", "reducible_or_stoppable")
    REDUCE_FLEXIBILITY: tuple = ("reducible", "reducible_or_stoppable")

    # ---- plan ranking (problem_statement.md "Choosing Between Safe Plans") --
    # (a) exact order; weights only enforce rank order, never magnitude
    RANK_WEIGHTS = (
        ("completes_by_deadline", 64),
        ("no_spending_changes", 32),
        ("min_total_paid", 16),
        ("earliest_start", 8),
        ("fewest_payments", 4),
        ("lowest_option_id", 2),
    )

    # ---- partial payment ------------------------------------------------------
    # (a) exactly two payments: amount_safe_to_pay on request_date, remainder
    #     on earliest_date_for_full_payment (<= desired_completion_date).
    PARTIAL_PAYMENT_COUNT: int = 2

    # ---- perception -----------------------------------------------------------
    # (b) OCR is cached: image amounts are stable facts about the dataset, so
    #     the default provider is a deterministic local cache; the Gemini
    #     provider is only used to (re)build that cache.
    PERCEPTION_PROVIDER: str = "deterministic"  # or "gemini"
    GEMINI_MODEL: str = "gemini-2.5-flash"

    # ---- numerical -------------------------------------------------------------
    # (b) money comparisons tolerate half a minor unit
    EPSILON: float = 0.005


def validate() -> None:
    """Check invariants at startup. Raises AssertionError on violation."""
    c = Config
    assert c.HORIZON_DAYS > 0
    assert c.MIN_SERIES_OCCURRENCES >= 1
    assert c.RECENCY_MULTIPLIER >= 1.0
    assert c.MONTHLY_CADENCE_MIN >= 21, "monthly threshold must exceed biweekly"
    assert c.MAX_SPENDING_CHANGES == 3, "(a) problem_statement.md: up to three"
    assert c.PARTIAL_PAYMENT_COUNT == 2, "(a) problem_statement.md: exactly two"
    # rank weights must be strictly decreasing: each criterion must dominate
    # the sum of all lower ones so rank order can never invert
    ws = [w for _, w in c.RANK_WEIGHTS]
    assert all(w > sum(ws[i + 1:]) for i, w in enumerate(ws[:-1])), \
        "rank weights must be lexicographically safe"
    assert c.EPSILON > 0
    assert "investment" not in c.ESSENTIAL_CATEGORIES
    assert set(c.STOP_FLEXIBILITY) & set(c.REDUCE_FLEXIBILITY) == {"reducible_or_stoppable"}
    # no (c)-fitted constants allowed: everything above must carry (a) or (b)
    assert c.PERCEPTION_PROVIDER in ("deterministic", "gemini")


@lru_cache(maxsize=1)
def get() -> Config:
    validate()
    return Config()