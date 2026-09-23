"""Independent cross-check of the loss-experience figures.

Recomputes every figure per portfolio and peril straight from the CSVs with the
standard library only (no pandas, no app code), then compares with what the
service reports. Run from the repository root:

    python scripts/check_totals.py
"""

import csv
import os
import sys
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

DATA = Path(os.environ.get("DATA_DIR", "data"))


def rows(name):
    with open(DATA / f"{name}.csv", newline="") as f:
        return list(csv.DictReader(f))


def parse_date(s: str) -> date:
    for fmt in ("%Y-%m-%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    raise ValueError(s)


def independent_figures(year=None, region=None, asset_type=None):
    """Returns {(portfolio, peril): figures} and the number of excluded claims.

    Only policies matching the (optional) filters, and their claims, are counted."""
    fx = {(r["month"], r["currency"]): float(r["rate_dkk_per_unit"]) for r in rows("fx_rates")}
    assets = {r["asset_id"]: r for r in rows("assets")}
    figures = defaultdict(lambda: {"policy_count": 0, "earned_premium": 0.0, "incurred_loss": 0.0,
                                   "claim_count": 0, "largest_claim": 0.0})

    policies = {}
    for p in rows("policies"):
        asset = assets[p["asset_id"]]
        key = (asset["portfolio_id"], p["peril"].strip().lower())
        inception = parse_date(p["inception_date"])
        if (year not in (None, inception.year) or region not in (None, asset["region"])
                or asset_type not in (None, asset["asset_type"])):
            continue
        policies[p["policy_id"]] = (key, inception, parse_date(p["expiry_date"]))
        figures[key]["policy_count"] += 1
        figures[key]["earned_premium"] += float(p["annual_premium"]) * fx[(inception.strftime("%Y-%m"), p["currency"])]

    all_policy_ids = {p["policy_id"] for p in rows("policies")}
    excluded = 0
    for c in rows("claims"):
        loss = parse_date(c["loss_date"])
        policy = policies.get(c["policy_id"])
        paid, reserve = float(c["paid_amount"]), float(c["reserve_amount"])
        if paid < 0 or c["policy_id"] not in all_policy_ids:
            excluded += 1
            continue
        if policy is None:  # policy exists but is filtered out
            continue
        if not (policy[1] <= loss <= policy[2]):
            excluded += 1
            continue
        key = policy[0]
        amount = {"settled": paid, "open": paid + reserve}.get(c["status"], 0.0)
        amount_dkk = amount * fx[(loss.strftime("%Y-%m"), c["currency"])]
        figures[key]["incurred_loss"] += amount_dkk
        figures[key]["largest_claim"] = max(figures[key]["largest_claim"], amount_dkk)
        if c["status"] in ("settled", "open"):
            figures[key]["claim_count"] += 1
    return figures, excluded


def compare(figures, book) -> int:
    """Compare every figure per portfolio and peril; returns the number of mismatches."""
    from app.report import loss_experience

    mismatches = 0
    for portfolio in sorted({portfolio for portfolio, _ in figures}):
        service = {row["peril"]: row for row in loss_experience(book, portfolio)["perils"]}
        expected_perils = {peril for pf, peril in figures if pf == portfolio}
        if set(service) != expected_perils:
            print(f"{portfolio}: perils differ: {sorted(service)} vs {sorted(expected_perils)}")
            mismatches += 1
            continue
        for peril in sorted(expected_perils):
            for field, expected in figures[(portfolio, peril)].items():
                actual = service[peril][field]
                if abs(actual - expected) > 0.01:
                    print(f"MISMATCH {portfolio} {peril} {field}: service {actual}, independent {expected:.2f}")
                    mismatches += 1
    return mismatches


def main() -> int:
    from app.data import load_book
    from app.report import filter_book

    book = load_book(DATA)
    figures, n_excluded = independent_figures()

    n_source = len(rows("claims"))
    kept = len(book.claims)
    print(f"claims: {n_source} in source = {kept} kept + {n_excluded} excluded")
    ok = kept + n_excluded == n_source

    assets = rows("assets")
    filters = [{}]
    filters += [{"year": y} for y in sorted({parse_date(p["inception_date"]).year for p in rows("policies")})]
    filters += [{"region": r} for r in sorted({a["region"] for a in assets})]
    filters += [{"asset_type": t} for t in sorted({a["asset_type"] for a in assets})]

    for f in filters:
        figures, _ = independent_figures(**f)
        filtered = filter_book(book, f.get("year"), f.get("region"), f.get("asset_type"))
        mismatches = compare(figures, filtered)
        print(f"{str(f or 'no filter'):<30} {len(figures) * 5:>4} figures compared, {mismatches} mismatches")
        ok &= mismatches == 0

    print("ALL MATCH" if ok else "MISMATCH FOUND")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
