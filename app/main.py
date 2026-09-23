import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException

from app.data import load_book
from app.report import compare_portfolios, filter_book, loss_experience


@asynccontextmanager
async def lifespan(app: FastAPI):
    # The files are small: load and clean them once at startup, not per request.
    app.state.book = load_book(os.environ.get("DATA_DIR", "data"))
    yield


app = FastAPI(title="Envira loss-experience service", lifespan=lifespan)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/data-quality")
def data_quality() -> dict:
    book = app.state.book
    return {"policies_kept": len(book.policies), "claims_kept": len(book.claims), "issues": book.issues}


@app.get("/portfolios/loss-experience")
def portfolios_loss_experience(
    underwriting_year: int | None = None, region: str | None = None, asset_type: str | None = None
) -> dict:
    book = filter_book(app.state.book, underwriting_year, region, asset_type)
    return {"currency": "DKK", "ordered_by": "loss_ratio desc", "portfolios": compare_portfolios(book)}


@app.get("/portfolios/{portfolio_id}/loss-experience")
def portfolio_loss_experience(
    portfolio_id: str, underwriting_year: int | None = None, region: str | None = None, asset_type: str | None = None
) -> dict:
    book = filter_book(app.state.book, underwriting_year, region, asset_type)
    result = loss_experience(book, portfolio_id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"No policies for portfolio {portfolio_id} with these filters")
    return result
