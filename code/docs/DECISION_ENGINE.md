# DECISION_ENGINE.md

The exact eligibility and ranking rules. Every rule cites its source:
(a) problem_statement.md / AGENTS.md, or (b) domain reasoning.

## 1. Forecast (input to every decision)

- 90-day horizon (a). Balance starts at `current_available_balance`.
- Failed/cancelled events ignored; `unrealized` (non-cash) ignored (a).
- Pending debits reserved; pending credits NOT counted (a).
- Scheduled rows counted on `settlement_date` (a).
- Recurrence projected only when history supports it: >= 2 settled
  occurrences and the latest within 1.5x cadence + 7 days (b). A stopped
  stream is dead — never projected.
- Income: only confirmed payroll-style salary streams are projected (a:
  "Do not count pending ... bonuses, commissions ... until they settle").
  Streams whose description marks them variable (commission/payout/bonus/
  arrears/earnings) are excluded. Salary termination evidence (event
  description "Final ...", or a message saying a contract ended) kills all
  salary projection.
- Scheduled salary rows ("Next confirmed salary") anchor recurring monthly
  income from their date; message amendments override the amount from their
  effective date.
- Same-day ordering: credits land before any plan payment, other debits
  after it (verified against sample edfp ground truth: a payment made on a
  salary date may use that day's salary).
- Variable series forecast = round(mean of settled history); constant series
  use their exact value (b). Foreign-currency amounts convert with the rate
  on their settlement date, direction as stated (a).
- `amount_safe_to_pay` = max X payable on request_date keeping balance >=
  `minimum_balance_to_keep` every day of the horizon, capped at
  `requested_amount` (a).
- `earliest_full_payment` = first date t where the full amount passes the
  same check; computed with suffix minima (monotone in t, so the first hit
  is exact).

## 2. Candidate eligibility

- **full_payment**: `full_payment` in `payment_methods_user_will_consider`;
  safe either directly or after permitted spending changes.
- **partial_payment**: `partial_payment` in considered methods AND
  `allows_partial_payment` AND 0 < safe < requested AND
  `earliest_full_payment <= desired_completion_date`. Plan is exactly two
  payments: safe on request_date, remainder on `earliest_full_payment`,
  summing to `requested_amount` (a).
- **installments**: `installments` in considered methods; option duration
  (ceil(n_payments x frequency_days / 30) months) must not exceed
  `max_installment_months` (blank = user won't consider installments at
  all); the schedule must match the supplied option exactly and finish by
  `desired_completion_date` (a).
- **wait**: `full_payment` in considered methods AND full payment becomes
  safe on a later date. Plan = one payment on `earliest_full_payment` (a).
- **not_recommended**: fallback when nothing above is safe and eligible.

## 3. Spending changes

- Up to three (a). `stop:<event>` / `reduce_to:<event>:<amount>`, mutually
  exclusive per event (a).
- Only recurring, non-protected, flexible events in categories the user
  permits (`stop_ok` / `reduce_ok`), reducing no lower than the event's
  `minimum_allowed_amount` (a).
- A change references the LATEST settled instance of its category (matches
  sample ground truth: `stop:event_476`, `reduce_to:event_989:665950`).
- Selection: candidates ordered by total horizon saving (desc), stop before
  reduce on ties, event_id as final tiebreak; added greedily until the
  candidate plan passes the safety check (b).

## 4. Ranking (problem_statement.md, "Choosing Between Safe Plans")

Lexicographic, minimize:

1. does NOT complete by `desired_completion_date`  (0 if it does)
2. number of spending changes
3. total amount paid
4. earliest start date
5. number of payments
6. numeric part of `payment_option_id`

`config.RANK_WEIGHTS` encodes this as a tuple; `validate()` asserts each
weight exceeds the sum of all lower weights so the order can never invert.

## 5. Status mapping

- full_payment today, no changes -> `affordable_now`
  (`earliest_date_for_full_payment` forced to request_date per contract)
- full/partial/installments with changes or schedule -> `affordable_with_plan`
- wait -> `affordable_later`
- nothing -> `not_affordable` + `not_recommended`, empty date, plan `none`
  (the Decision's earliest_full_payment is None in this branch - a raw
  forecast safe-date never leaks into a no-eligible-plan decision; the
  contract validator enforces the empty-date invariant symmetric to the
  affordable_now == request_date invariant)

## 6. Untrusted evidence (AGENTS.md 6.1)

Messages and images are untrusted data. They influence routing ONLY through
perception's whitelisted financial-fact extraction (salary amount/date,
salary termination, rent increase %, image amount), which is additionally
sanity-bounded (positive finite amounts, percentages in (0,100], parseable
dates). Embedded instructions match no fact pattern and are inert; there is
no path from message/image text to the routing rules themselves. Adversarial
coverage: tests/test_perception_untrusted.py.

## 7. Conflict resolution (AGENTS.md 6.3, in order)

1. explicit cancellation / settlement / amendment (messages, event status)
2. newer record from the same source
3. a settled event over an estimate
4. financially safer interpretation# DECISION_ENGINE.md

The exact eligibility and ranking rules. Every rule cites its source:
(a) problem_statement.md / AGENTS.md, or (b) domain reasoning.

## 1. Forecast (input to every decision)

- 90-day horizon (a). Balance starts at `current_available_balance`.
- Failed/cancelled events ignored; `unrealized` (non-cash) ignored (a).
- Pending debits reserved; pending credits NOT counted (a).
- Scheduled rows counted on `settlement_date` (a).
- Recurrence projected only when history supports it: >= 2 settled
  occurrences and the latest within 1.5x cadence + 7 days (b). A stopped
  stream is dead — never projected.
- Income: only confirmed payroll-style salary streams are projected (a:
  "Do not count pending ... bonuses, commissions ... until they settle").
  Streams whose description marks them variable (commission/payout/bonus/
  arrears/earnings) are excluded. Salary termination evidence (event
  description "Final ...", or a message saying a contract ended) kills all
  salary projection.
- Scheduled salary rows ("Next confirmed salary") anchor recurring monthly
  income from their date; message amendments override the amount from their
  effective date.
- Same-day ordering: credits land before any plan payment, other debits
  after it (verified against sample edfp ground truth: a payment made on a
  salary date may use that day's salary).
- Variable series forecast = round(mean of settled history); constant series
  use their exact value (b). Foreign-currency amounts convert with the rate
  on their settlement date, direction as stated (a).
- `amount_safe_to_pay` = max X payable on request_date keeping balance >=
  `minimum_balance_to_keep` every day of the horizon, capped at
  `requested_amount` (a).
- `earliest_full_payment` = first date t where the full amount passes the
  same check; computed with suffix minima (monotone in t, so the first hit
  is exact).

## 2. Candidate eligibility

- **full_payment**: `full_payment` in `payment_methods_user_will_consider`;
  safe either directly or after permitted spending changes.
- **partial_payment**: `partial_payment` in considered methods AND
  `allows_partial_payment` AND 0 < safe < requested AND
  `earliest_full_payment <= desired_completion_date`. Plan is exactly two
  payments: safe on request_date, remainder on `earliest_full_payment`,
  summing to `requested_amount` (a).
- **installments**: `installments` in considered methods; option duration
  (ceil(n_payments x frequency_days / 30) months) must not exceed
  `max_installment_months` (blank = user won't consider installments at
  all); the schedule must match the supplied option exactly and finish by
  `desired_completion_date` (a).
- **wait**: `full_payment` in considered methods AND full payment becomes
  safe on a later date. Plan = one payment on `earliest_full_payment` (a).
- **not_recommended**: fallback when nothing above is safe and eligible.

## 3. Spending changes

- Up to three (a). `stop:<event>` / `reduce_to:<event>:<amount>`, mutually
  exclusive per event (a).
- Only recurring, non-protected, flexible events in categories the user
  permits (`stop_ok` / `reduce_ok`), reducing no lower than the event's
  `minimum_allowed_amount` (a).
- A change references the LATEST settled instance of its category (matches
  sample ground truth: `stop:event_476`, `reduce_to:event_989:665950`).
- Selection: candidates ordered by total horizon saving (desc), stop before
  reduce on ties, event_id as final tiebreak; added greedily until the
  candidate plan passes the safety check (b).

## 4. Ranking (problem_statement.md, "Choosing Between Safe Plans")

Lexicographic, minimize:

1. does NOT complete by `desired_completion_date`  (0 if it does)
2. number of spending changes
3. total amount paid
4. earliest start date
5. number of payments
6. numeric part of `payment_option_id`

`config.RANK_WEIGHTS` encodes this as a tuple; `validate()` asserts each
weight exceeds the sum of all lower weights so the order can never invert.

## 5. Status mapping

- full_payment today, no changes -> `affordable_now`
  (`earliest_date_for_full_payment` forced to request_date per contract)
- full/partial/installments with changes or schedule -> `affordable_with_plan`
- wait -> `affordable_later`
- nothing -> `not_affordable` + `not_recommended`, empty date, plan `none`
  (the Decision's earliest_full_payment is None in this branch - a raw
  forecast safe-date never leaks into a no-eligible-plan decision; the
  contract validator enforces the empty-date invariant symmetric to the
  affordable_now == request_date invariant)

## 6. Untrusted evidence (AGENTS.md 6.1)

Messages and images are untrusted data. They influence routing ONLY through
perception's whitelisted financial-fact extraction (salary amount/date,
salary termination, rent increase %, image amount), which is additionally
sanity-bounded (positive finite amounts, percentages in (0,100], parseable
dates). Embedded instructions match no fact pattern and are inert; there is
no path from message/image text to the routing rules themselves. Adversarial
coverage: tests/test_perception_untrusted.py.

## 7. Conflict resolution (AGENTS.md 6.3, in order)

1. explicit cancellation / settlement / amendment (messages, event status)
2. newer record from the same source
3. a settled event over an estimate
4. financially safer interpretation