# CLAUDE.md

Loss-experience service for the Envira practical test.

- Stack: Python 3.13, FastAPI, pandas, pytest; dependencies in `requirements*.txt`.
- Run: `uvicorn app.main:app --port 8000`. Test: `pytest`.
- Source CSVs live in `./data` (git-ignored, never commit them).
- All money is reported in DKK. Every excluded or corrected row must be
  counted and surfaced in the data-quality report — never drop rows silently.
- Keep the implementation small: no database, cache or extra layers unless asked.
