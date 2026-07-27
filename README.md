# TTB Label Reviewer

Review-focused proof of concept for comparing backend-provided TTB alcohol
application data with the visible text on its corresponding label image.

The backend currently simulates a database with five JSON/image fixtures. A
reviewer can run AI verification for one record or the full queue, inspect
field-level results, choose Accept or Flag, and submit that decision for the
current browser session.

Repository: https://github.com/Latrell23/latrell-price-ttb-label-verification-app

## Live Demo

- Frontend: https://ttb-label-frontend.vercel.app/
- Backend health: https://latrell-price-ttb-label-verification-app.onrender.com/health
- Backend API base: https://latrell-price-ttb-label-verification-app.onrender.com

Render free-tier services can spin down after idle time, so the first request
may be slower than later requests.

## Architecture

- Static HTML/CSS and native browser JavaScript modules.
- Python 3.12, FastAPI, Pydantic, Pillow, RapidFuzz, and the OpenAI Responses API.
- Backend-owned review JSON and JPEG fixtures under `backend/app/review/fixtures`.
- Deterministic field comparison after AI vision extraction.
- No upload endpoints, manual application form, or database.
- Reviewer decisions are session-only and are not persisted by the backend.

The backend exposes only:

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/health` | Service and vision-configuration readiness |
| `GET` | `/review/labels` | Load the simulated review queue |
| `GET` | `/review/assets/{image}` | Serve fixture label images |
| `POST` | `/review/labels/{label_id}/verify` | Run AI review for one record |
| `POST` | `/review/verify` | Run AI review for the full queue |

## Local Setup

Create and start the backend:

```bash
cd backend
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

In another terminal, serve the frontend:

```bash
cd frontend
python3 -m http.server 5173
```

Open `http://localhost:5173`.

Configure `frontend/config.js` for local development:

```js
window.APP_CONFIG = {
  API_BASE_URL: "http://localhost:8000",
  REVIEW_TIMEOUT_MS: 45000,
};
```

Backend environment variables:

| Variable | Required | Default | Purpose |
| --- | --- | --- | --- |
| `APP_ENV` | No | `local` | Selects local or production CORS defaults |
| `ALLOWED_ORIGINS` | Production | none | Comma-separated browser origins |
| `OPENAI_API_KEY` | Real AI review | none | OpenAI API credential |
| `OPENAI_MODEL` | Real AI review | none | Vision-capable model selected by the deployer |
| `OPENAI_REASONING_EFFORT` | No | none | Optional supported reasoning effort |
| `MAX_REVIEW_CONCURRENCY` | No | `3` | Maximum simultaneous queue review calls |
| `REVIEW_TIMEOUT_SECONDS` | No | `20` | Per-record backend AI time budget |

Keep API keys in environment variables only. Never put credentials in
`frontend/config.js` or commit them to the repository.

## API Examples

Load the queue:

```bash
curl -sS http://localhost:8000/review/labels
```

Review one record:

```bash
curl -sS -X POST http://localhost:8000/review/labels/label-001/verify \
  -H 'Accept: application/json'
```

Review the full queue:

```bash
curl -sS -X POST http://localhost:8000/review/verify \
  -H 'Accept: application/json'
```

A completed item contains the fixture ID, image file name, status, and a
verification result. Failed queue items use the same stable error object without
preventing other records from completing.

## Comparison Rules

| Field | Strategy |
| --- | --- |
| `brand_name` | Normalized fuzzy text; threshold 90 |
| `class_type` | Normalized fuzzy text; threshold 90 |
| `producer` | Normalized fuzzy text; threshold 90 |
| `abv` | Numeric comparison within ±0.1 |
| `net_contents` | Unit-normalized comparison within ±1 mL |
| `country_of_origin` | Punctuation normalization and country synonyms |
| `government_warning` | Exact, case-insensitive comparison after whitespace normalization |

The overall verdict is `APPROVED` only when every field passes. Otherwise it is
`NEEDS_REVIEW`; the human reviewer still makes the final Accept or Flag decision.

## Verification

Run the backend suite:

```bash
backend/.venv/bin/pytest -q
```

Check frontend modules:

```bash
node --check frontend/js/app.js
node --check frontend/js/api.js
node --check frontend/js/constants.js
node --check frontend/js/rendering.js
node --check frontend/js/review.js
```

Run the deployed review-only smoke checklist:

```bash
backend/.venv/bin/python scripts/live_checklist.py \
  --base-url http://localhost:8000
```

The direct vision utilities in `backend/scripts` remain available for provider
and preprocessing development; they do not expose upload APIs.
