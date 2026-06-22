# TTB Label Verification

Proof-of-concept for TTB label verification.

## Local Setup

Backend:

```bash
cd backend
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export APP_ENV=local
export ALLOWED_ORIGINS=http://localhost:5173
export GEMINI_API_KEY=<your Gemini API key>
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Frontend, in a second terminal:

```bash
cd frontend
python3 -m http.server 5173
```

Open `http://localhost:5173`. The page should show the single-label
verification form.

The frontend reads its backend URL from `frontend/config.js`. For local
development against the deployed Render backend, keep:

```js
window.APP_CONFIG = {
  API_BASE_URL: "https://latrell-price-ttb-label-verification-app.onrender.com",
};
```

To point the same static frontend at another backend later, change only
`API_BASE_URL`.

Run all backend tests:

```bash
backend/.venv/bin/pytest
```

Run only the Phase 1 comparison engine tests:

```bash
backend/.venv/bin/pytest backend/tests/test_verification.py
```

Show the strict case-sensitive government warning test:

```bash
backend/.venv/bin/pytest backend/tests/test_verification.py -k government_warning_title_case_fails_strict_case_sensitive_comparison -vv
```

Run the Phase 2 vision sample script against a generated label image with
mock extraction data:

```bash
backend/.venv/bin/python backend/scripts/run_vision_sample.py --mock
```

Or call the real Gemini vision service by setting an API key:

```bash
export GEMINI_API_KEY=<your Gemini API key>
backend/.venv/bin/python backend/scripts/run_vision_sample.py
```

You can also pass an existing image:

```bash
backend/.venv/bin/python backend/scripts/run_vision_sample.py /path/to/label.jpg
```

## Phase 6 Hardening

Phase 6 keeps the production vision path on Gemini Flash via the Google AI API
free-tier workflow. Do not switch hardening or benchmark work to paid OpenAI
vision models. The default production model remains `gemini-3.5-flash`, with
`GEMINI_MODEL` available only for measurement-gated Gemini variants.

Run the repeatable benchmark with the deterministic fake provider:

```bash
backend/.venv/bin/python backend/scripts/benchmark_phase6.py --mock --runs 3 --jsonl /tmp/ttb-phase6.jsonl
```

Run the same fixture set against Gemini free-tier credentials:

```bash
export GEMINI_API_KEY=<your Gemini API key>
backend/.venv/bin/python backend/scripts/benchmark_phase6.py --runs 30 --jsonl /tmp/ttb-phase6-gemini.jsonl
```

Tune image settings without changing application code:

```bash
backend/.venv/bin/python backend/scripts/benchmark_phase6.py --runs 30 --max-edge 1600 --jpeg-quality 78 --jsonl /tmp/ttb-phase6-1600-q78.jsonl
```

Benchmark pass targets for warm backend requests, excluding Render free-plan
cold starts:

| Measurement | Target |
| --- | --- |
| Single-label p50 | <= 3000 ms |
| Single-label p95 | <= 4500 ms |
| Single-label max | <= 5000 ms |
| Preprocessing p95 | <= 350 ms |
| Model request p95 | <= 4000 ms |
| API validation failures | <= 250 ms and no vision call |
| Batch first item result | <= 5000 ms under configured concurrency |

Brief checklist coverage:

| Checklist item | Coverage |
| --- | --- |
| Valid label | `test_verify_success_returns_full_verification_result_and_calls_mock` |
| Mismatches | `test_verify_mismatched_extracted_field_returns_needs_review` |
| Case-only | `test_verify_case_only_application_difference_is_approved` |
| ABV / units normalization | `test_abv_percent_matches_plain_number`, `test_liters_convert_to_milliliters`, `test_fluid_ounces_convert_within_one_ml` |
| Missing warning | `test_incomplete_government_warning_can_return_none`, `test_verify_imperfect_readable_image_returns_needs_review_with_null_fields` |
| Wrong-caps warning | `test_government_warning_case_difference_fails` |
| Correct warning | `test_correct_all_caps_government_warning_passes` |
| Imperfect image | `test_partial_blurry_response_returns_partial_label`, `test_verify_imperfect_readable_image_returns_needs_review_with_null_fields` |
| Wrong file type | `test_verify_unsupported_content_type_returns_415` |
| Empty submit | `test_verify_missing_image_returns_readable_422_error`, `test_verify_missing_required_application_field_returns_422` |
| Batch summary | `test_verify_batch_success_returns_summary_and_item_results`, `test_verify_batch_mixed_approved_and_needs_review_counts_correctly` |
| Single-label speed | `test_verify_logs_latency_and_five_second_budget`, `benchmark_phase6.py` targets |

## Deploy

Backend on Render:

1. Push this repo to GitHub.
2. In Render, create a new Blueprint from the repo, or create a Web Service manually.
3. Use these settings if creating manually:
   - Root directory: `backend`
   - Build command: `pip install -r requirements.txt`
   - Start command: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
   - Health check path: `/health`
   - Plan: Free
4. Add environment variables in Render:
   - `APP_ENV=production`
   - `ALLOWED_ORIGINS=http://localhost:5173` for local frontend testing
   - `GEMINI_API_KEY=<your Gemini API key>`
   - `GEMINI_MODEL=gemini-3.5-flash`

Frontend on Vercel:

```bash
cd frontend
printf 'window.APP_CONFIG = { API_BASE_URL: "https://YOUR-RENDER-SERVICE.onrender.com" };\n' > config.js
npx vercel --prod
```

After Vercel gives you the production URL, update Render's `ALLOWED_ORIGINS` to
that exact URL and redeploy/restart the backend.

## Exit Check

1. Open `http://localhost:5173`.
2. Choose a JPG, PNG, or WebP label image.
3. Fill in all seven expected application fields.
4. Press `Verify Label`.
5. Confirm the page shows `APPROVED` or `NEEDS REVIEW` plus one PASS/FAIL row
   per field.

Render Free services spin down after idle time, so the first request after idle
can be slow. Warm the backend URL before demos.
