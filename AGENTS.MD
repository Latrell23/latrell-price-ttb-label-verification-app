You are helping build the TTB Label Reviewer proof of concept.

Standing rules for the whole project:

1. Stack: Python 3.12 + FastAPI backend, plain HTML/CSS/JavaScript frontend,
   OpenAI vision extraction, and no production database yet.
2. Product scope: review backend-provided application JSON and label images.
   Do not add image uploads, manual application forms, or multipart verification
   endpoints.
3. Reviewer flow: load the simulated queue, run AI review for one record or the
   full queue, inspect field comparisons, then Accept or Flag and submit the
   session-only decision.
4. Government warning comparison uses the documented exact-match rule. Other
   fields use their documented fuzzy or normalized rules.
5. API keys live in environment variables only—never hardcoded or committed.
6. The UI must be usable by a non-technical older adult without instructions.
7. Keep the review API and UI accessible, reliable, and responsive. Queue-wide
   review concurrency must remain bounded and configurable.
8. Working cadence: PLAN proposes an approach without code; REVIEW critiques and
   finalizes it; EXECUTE implements the approved plan with tests and verification.
9. Prefer correctness and clean structure over ambition. Keep scope to the
   current phase.
