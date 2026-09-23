"""Load the source CSVs and apply the data-handling policy.

Every row that is corrected or excluded is recorded in `Book.issues`,
so the data-quality report can say exactly what happened to the source data.
"""

from dataclasses import dataclass
from pathlib import Path

import pandas as pd


@dataclass
class Book:
    policies: pd.DataFrame  # valid policies, with portfolio_id and premium_dkk
    claims: pd.DataFrame  # valid claims, with policy fields and incurred_dkk
    issues: list[dict]  # what was corrected or excluded, and how many rows


def load_book(data_dir: str | Path) -> Book:
    data_dir = Path(data_dir)
    assets = pd.read_csv(data_dir / "assets.csv")
    policies = pd.read_csv(data_dir / "policies.csv")
    claims = pd.read_csv(data_dir / "claims.csv")
    fx = pd.read_csv(data_dir / "fx_rates.csv")
    return build_book(assets, policies, claims, fx)


def build_book(assets, policies, claims, fx) -> Book:
    issues = []
    fx = fx.astype({"rate_dkk_per_unit": float})
    policies = clean_policies(policies, assets, fx, issues)
    claims = clean_claims(claims, policies, fx, issues)
    return Book(policies=policies, claims=claims, issues=issues)


def clean_policies(policies, assets, fx, issues) -> pd.DataFrame:
    policies = policies.copy()

    # 1. Peril names come with mixed case and stray spaces ("FIRE", " fire").
    normalised = policies["peril"].str.strip().str.lower()
    changed = normalised != policies["peril"]
    add_issue(issues, "policies", "peril with inconsistent case or spaces", "normalised", changed.sum())
    policies["peril"] = normalised

    # 2. Types.
    policies["inception_date"] = pd.to_datetime(policies["inception_date"], format="%Y-%m-%d")
    policies["expiry_date"] = pd.to_datetime(policies["expiry_date"], format="%Y-%m-%d")
    policies["annual_premium"] = policies["annual_premium"].astype(float)
    policies["underwriting_year"] = policies["inception_date"].dt.year

    # 3. Portfolio, region and asset type come from the asset.
    asset_columns = assets[["asset_id", "portfolio_id", "region", "asset_type"]]
    policies = policies.merge(asset_columns, on="asset_id", how="left", validate="many_to_one")
    if policies["portfolio_id"].isna().any():
        raise ValueError("Some policies reference an asset_id that is not in assets")

    # 4. Premium in DKK, at the rate of the inception month.
    policies = add_dkk_rate(policies, "inception_date", fx)
    policies["premium_dkk"] = policies["annual_premium"] * policies["rate_dkk_per_unit"]

    return policies


def clean_claims(claims, policies, fx, issues) -> pd.DataFrame:
    claims = claims.copy()

    # 1. Some dates are DD-MM-YYYY instead of ISO; parse both.
    claims["loss_date"], loss_day_first = parse_dates(claims["loss_date"])
    claims["reported_date"], reported_day_first = parse_dates(claims["reported_date"])
    day_first = loss_day_first | reported_day_first
    add_issue(issues, "claims", "date in DD-MM-YYYY format", "parsed as day-first", day_first.sum())

    # 2. Incurred loss, by status. Withdrawn and declined claims cost nothing.
    claims["paid_amount"] = claims["paid_amount"].astype(float)
    claims["reserve_amount"] = claims["reserve_amount"].astype(float)
    settled = claims["status"] == "settled"
    is_open = claims["status"] == "open"
    claims["incurred"] = 0.0
    claims.loc[settled, "incurred"] = claims["paid_amount"]
    claims.loc[is_open, "incurred"] = claims["paid_amount"] + claims["reserve_amount"]

    settled_with_reserve = settled & (claims["reserve_amount"] > 0)
    add_issue(issues, "claims", "settled claim still has a reserve",
              "reserve ignored (settled = paid only)", settled_with_reserve.sum())

    # 3. Incurred in DKK, in the claim's own currency, at the rate of the loss month.
    claims = add_dkk_rate(claims, "loss_date", fx)
    claims["incurred_dkk"] = claims["incurred"] * claims["rate_dkk_per_unit"]

    # 4. Negative paid amounts: probably a sign error, but not ours to fix. Exclude.
    negative = claims["paid_amount"] < 0
    add_issue(issues, "claims", "negative paid_amount", "excluded (to confirm with data provider)",
              negative.sum(), claims.loc[negative, "incurred_dkk"].abs().sum())
    claims = claims[~negative]

    # 5. Claims whose policy does not exist cannot be attributed to a portfolio.
    orphan = ~claims["policy_id"].isin(policies["policy_id"])
    add_issue(issues, "claims", "policy_id not in policies", "excluded",
              orphan.sum(), claims.loc[orphan, "incurred_dkk"].sum())
    claims = claims[~orphan]

    # 6. Attach policy fields (one policy per claim).
    policy_columns = policies[["policy_id", "portfolio_id", "peril", "region", "asset_type",
                               "underwriting_year", "inception_date", "expiry_date"]]
    claims = claims.merge(policy_columns, on="policy_id", how="inner", validate="many_to_one")

    # 7. A policy cannot cover a loss outside its term.
    outside = (claims["loss_date"] < claims["inception_date"]) | (claims["loss_date"] > claims["expiry_date"])
    add_issue(issues, "claims", "loss date outside the policy term", "excluded",
              outside.sum(), claims.loc[outside, "incurred_dkk"].sum())
    claims = claims[~outside]

    return claims.reset_index(drop=True)


def parse_dates(values: pd.Series) -> tuple[pd.Series, pd.Series]:
    """Parse ISO dates, falling back to DD-MM-YYYY. Returns (dates, was_day_first)."""
    iso = pd.to_datetime(values, format="%Y-%m-%d", errors="coerce")
    day_first = pd.to_datetime(values, format="%d-%m-%Y", errors="coerce")
    dates = iso.fillna(day_first)
    if dates.isna().any():
        raise ValueError(f"Unparseable dates: {values[dates.isna()].tolist()[:5]}")
    return dates, iso.isna()


def add_dkk_rate(df: pd.DataFrame, date_column: str, fx: pd.DataFrame) -> pd.DataFrame:
    """Add `rate_dkk_per_unit` for each row's currency and the month of `date_column`."""
    df = df.copy()
    df["month"] = df[date_column].dt.strftime("%Y-%m")
    df = df.merge(fx, on=["month", "currency"], how="left")
    if df["rate_dkk_per_unit"].isna().any():
        raise ValueError(f"Missing FX rate for some rows (by {date_column})")
    return df


def add_issue(issues, table, problem, action, rows, amount_dkk=None) -> None:
    if rows == 0:
        return
    issue = {"table": table, "problem": problem, "action": action, "rows": int(rows)}
    if amount_dkk is not None:
        issue["amount_dkk"] = round(float(amount_dkk), 2)
    issues.append(issue)
