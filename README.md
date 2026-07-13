# TTB Label Verification

Proof-of-concept final submission build for comparing TTB alcohol label image
fields against expected application fields. The app extracts label text from an
uploaded image, normalizes comparable values, and returns field-level
`PASS`/`FAIL` results with an overall `APPROVED` or `NEEDS REVIEW` status.

Repository: https://github.com/AI-Native-2026-06-22-FedStack/latrell-price-ttb-label-verification-app

## Live Demo

- Frontend: https://ttb-label-frontend.vercel.app/
- Backend health: https://latrell-price-ttb-label-verification-app.onrender.com/health
- Backend API base: https://latrell-price-ttb-label-verification-app.onrender.com

Render free-tier services can spin down after idle time, so the first request
after idle may be slower than warm requests.

## Features

- Single-label verification for JPG, PNG, and WebP uploads.
- Batch verification with item-level results and an aggregate summary.
- Field-level `PASS`/`FAIL` comparisons for expected application fields.
- Strict government warning comparison, including capitalization.
- Fuzzy text matching for label text fields.
- Numeric ABV and volume/unit normalization.
- Country synonym handling.
- Image validation and readable error states for empty submits, unsupported
  file types, and malformed requests.

## Approach / AI Workflow

- Built with Codex as the implementation partner using the project cadence in
  `AGENTS.MD`: plan the phase, review against requirements and edge cases, then
  execute with tests and verification commands.
- AI-assisted work covered backend routes, comparison logic, vision-provider
  integration, frontend modules, tests, docs, and deployment configuration.
- Human direction set the product requirements, tradeoffs, provider choice,
  review feedback, deployed URLs, and acceptance priorities.
- Review loops focused on demonstrable requirements, especially latency,
  batch behavior, environment-secret handling, and reviewer-run commands.

## Runtime Architecture

- Frontend: static HTML/CSS with native browser JavaScript modules.
- Backend: FastAPI verification API with `/health`, `/verify`, and
  `/verify/batch` routes.
- Vision extraction: Gemini Flash through the Google AI API free-tier workflow
  by default. Default model: `gemini-3.5-flash` (verified against Google's
  current Gemini model list on 2026-07-12; Google docs last updated
  2026-07-09).
- Verification engine: deterministic comparison logic after vision extraction,
  including fuzzy text matching, numeric ABV comparison, unit conversion,
  country synonyms, and exact government warning comparison.

## Tools And Services

- Python 3.12.8
- FastAPI, Uvicorn, Pytest, HTTPX
- Pillow, RapidFuzz
- Google GenAI / Gemini API
- Native browser JavaScript modules
- Render for backend deployment
- Vercel
## Local Setup

Create a backend environment:

```bash
cd backend
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Set local environment variables. Use `.env.example` as the reference; keep real
values in your shell, local untracked `.env`, or deployment provider settings.

| Variable | Required | Default | Purpose |
| --- | --- | --- | --- |
| `APP_ENV` | No | `local` | Identifies local vs production behavior; production disables default local CORS origins. |
| `ALLOWED_ORIGINS` | Yes in production | none in production; `http://localhost:5173` locally | Comma-separated browser origins allowed by backend CORS. |
| `GEMINI_API_KEY` | Yes for real vision | none | Primary Google GenAI credential for Gemini extraction. |
| `GOOGLE_API_KEY` | No | none | Alternate Google GenAI credential name accepted by the backend. |
| `GEMINI_MODEL` | No | `gemini-3.5-flash` | Gemini model used for extraction; verified against Google's model list on 2026-07-12. |
| `MAX_BATCH_ITEMS` | No | `5` | Backend per-request batch item cap, enforced before image bytes are read. |
| `MAX_BATCH_CONCURRENCY` | No | `3` | Maximum concurrent vision extractions inside one batch request. |
| `API_BASE_URL` | Frontend config only | `http://localhost:8000` | Backend base URL used by `frontend/config.js` / `window.APP_CONFIG`. |
| `MAX_BATCH_ROWS` | Frontend config only | `5` | Frontend row cap kept aligned with backend `MAX_BATCH_ITEMS`. |

Example local backend env:

```bash
export APP_ENV=local
export ALLOWED_ORIGINS=http://localhost:5173
export GEMINI_API_KEY=<your Gemini API key>
export GEMINI_MODEL=gemini-3.5-flash
export MAX_BATCH_ITEMS=5
export MAX_BATCH_CONCURRENCY=3
```

Start the backend:

```bash
cd backend
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Start the frontend in a second terminal:

```bash
cd frontend
python3 -m http.server 5173
```

Open `http://localhost:5173`. The frontend reads its backend URL from
`frontend/config.js`. For local development against a local backend, set:

```js
window.APP_CONFIG = {
  API_BASE_URL: "http://localhost:8000",
  MAX_BATCH_ROWS: 5,
};
```

For local development against the deployed Render backend, set:

```js
window.APP_CONFIG = {
  API_BASE_URL: "https://latrell-price-ttb-label-verification-app.onrender.com",
  MAX_BATCH_ROWS: 5,
};
```

## API Examples

Generate a sample JPEG label for the `curl` examples:

```bash
backend/.venv/bin/python backend/scripts/run_vision_sample.py --mock >/dev/null
```

Single-label verification:

```bash
curl -sS -X POST http://localhost:8000/verify \
  -H 'Accept: application/json' \
  -F image=@/tmp/ttb_sample_label.jpg\;type=image/jpeg \
  -F brand_name='Acme Estate' \
  -F class_type='Red Wine' \
  -F abv='13.5%' \
  -F net_contents='750 mL' \
  -F producer='Acme Cellars' \
  -F country_of_origin='United States' \
  -F government_warning='GOVERNMENT WARNING: (1) ACCORDING TO THE SURGEON GENERAL, WOMEN SHOULD NOT DRINK ALCOHOLIC BEVERAGES DURING PREGNANCY BECAUSE OF THE RISK OF BIRTH DEFECTS. (2) CONSUMPTION OF ALCOHOLIC BEVERAGES IMPAIRS YOUR ABILITY TO DRIVE A CAR OR OPERATE MACHINERY, AND MAY CAUSE HEALTH PROBLEMS.'
```

Batch verification:

```bash
curl -sS -X POST http://localhost:8000/verify/batch \
  -H 'Accept: application/json' \
  -F image_0=@/tmp/ttb_sample_label.jpg\;type=image/jpeg \
  -F 'items=[{"client_id":"label-0","image_field":"image_0","brand_name":"Acme Estate","class_type":"Red Wine","abv":"13.5%","net_contents":"750 mL","producer":"Acme Cellars","country_of_origin":"United States","government_warning":"GOVERNMENT WARNING: (1) ACCORDING TO THE SURGEON GENERAL, WOMEN SHOULD NOT DRINK ALCOHOLIC BEVERAGES DURING PREGNANCY BECAUSE OF THE RISK OF BIRTH DEFECTS. (2) CONSUMPTION OF ALCOHOLIC BEVERAGES IMPAIRS YOUR ABILITY TO DRIVE A CAR OR OPERATE MACHINERY, AND MAY CAUSE HEALTH PROBLEMS."}]'
```

Success shape:

```json
{
  "results": [
    {
      "field": "brand_name",
      "match_type": "FUZZY",
      "expected": "Acme Estate",
      "found": "ACME ESTATE",
      "status": "PASS"
    }
  ],
  "overall_verdict": "APPROVED",
  "latency_ms": 842.1
}
```

Error shape:

```json
{
  "error": {
    "code": "missing_image",
    "message": "The image file field is required.",
    "details": [
      {
        "field": "image",
        "message": "Upload one label image."
      }
    ]
  }
}
```

## Comparison Rules

Comparison logic lives in `backend/app/verification/engine.py`.

| Field | Strategy |
| --- | --- |
| `brand_name` | Fuzzy text match after whitespace collapse and case-folding; threshold `90`. |
| `class_type` | Fuzzy text match after whitespace collapse and case-folding; threshold `90`. |
| `producer` | Fuzzy text match after whitespace collapse and case-folding; threshold `90`. |
| `abv` | Numeric ABV parse; pass when values differ by no more than `±0.1`. |
| `net_contents` | Unit-normalized milliliter comparison; supports mL, L, cL, and fluid ounces; tolerance `±1 mL`. |
| `country_of_origin` | Punctuation-insensitive country normalization plus synonym groups such as USA / United States. |
| `government_warning` | Exact, case-sensitive comparison after whitespace collapse. |

## Running Tests

Run all backend tests:

```bash
backend/.venv/bin/pytest
```

Run the comparison engine tests:

```bash
backend/.venv/bin/pytest backend/tests/test_verification.py
```

Show the strict case-sensitive government warning test:

```bash
backend/.venv/bin/pytest backend/tests/test_verification.py -k government_warning_title_case_fails_strict_case_sensitive_comparison -vv
```

Run the vision sample script with mock extraction data:

```bash
backend/.venv/bin/python backend/scripts/run_vision_sample.py --mock
```

Call the real Gemini vision service:

```bash
export GEMINI_API_KEY=<your Gemini API key>
backend/.venv/bin/python backend/scripts/run_vision_sample.py
```

Pass an existing image:

```bash
backend/.venv/bin/python backend/scripts/run_vision_sample.py /path/to/label.jpg
```

Run the repeatable benchmark with the deterministic fake provider:

```bash
backend/.venv/bin/python backend/scripts/benchmark_phase6.py --mock --runs 3 --jsonl /tmp/ttb-phase6.jsonl
```

## Performance

Run the benchmark against Gemini free-tier credentials:

```bash
export GEMINI_API_KEY=<your Gemini API key>
backend/.venv/bin/python backend/scripts/benchmark_phase6.py --runs 30 --jsonl /tmp/ttb-phase6-gemini.jsonl
```

Tune image settings without changing application code:

```bash
backend/.venv/bin/python backend/scripts/benchmark_phase6.py --runs 30 --max-edge 1600 --jpeg-quality 78 --jsonl /tmp/ttb-phase6-1600-q78.jsonl
```

Benchmark targets are for warm backend requests and exclude Render free-plan
cold starts.

| Measurement | Target |
| --- | --- |
| Single-label p50 | <= 3000 ms |
| Single-label p95 | <= 4500 ms |
| Single-label max | <= 5000 ms |
| Preprocessing p95 | <= 350 ms |
| Model request p95 | <= 4000 ms |
| API validation failures | <= 250 ms and no vision call |
| Batch first item result | <= 5000 ms under configured concurrency |

Measured deployed performance:

| Date | Command | Sample | p50 | p95 | Result |
| --- | --- | --- | --- | --- | --- |
| 2026-07-12 | `backend/scripts/live_smoke_check.py --base-url https://latrell-price-ttb-label-verification-app.onrender.com` | 1 generated JPEG label | Not available | Not available | Real provider timed out at the 4.5s app-layer budget; no successful deployed p50/p95 can be claimed from that run. |
| 2026-07-12 | `backend/scripts/benchmark_phase6.py --mock --runs 3` | deterministic fake provider | Not applicable | Not applicable | Backend/test harness passed; this validates API shape and comparison behavior, not live provider latency. |

Cold-start behavior: Render free-tier services may take longer than the 5s
warm-request target after idle spin-down. The latency SLA is evaluated on warm
requests; cold starts are documented as an accepted hosting limitation.

## Live Smoke Check

Run the deployed end-to-end smoke check:

```bash
backend/.venv/bin/python backend/scripts/live_smoke_check.py \
  --base-url https://latrell-price-ttb-label-verification-app.onrender.com
```

The script generates `/tmp/ttb_sample_label.jpg`, posts it to deployed
`/verify`, and exits non-zero unless the response is HTTP `200` with
`results`, `overall_verdict`, and `latency_ms`.

## Deployment

Backend on Render:

1. Push this repo to GitHub.
2. In Render, create a Blueprint from the repo, or create a Web Service
   manually.
3. Use these settings if creating manually:
   - Root directory: `backend`
   - Build command: `pip install -r requirements.txt`
   - Start command: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
   - Health check path: `/health`
   - Plan: Free
4. Add production environment variables in Render:
   - `APP_ENV=production`
   - `ALLOWED_ORIGINS=https://ttb-label-frontend.vercel.app`
   - `GEMINI_API_KEY=<provider secret>`
   - `GEMINI_MODEL=gemini-3.5-flash` (verified against Google's model list on
     2026-07-12)
   - `MAX_BATCH_ITEMS=5`

Frontend on Vercel or another static host:

1. Set `frontend/config.js` to the deployed backend base URL.
2. Deploy the `frontend` directory as a static site.
3. Confirm Render's `ALLOWED_ORIGINS` includes
   `https://ttb-label-frontend.vercel.app` and restart/redeploy the backend.

Example frontend config:

```js
window.APP_CONFIG = {
  API_BASE_URL: "https://latrell-price-ttb-label-verification-app.onrender.com",
  MAX_BATCH_ROWS: 5,
};
```

## Assumptions

- Warm backend requests are measured separately from Render cold starts.
- Real credentials are managed outside git in local shell variables, untracked
  local env files, or Render/Vercel environment settings.
- `.env.example` remains committed with placeholders only.
- Gemini Flash through the Google AI API free-tier workflow is the intended
  production vision path.
- The production frontend origin is `https://ttb-label-frontend.vercel.app`.

## Tradeoffs

| Tradeoff | Reason |
| --- | --- |
| Batch cap defaults to `5` | Keeps memory and concurrent provider calls bounded on free-tier hosting. |
| Backend timeout is enforced at the app layer | Gemini rejects manual SDK deadlines below 10s, but the app must return within the 4.5s budget. |
| Gemini is the only production provider | Simpler deployment and avoids unsafe cross-provider model defaults. |
| Static frontend config is committed | Vercel static hosting has no runtime server env; public backend URL and row cap are safe client config. |
| No authentication or persistence | The proof of concept focuses on demonstrable label verification behavior. |

## Limitations

- OCR/vision extraction can require human review for blurry, cropped, rotated,
  or low-contrast labels.
- Render free-tier cold starts can exceed warm-request latency targets.
- This is not an official TTB system.
- No authentication, persistent storage, or audit log is included.
- Verification quality depends on the uploaded image and the configured vision
  provider response.

## Verification Coverage

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

## Pre-Submission Audit

Run these commands before final submission:

```bash
git status --short
git ls-files
git check-ignore -v .env .env.local .env.production
git ls-files | rg '(^|/)\.env($|\.)'
git ls-files | rg '(^|/)\.env[^/]*$'
git log --all --name-only --pretty=format: | rg '(^|/)\.env($|\.)|(^|/)\.env[^/]*$'
rg -n --hidden --glob '!.git/**' --glob '!backend/.venv/**' --glob '!node_modules/**' '(api[_-]?key|secret|token|password|GEMINI_API_KEY|AIza)' .
git grep -n -I -E '(api[_-]?key|secret|token|password|GEMINI_API_KEY|AIza)' $(git rev-list --all) -- . ':!backend/.venv/**' ':!node_modules/**'
git diff --check
backend/.venv/bin/pytest
```

The `.env` audit intentionally prints `.env.example`; that should be the only
tracked `.env*` file. If the command prints `.env`, `.env.local`,
`.env.production`, or a nested path such as `backend/.env`, remove it from git
history before public submission. The current-tree and history secret scans
should only show placeholder documentation, config key names, test env names, or
provider-client code paths. They should not show real API keys, provider tokens,
passwords, or deployment secrets. If the history scan finds a real secret,
rotate the credential and rewrite/remove the affected public history before
final submission.

Also review:

- `render.yaml`
- `frontend/config.js`
- `frontend/config.example.js`
- `.env.example`

`frontend/config.js` may contain the public backend URL only.

## Final Submission Checklist

- Public GitHub repo is accessible:
  https://github.com/AI-Native-2026-06-22-FedStack/latrell-price-ttb-label-verification-app
- Final frontend URL is filled into this README:
  https://ttb-label-frontend.vercel.app/
- Backend health URL returns `status: ok`.
- Single-label happy path works against the deployed backend.
- Mismatch or needs-review path works against the deployed backend.
- Wrong file type and empty submit return readable errors.
- Batch verification returns item results and a summary.
- Render `ALLOWED_ORIGINS` includes `https://ttb-label-frontend.vercel.app`.
- Backend tests pass.
- `git diff --check` passes.
- Secret scan/audit is complete.
