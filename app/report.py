"""Loss-experience aggregation over a cleaned Book."""

import pandas as pd

from app.data import Book


def filter_book(book: Book, underwriting_year=None, region=None, asset_type=None) -> Book:
    """Keep only policies (and their claims) matching the given filters; None means no filter."""
    policies, claims = book.policies, book.claims
    for column, value in [("underwriting_year", underwriting_year), ("region", region), ("asset_type", asset_type)]:
        if value is not None:
            policies = policies[policies[column] == value]
            claims = claims[claims[column] == value]
    return Book(policies=policies, claims=claims, issues=book.issues)


def loss_experience(book: Book, portfolio_id: str) -> dict | None:
    policies = book.policies[book.policies["portfolio_id"] == portfolio_id]
    if policies.empty:
        return None
    claims = book.claims[book.claims["portfolio_id"] == portfolio_id]

    perils = [
        {"peril": peril} | _summarise(policies[policies["peril"] == peril], claims[claims["peril"] == peril])
        for peril in sorted(policies["peril"].unique())
    ]
    return {
        "portfolio_id": portfolio_id,
        "currency": "DKK",
        "perils": perils,
        "total": _summarise(policies, claims),
    }


def compare_portfolios(book: Book) -> list[dict]:
    rows = []
    for portfolio_id in book.policies["portfolio_id"].unique():
        total = loss_experience(book, portfolio_id)["total"]
        rows.append({"portfolio_id": portfolio_id} | total)
    # Worst first: loss ratio is comparable across portfolios of similar size.
    return sorted(rows, key=lambda row: row["loss_ratio"], reverse=True)


def _summarise(policies: pd.DataFrame, claims: pd.DataFrame) -> dict:
    premium = float(policies["premium_dkk"].sum())
    incurred = float(claims["incurred_dkk"].sum())
    # Withdrawn and declined claims cost nothing, so they are not counted as claims.
    counted = claims[claims["status"].isin(["settled", "open"])]
    return {
        "policy_count": int(policies["policy_id"].nunique()),
        "earned_premium": round(premium, 2),
        "incurred_loss": round(incurred, 2),
        "loss_ratio": round(incurred / premium, 4) if premium else None,
        "claim_count": len(counted),
        "largest_claim": round(float(claims["incurred_dkk"].max()), 2) if len(claims) else 0.0,
    }
