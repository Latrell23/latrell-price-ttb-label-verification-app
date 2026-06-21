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
