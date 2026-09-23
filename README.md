# Envira loss-experience service

A small FastAPI service that reports loss experience (premium, incurred loss,
loss ratio) per portfolio and peril, in DKK.

## Setup

Requires Python 3.13.

Unzip the provided data so the CSV files sit in `./data`:

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

## Test

```bash
pytest
```

## Endpoints

| method | path | what |
|---|---|---|
| GET | `/portfolios/{portfolio_id}/loss-experience` | per peril and in total: policy count, earned premium, incurred loss, loss ratio, claim count, largest single claim (DKK) |
| GET | `/health` | liveness |

Example: `curl http://localhost:8000/portfolios/PF-03/loss-experience`

## Data handling policy

Applied once at startup in `app/data.py`; every row corrected or excluded is
counted.

| issue in source data | rows | handling |
|---|---:|---|
| peril with mixed case / stray whitespace (`FIRE`, `" fire"`) | 1,321 policies | normalised to lower case |
| claim dates in `DD-MM-YYYY` instead of ISO | 1,072 claims | parsed as day-first (month-first fails to parse 654 and puts reports before losses) |
| negative `paid_amount`, all on settled claims | 262 claims | treated as sign error, absolute value used |
| settled claims that still carry a reserve | 721 claims | reserve ignored: settled incurred = paid |
| claim `policy_id` not in `policies.csv` | 260 claims, 11.7M DKK | excluded: cannot be attributed to a portfolio |
| loss date before the policy's inception | 310 claims, 5.3M DKK | excluded: the policy did not cover that date (almost all were also reported before inception) |

Currency: premiums are converted at the month-end rate of the inception month,
claims at the rate of the loss month, each in its own currency (a policy's
claims are not always in the policy's currency).

Definitions: incurred = paid for settled, paid + reserve for open, 0 for
withdrawn/declined. Claim count includes open and settled claims only.

## Verification

```bash
python scripts/check_totals.py
```

Recomputes per-portfolio premium and incurred loss from the raw CSVs with the
standard library only and compares them with the service output.
