# Envira loss-experience service

A small FastAPI service that reports loss experience (premium, incurred loss,
loss ratio) per portfolio and peril, in DKK.

## Setup

Requires Python 3.13.

The service reads the provided CSV files from `./data` in the repository root.
The archive unpacks to `envira-loss-data/data/`: move that `data` folder to the
repository root, so that you have:

```
data/
  assets.csv
  claims.csv
  fx_rates.csv
  policies.csv
```

A different location can be set with the `DATA_DIR` environment variable.

Install dependencies in a virtual environment:

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
```

(`requirements.txt` alone is enough to run the service; `requirements-dev.txt`
adds the test tools.)

## Run

```bash
uvicorn app.main:app --port 8000
```

Then open http://localhost:8000/docs.

## Run with Docker

With the data in `./data` (mounted read-only into the container):

```bash
docker compose up --build
```

The service listens on http://localhost:8000.

## Test

```bash
pytest
```

## Endpoints

| method | path | what |
|---|---|---|
| GET | `/portfolios/{portfolio_id}/loss-experience` | per peril and in total: policy count, earned premium, incurred loss, loss ratio, claim count, largest single claim (DKK) |
| GET | `/portfolios/loss-experience` | all portfolios with the same totals, ordered by loss ratio (worst first) |
| GET | `/data-quality` | rows kept, and every correction or exclusion applied to the source data (rows, amount in DKK) |
| GET | `/health` | liveness |

Example: `curl http://localhost:8000/portfolios/PF-03/loss-experience`

Both portfolio endpoints accept optional filters, combinable:
`underwriting_year` (e.g. `2023`), `region` (e.g. `Hovedstaden`) and
`asset_type` (e.g. `residential`); values match the source data exactly.
Example: `/portfolios/loss-experience?underwriting_year=2024&region=Sjaelland`

## Data handling policy

Applied once at startup in `app/data.py`, in the order below; every row corrected
or excluded is counted once, under the first rule that excludes it.

| issue in source data | rows | handling |
|---|---:|---|
| peril with mixed case / stray whitespace (`FIRE`, `" fire"`) | 1,321 policies | normalised to lower case |
| claim dates in `DD-MM-YYYY` instead of ISO | 1,072 claims | parsed as day-first (month-first fails to parse 654 and puts reports before losses) |
| negative `paid_amount`, all on settled claims | 262 claims, 4.1M DKK (absolute) | excluded; likely a sign error, but that is for the data provider to confirm |
| settled claims that still carry a reserve | 721 claims | reserve ignored: settled incurred = paid |
| claim `policy_id` not in `policies.csv` | 260 claims, 11.7M DKK | excluded: cannot be attributed to a portfolio |
| loss date before the policy's inception | 293 claims, 4.8M DKK | excluded: the policy did not cover that date (almost all were also reported before inception) |

Currency: premiums are converted at the month-end rate of the inception month,
claims at the rate of the loss month, each in its own currency (a policy's
claims are not always in the policy's currency).

Definitions: incurred = paid for settled, paid + reserve for open, 0 for
withdrawn/declined. Claim count includes open and settled claims only.

## Verification

```bash
python scripts/check_totals.py
```

Recomputes every figure of the core endpoint (per portfolio and peril), unfiltered
and for each filter value, from the raw CSVs with the standard library only, and
compares it with the service output.

## What the numbers say

No portfolio loses money on claims overall (highest loss ratio: PF-03, 0.91),
but fire does: its loss ratio is above 1 in 11 of 12 portfolios (1.58 across
the book, 3.15 in PF-03). Subsidence is above 1 in 3 portfolios. Loss ratios
exclude expenses, so a ratio near 1 is already unprofitable.
