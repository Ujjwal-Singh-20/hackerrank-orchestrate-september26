# GENERALIZATION_POLICY.md

## The rule

Every constant in `code/config.py` is tagged with its justification:

- **(a)** mandated by `problem_statement.md` or `AGENTS.md`
  (e.g., `HORIZON_DAYS = 90`, `MAX_SPENDING_CHANGES = 3`,
  `PARTIAL_PAYMENT_COUNT = 2`, the 6-criterion ranking order).
- **(b)** independent domain reasoning that would hold for any financially
  plausible user (e.g., a series silent for 1.5x its own cadence is treated
  as stopped; variable income streams are not forecast; investment
  contributions are not reserved essentials).
- **(c)** fitted to `sample_requests.csv` — **FORBIDDEN** in config. If a
  constant's only justification is "it makes the samples score better",
  it must not exist. `config.validate()` cannot detect this mechanically;
  the discipline is procedural: any (c)-temptation must be flagged in review.

## What we learned from the samples anyway (and where it lives)

Reverse-engineering the 25 solved samples produced *structural* knowledge:
salary-termination semantics, amendment message phrasings, same-day credit
ordering, description-grouped income streams, the "latest event instance"
rule for spending changes. These are implemented as **general rules** in
forecast/policy, not as per-sample constants — they would apply to any user
generated the same way. That knowledge is legitimate (b)-adjacent: it is a
model of the domain, testable on held-out requests, and nothing in the code
keys off `request_id` or `user_id`.

Test expectations in `tests/test_forecast_samples.py` DO encode the measured
sample status (e.g., "edfp exact >= 20/25"). That is a regression test on
known behavior, not a model constant; if it fails, something regressed.

## The one honest caveat

The ground-truth `amount_safe_to_pay` values appear to be computed from the
data generator's private per-series "base" amounts (e.g., user_02's reserve
includes ~1,107,627 IDR that appears in visible history only as a single
noisy observation of ~1.35M). These are not exactly recoverable from the
visible data, so exact match on that column has an information-theoretic
ceiling. Our forecast uses `round(mean(history))` — an unbiased estimator of
the same base — and we accept the resulting dispersion rather than fit
per-user corrections, which would be (c) by definition.

## OCR values

`perception.IMAGE_AMOUNT_CACHE` holds the 16 extracted image amounts. These
are facts about the provided dataset (extracted via Gemini OCR, cached for
determinism), not fitted labels. `event_1442` uses the receipt's Balance Due
(100,000 INR) because the linked event is described as an "Outstanding rent
balance".# GENERALIZATION_POLICY.md

## The rule

Every constant in `code/config.py` is tagged with its justification:

- **(a)** mandated by `problem_statement.md` or `AGENTS.md`
  (e.g., `HORIZON_DAYS = 90`, `MAX_SPENDING_CHANGES = 3`,
  `PARTIAL_PAYMENT_COUNT = 2`, the 6-criterion ranking order).
- **(b)** independent domain reasoning that would hold for any financially
  plausible user (e.g., a series silent for 1.5x its own cadence is treated
  as stopped; variable income streams are not forecast; investment
  contributions are not reserved essentials).
- **(c)** fitted to `sample_requests.csv` — **FORBIDDEN** in config. If a
  constant's only justification is "it makes the samples score better",
  it must not exist. `config.validate()` cannot detect this mechanically;
  the discipline is procedural: any (c)-temptation must be flagged in review.

## What we learned from the samples anyway (and where it lives)

Reverse-engineering the 25 solved samples produced *structural* knowledge:
salary-termination semantics, amendment message phrasings, same-day credit
ordering, description-grouped income streams, the "latest event instance"
rule for spending changes. These are implemented as **general rules** in
forecast/policy, not as per-sample constants — they would apply to any user
generated the same way. That knowledge is legitimate (b)-adjacent: it is a
model of the domain, testable on held-out requests, and nothing in the code
keys off `request_id` or `user_id`.

Test expectations in `tests/test_forecast_samples.py` DO encode the measured
sample status (e.g., "edfp exact >= 20/25"). That is a regression test on
known behavior, not a model constant; if it fails, something regressed.

## The one honest caveat

The ground-truth `amount_safe_to_pay` values appear to be computed from the
data generator's private per-series "base" amounts (e.g., user_02's reserve
includes ~1,107,627 IDR that appears in visible history only as a single
noisy observation of ~1.35M). These are not exactly recoverable from the
visible data, so exact match on that column has an information-theoretic
ceiling. Our forecast uses `round(mean(history))` — an unbiased estimator of
the same base — and we accept the resulting dispersion rather than fit
per-user corrections, which would be (c) by definition.

## OCR values

`perception.IMAGE_AMOUNT_CACHE` holds the 16 extracted image amounts. These
are facts about the provided dataset (extracted via Gemini OCR, cached for
determinism), not fitted labels. `event_1442` uses the receipt's Balance Due
(100,000 INR) because the linked event is described as an "Outstanding rent
balance".