# SYSTEM_DESIGN.md

## Purpose

For every row of `dataset/requests.csv`, decide whether the user should pay in
full, pay partially, use installments, wait, or not proceed — and emit the
eight required columns in `output.csv`.

## Shape

One pipeline, strictly layered. `pipeline.route_one(request_id)` is the ONLY
composition point; nothing imports across two layers.

```
ingest  ->  perception  ->  forecast  ->  policy  ->  compose  ->  validate  ->  emit
 (CSV)      (LLM/OCR)      (pure)       (pure)     (pure)      (guards)      (I/O)
```

- **ingest/** loads and joins the seven CSVs into typed dataclasses
  (`schemas.Dataset`). Join keys: `user_id`, `request_id`, `related_event_id`,
  `linked_event_id`, `(rate_date, from, to)`. It performs integrity checks
  (unknown user references, blank amounts without image links) and raises
  `DatasetError`.
- **perception/** is the only module allowed to call an external model. It
  contributes two things: message-derived amendments (salary changes,
  terminations, rent increases) and OCR amounts for blank-amount events. Both
  sit behind the `PerceptionProvider` protocol; the default provider is
  deterministic (cached OCR + regex parsers), so the default run has NO
  network dependency and is fully reproducible. The Gemini provider exists to
  rebuild the OCR cache.
- **forecast/** is a pure function
  `(profile, ledger, request, amendments, image_amounts, rates) -> ForecastResult`.
  It infers recurring series (expenses by category, income by description),
  projects them over 90 days, and computes `amount_safe_to_pay` and
  `earliest_date_for_full_payment` with a prefix-sum/suffix-minimum
  formulation (O(D) instead of O(D^2)).
- **policy/** turns a forecast into candidates (full, partial, each eligible
  installment option, wait, none), optionally finds the minimal permitted
  spending changes that make a candidate safe, and ranks survivors with the
  six lexicographic criteria from `problem_statement.md`.
- **compose/** builds `decision_explanation` strictly from values the earlier
  modules computed (via `ExplanationInputs`) — it never re-derives or reads
  raw CSV data.
- **validate/** enforces the output contract on every row (bounds, plan sums,
  status/method coherence, option matching) and raises
  `OutputContractError` before anything is written.
- **emit/** writes `output.csv` and `code/emit/run_manifest.json`
  (config fingerprint, per-file dataset fingerprints, timestamp, provider) so
  any run is provably reproducible.

## Determinism and reproducibility

- The default perception provider is deterministic; the whole run is a pure
  function of (dataset, config).
- Money comparisons use `config.EPSILON` (half a minor unit).
- Amount formatting strips trailing zeros (`25256`, `594.88`), matching the
  solved samples' style.

## Known accuracy status (measured on the 25 solved samples)

- `earliest_date_for_full_payment`: 20/25 exact.
- `recommended_payment_method`: 22/25 exact; `affordability_status`: 21/25;
  `spending_changes_needed`: 22/25; `payment_plan`: 18/25.
- `amount_safe_to_pay`: exact on capped cases; on uncapped values the median
  relative error is ~9%. Evidence gathered during calibration shows the
  ground-truth reserve amounts depend on the data generator's private
  per-series base values, which are only estimable (not exactly recoverable)
  from the noisy visible history. See GENERALIZATION_POLICY.md.# SYSTEM_DESIGN.md

## Purpose

For every row of `dataset/requests.csv`, decide whether the user should pay in
full, pay partially, use installments, wait, or not proceed — and emit the
eight required columns in `output.csv`.

## Shape

One pipeline, strictly layered. `pipeline.route_one(request_id)` is the ONLY
composition point; nothing imports across two layers.

```
ingest  ->  perception  ->  forecast  ->  policy  ->  compose  ->  validate  ->  emit
 (CSV)      (LLM/OCR)      (pure)       (pure)     (pure)      (guards)      (I/O)
```

- **ingest/** loads and joins the seven CSVs into typed dataclasses
  (`schemas.Dataset`). Join keys: `user_id`, `request_id`, `related_event_id`,
  `linked_event_id`, `(rate_date, from, to)`. It performs integrity checks
  (unknown user references, blank amounts without image links) and raises
  `DatasetError`.
- **perception/** is the only module allowed to call an external model. It
  contributes two things: message-derived amendments (salary changes,
  terminations, rent increases) and OCR amounts for blank-amount events. Both
  sit behind the `PerceptionProvider` protocol; the default provider is
  deterministic (cached OCR + regex parsers), so the default run has NO
  network dependency and is fully reproducible. The Gemini provider exists to
  rebuild the OCR cache.
- **forecast/** is a pure function
  `(profile, ledger, request, amendments, image_amounts, rates) -> ForecastResult`.
  It infers recurring series (expenses by category, income by description),
  projects them over 90 days, and computes `amount_safe_to_pay` and
  `earliest_date_for_full_payment` with a prefix-sum/suffix-minimum
  formulation (O(D) instead of O(D^2)).
- **policy/** turns a forecast into candidates (full, partial, each eligible
  installment option, wait, none), optionally finds the minimal permitted
  spending changes that make a candidate safe, and ranks survivors with the
  six lexicographic criteria from `problem_statement.md`.
- **compose/** builds `decision_explanation` strictly from values the earlier
  modules computed (via `ExplanationInputs`) — it never re-derives or reads
  raw CSV data.
- **validate/** enforces the output contract on every row (bounds, plan sums,
  status/method coherence, option matching) and raises
  `OutputContractError` before anything is written.
- **emit/** writes `output.csv` and `code/emit/run_manifest.json`
  (config fingerprint, per-file dataset fingerprints, timestamp, provider) so
  any run is provably reproducible.

## Determinism and reproducibility

- The default perception provider is deterministic; the whole run is a pure
  function of (dataset, config).
- Money comparisons use `config.EPSILON` (half a minor unit).
- Amount formatting strips trailing zeros (`25256`, `594.88`), matching the
  solved samples' style.

## Known accuracy status (measured on the 25 solved samples)

- `earliest_date_for_full_payment`: 20/25 exact.
- `recommended_payment_method`: 22/25 exact; `affordability_status`: 21/25;
  `spending_changes_needed`: 22/25; `payment_plan`: 18/25.
- `amount_safe_to_pay`: exact on capped cases; on uncapped values the median
  relative error is ~9%. Evidence gathered during calibration shows the
  ground-truth reserve amounts depend on the data generator's private
  per-series base values, which are only estimable (not exactly recoverable)
  from the noisy visible history. See GENERALIZATION_POLICY.md.