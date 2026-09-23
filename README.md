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
