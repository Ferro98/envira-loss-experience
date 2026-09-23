import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException

from app.data import load_book
from app.report import loss_experience


@asynccontextmanager
async def lifespan(app: FastAPI):
    # The files are small: load and clean them once at startup, not per request.
    app.state.book = load_book(os.environ.get("DATA_DIR", "data"))
    yield


app = FastAPI(title="Envira loss-experience service", lifespan=lifespan)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/portfolios/{portfolio_id}/loss-experience")
def portfolio_loss_experience(portfolio_id: str) -> dict:
    result = loss_experience(app.state.book, portfolio_id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Portfolio {portfolio_id} not found")
    return result
