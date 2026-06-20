# TTB Label Verification

Phase 0 scaffold for the TTB Label Verification proof-of-concept.

## Local Setup

Backend:

```bash
cd backend
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export APP_ENV=local
export ALLOWED_ORIGINS=http://localhost:5173
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Frontend, in a second terminal:

```bash
cd frontend
python3 -m http.server 5173
```

Open `http://localhost:5173`. The page should show the JSON response from
`http://localhost:8000/health`.

Run backend tests:

```bash
cd backend
source .venv/bin/activate
PYTHONPATH=. pytest
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
   - `ALLOWED_ORIGINS=https://YOUR-VERCEL-APP.vercel.app`
   - `VISION_MODEL_API_KEY=<real key later>`

Frontend on Vercel:

```bash
cd frontend
printf 'window.APP_CONFIG = { API_BASE_URL: "https://YOUR-RENDER-SERVICE.onrender.com" };\n' > config.js
npx vercel --prod
```

After Vercel gives you the production URL, update Render's `ALLOWED_ORIGINS` to
that exact URL and redeploy/restart the backend.

## Exit Check

1. Open `https://YOUR-RENDER-SERVICE.onrender.com/health`.
2. Confirm it returns JSON with `"status": "ok"`.
3. Open the Vercel frontend URL.
4. Confirm the page says `API health response received` and displays the same
   health JSON.

Render Free services spin down after idle time, so the first request after idle
can be slow. Warm the backend URL before demos.
