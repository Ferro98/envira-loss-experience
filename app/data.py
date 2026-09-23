"""Load the source CSVs and apply the data-handling policy.

Every row that is excluded or corrected is counted in `Book.issues`, so the
data-quality report can say exactly what happened to the source data.
"""

from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

INCURRED_STATUSES = {"settled", "open"}
ZERO_COST_STATUSES = {"withdrawn", "declined"}


@dataclass
class Book:
    policies: pd.DataFrame  # one row per valid policy, with portfolio and premium_dkk
    claims: pd.DataFrame  # one row per valid claim, with policy fields and incurred_dkk
    issues: list[dict] = field(default_factory=list)


def load_book(data_dir: str | Path) -> Book:
    data_dir = Path(data_dir)
    read = lambda name: pd.read_csv(data_dir / f"{name}.csv", dtype=str)
    return build_book(read("assets"), read("policies"), read("claims"), read("fx_rates"))


def build_book(assets: pd.DataFrame, policies: pd.DataFrame, claims: pd.DataFrame, fx: pd.DataFrame) -> Book:
    issues: list[dict] = []

    def record(table: str, issue: str, action: str, mask: pd.Series, amount_dkk: float | None = None) -> None:
        count = int(mask.sum())
        if count:
            entry = {"table": table, "issue": issue, "action": action, "rows": count}
            if amount_dkk is not None:
                entry["amount_dkk"] = round(float(amount_dkk), 2)
            issues.append(entry)

    rates = _rate_lookup(fx)
    policies = _clean_policies(assets, policies, rates, record)
    claims = _clean_claims(claims, policies, rates, record)
    return Book(policies=policies, claims=claims, issues=issues)


def _rate_lookup(fx: pd.DataFrame) -> dict[tuple[str, str], float]:
    fx = fx.assign(rate=pd.to_numeric(fx["rate_dkk_per_unit"]))
    return {(m, c.strip().upper()): r for m, c, r in zip(fx["month"], fx["currency"], fx["rate"])}


def _to_dkk(amount: pd.Series, currency: pd.Series, date: pd.Series, rates: dict) -> pd.Series:
    """Convert at the month-end rate of the month the amount belongs to. NaN if no rate."""
    keys = zip(date.dt.strftime("%Y-%m"), currency)
    return amount * pd.Series([rates.get(k, float("nan")) for k in keys], index=amount.index)


def _parse_dates(values: pd.Series) -> tuple[pd.Series, pd.Series]:
    """Parse ISO dates, falling back to day-first DD-MM-YYYY. Returns (dates, was_day_first)."""
    iso = pd.to_datetime(values, format="%Y-%m-%d", errors="coerce")
    day_first = pd.to_datetime(values, format="%d-%m-%Y", errors="coerce")
    return iso.fillna(day_first), iso.isna() & day_first.notna()


def _clean_policies(assets, policies, rates, record) -> pd.DataFrame:
    p = policies.copy()

    raw_peril = p["peril"]
    p["peril"] = raw_peril.str.strip().str.lower()
    record("policies", "peril with inconsistent case or whitespace", "normalised", p["peril"] != raw_peril)
    p["currency"] = p["currency"].str.strip().str.upper()

    dup = p.duplicated("policy_id", keep="first")
    record("policies", "duplicate policy_id", "excluded (kept first)", dup)
    p = p[~dup]

    p["inception_date"], _ = _parse_dates(p["inception_date"])
    p["expiry_date"], _ = _parse_dates(p["expiry_date"])
    p["annual_premium"] = pd.to_numeric(p["annual_premium"], errors="coerce")
    bad = p["inception_date"].isna() | p["expiry_date"].isna() | p["annual_premium"].isna()
    record("policies", "unparseable date or premium", "excluded", bad)
    p = p[~bad]

    p = p.merge(assets[["asset_id", "portfolio_id", "region", "asset_type"]], on="asset_id", how="left")
    orphan = p["portfolio_id"].isna()
    record("policies", "asset_id not in assets", "excluded", orphan)
    p = p[~orphan]

    p["premium_dkk"] = _to_dkk(p["annual_premium"], p["currency"], p["inception_date"], rates)
    no_rate = p["premium_dkk"].isna()
    record("policies", "no FX rate for currency and inception month", "excluded", no_rate)
    p = p[~no_rate]

    p["underwriting_year"] = p["inception_date"].dt.year
    return p.reset_index(drop=True)


def _clean_claims(claims, policies, rates, record) -> pd.DataFrame:
    c = claims.copy()
    c["status"] = c["status"].str.strip().str.lower()
    c["currency"] = c["currency"].str.strip().str.upper()

    dup = c.duplicated("claim_id", keep="first")
    record("claims", "duplicate claim_id", "excluded (kept first)", dup)
    c = c[~dup]

    c["loss_date"], day_first = _parse_dates(c["loss_date"])
    c["reported_date"], day_first_rep = _parse_dates(c["reported_date"])
    record("claims", "date in DD-MM-YYYY instead of ISO format", "parsed as day-first", day_first | day_first_rep)
    c["paid_amount"] = pd.to_numeric(c["paid_amount"], errors="coerce")
    c["reserve_amount"] = pd.to_numeric(c["reserve_amount"], errors="coerce")
    bad = c["loss_date"].isna() | c["paid_amount"].isna() | c["reserve_amount"].isna()
    record("claims", "unparseable date or amount", "excluded", bad)
    c = c[~bad]

    unknown = ~c["status"].isin(INCURRED_STATUSES | ZERO_COST_STATUSES)
    record("claims", "unknown status", "excluded", unknown)
    c = c[~unknown]

    negative = c["paid_amount"] < 0
    record("claims", "negative paid_amount (treated as sign error)", "used absolute value", negative)
    c["paid_amount"] = c["paid_amount"].abs()

    settled_reserve = (c["status"] == "settled") & (c["reserve_amount"] > 0)
    record("claims", "settled claim with reserve left", "reserve ignored (settled = paid only)", settled_reserve)

    c["incurred"] = 0.0
    c.loc[c["status"] == "settled", "incurred"] = c["paid_amount"]
    c.loc[c["status"] == "open", "incurred"] = c["paid_amount"] + c["reserve_amount"]
    c["incurred_dkk"] = _to_dkk(c["incurred"], c["currency"], c["loss_date"], rates)
    no_rate = c["incurred_dkk"].isna()
    record("claims", "no FX rate for currency and loss month", "excluded", no_rate)
    c = c[~no_rate]

    policy_cols = ["policy_id", "portfolio_id", "peril", "region", "asset_type",
                   "underwriting_year", "inception_date", "expiry_date"]
    c = c.merge(policies[policy_cols], on="policy_id", how="left", validate="many_to_one")
    orphan = c["portfolio_id"].isna()
    record("claims", "policy_id not in (valid) policies", "excluded", orphan, c.loc[orphan, "incurred_dkk"].sum())
    c = c[~orphan]

    outside = (c["loss_date"] < c["inception_date"]) | (c["loss_date"] > c["expiry_date"])
    record("claims", "loss date outside the policy term", "excluded", outside, c.loc[outside, "incurred_dkk"].sum())
    c = c[~outside]

    return c.reset_index(drop=True)
