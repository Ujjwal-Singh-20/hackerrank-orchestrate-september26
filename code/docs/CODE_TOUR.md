# CODE_TOUR.md

A guided map. If you are being quizzed on this codebase, this is the script.

## Start here: `code/main.py`

`main()` validates config, routes every request, writes `output.csv` plus a
reproducibility manifest. ~40 lines; everything interesting happens one
layer down.

```
python3 code/main.py          # full run, ~250 rows, < 30 s, no network
python3 -m unittest discover code/tests   # 22 tests, < 1 s
```

## The one composition point: `code/pipeline.py`

`route_one(request_id)` is the only function that knows the order of
operations:

1. `ingest.cached_dataset()` — typed dataset (loaded once, joined).
2. `perception.get_provider()` — amendments + OCR amounts for this user.
3. `forecast.run(...)` — pure 90-day simulation -> `ForecastResult`.
4. `policy.decide(...)` — candidates, spending changes, ranking -> `Decision`.
5. `compose.build_explanation(...)` — text built only from computed values.
6. `validate.validate_row(...)` — contract check, raises before emit.
7. `emit.write_output(...)` in main, after all rows route.

Nothing imports across two layers: `compose` never touches ingest, `policy`
never opens a file, `forecast` is importable with no I/O at all.

## `code/config.py`

Every threshold, tagged (a)/(b)/(c) with (c) forbidden. `validate()` asserts
the invariants (rank weights strictly dominate, non-negative bounds,
essential-set excludes investment). If asked "why 1.5x?" — that's the
recency multiplier for a stopped-series heuristic, source (b); if asked
"why 90 days?" — problem_statement.md, source (a).

## `code/schemas.py`

Dataclasses only, no pydantic (zero-dependency rule). The tour-worthy ones:
`ForecastResult` (flows + safe + edfp + trough), `PlanCandidate` (payments,
changes, ranking fields), `OutputRow` (header + CSV rendering with
sample-style amount formatting via `fmt_amount`).

## `code/ingest/`

Loads the 7 CSVs into `Dataset`, checks join integrity. Gotchas encoded
here: sample requests (01–25) are NOT in `requests.csv` — that file is the
eval set (26–275). Blank `amount` is legal only when an image links to the
event.

## `code/perception/`

`PerceptionProvider` protocol; `DeterministicPerception` is the default
(regex amendment parsers + cached OCR; no network). `GeminiPerception`
(same package) rebuilds the OCR cache with `gemini-2.5-flash`; the key comes
from `.env`, is never logged, and `.env` is gitignored. The amendments layer
understands: salary changes (with/without explicit effective date), salary
termination ("contract has ended", "Final employer payroll" via forecast),
rent increase percentages.

## `code/forecast/`

The math core. Three ideas worth explaining on a whiteboard:

1. **Series inference** — expenses group by category, income by description;
   modal-gap cadence; monthly series anchor on day-of-month; recurrence
   needs >= 2 instances and a recent last instance.
2. **`amount_safe_to_pay`** — with flows fixed, the max payable on day t is
   `room + min(mid-day trough, suffix-min of cumulative net)`. One prefix
   pass, one suffix pass.
3. **`earliest_full_payment`** — the suffix minimum M(t) is non-decreasing
   in t, so the first date where `requested <= max_payable(t)` is found in
   one scan. (The naive version re-simulated 91 times; this is 1000x faster
   and provably identical — verified 25/25 against the slow loop.)
   `payments_are_safe` is the exact day-by-day verifier kept for arbitrary
   schedules (installments, partials) and for final plan validation.

## `code/policy/`

`enumerate_candidates` builds the eligible set (see
`docs/DECISION_ENGINE.md` for every gate). `find_changes_for_safety` greedily
adds permitted spending changes (biggest saving first, latest event instance
per category, capped at 3) until the plan passes `payments_are_safe`.
`rank` implements the six lexicographic criteria; the weights in config make
the order non-invertible by construction.

## `code/compose/`, `code/validate/`, `code/emit/`

- `compose` receives an `ExplanationInputs` containing ONLY values other
  modules computed — the enforced way to keep the explanation grounded.
- `validate` is the output contract from problem_statement.md, one assert
  per invariant: bounds, chronological plans, two-payment partials summing
  to the request, installment plans matching a supplied option,
  status/method coherence.
- `emit` writes the CSV and `run_manifest.json` (config hash + dataset
  file fingerprints + timestamp). Two runs over the same inputs produce
  byte-identical output.csv rows.

## Legacy / calibration artifacts (not part of the build)

- `code/engine.py` + `code/run_samples.py` — the reverse-engineering
  harness used during calibration (kept for the transcript story).
- `code/search.py`, `code/diag.py`, `code/calibrate.py` — grid searches
  over forecast rules used to establish the (b) choices above.
- `code/ocr_gemini.py` — one-off OCR rebuild tool for the image cache.

## Sample-measured status (the number you'll be asked about)

method 22/25, status 21/25, changes 22/25, plan 18/25, edfp 20/25 exact;
safe amounts: exact where capped, ~9% median error elsewhere (see
GENERALIZATION_POLICY.md for why that ceiling exists). The four remaining
method/status misses (request_06, 11, 13, 21) trace to forecast value
residuals, not to policy logic.