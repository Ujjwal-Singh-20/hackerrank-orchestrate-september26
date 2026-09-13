# Model Usage Report — Buy or Wait?

Final full-dataset run: **`python3 code/main.py`** over all 250 requests in
`dataset/requests.csv`, producing `output.csv`.

## Providers and models used

| Provider | Model | Role | When |
|---|---|---|---|
| Google | `gemini-2.5-flash` (via Generative Language REST API) | Image OCR: extract amounts for the 16 blank-amount events linked in `dataset/images.csv` | One-time cache rebuild during development; results are cached in `code/perception/__init__.py` and used by the deterministic provider |
| (local) | `zai-org/GLM-OCR` via `transformers` | Initial local OCR experiment | Development only; model files deleted; **not** used in the final run |
| — | deterministic (no model) | Final routing: forecasts, policy, explanations | The final full-dataset run makes **zero** LLM/vision calls |

## Final run (the run that produced output.csv)

- **Model calls: 0.** The final pipeline runs with the deterministic
  perception provider (cached OCR values + regex amendment parsers).
- Input tokens: 0. Output tokens: 0. Model cost: $0.00.
- Per-request average: 0 tokens, $0.00 (250 requests, ~0.04 s/request CPU).

## Development-time model usage (Gemini OCR cache rebuild)

Measured from the API's `usageMetadata` on the 16 image calls
(temperature 0, re-run at report time to capture exact counts):

- Model calls: **16** (one per image; `image_01` … `image_16`)
- Input tokens: **5,696** total (356 per call: image tokens + fixed prompt)
- Output tokens: **857** total (avg 53.6 per call)
- Total tokens: **6,553**; average per request: **409.6** (16 OCR requests)

Cost estimate (Google list pricing for `gemini-2.5-flash` at report time:
~$0.30 / 1M input tokens, ~$2.50 / 1M output tokens):

- Input: 5,696 × $0.30 / 1M ≈ **$0.0017**
- Output: 857 × $2.50 / 1M ≈ **$0.0021**
- **Estimated total: ≈ $0.004** (~$0.0002 per OCR request)

(The earlier local GLM-OCR experiment ran on CPU locally: no API calls, no
tokens, no cost.)

## Overall totals

- Final full-dataset run: 0 calls, 0 tokens, $0.00.
- Including all development-time OCR: 16 calls, 6,553 tokens, ≈ $0.004.

No API keys, credentials, or sensitive configuration are included in this
report or in the submitted code. The Gemini key is read from `.env` (gitignored)
and is required only to rebuild the OCR cache, never for the final run.