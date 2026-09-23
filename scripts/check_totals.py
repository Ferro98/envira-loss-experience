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


def independent_figures():
    """Returns {(portfolio, peril): figures} and the number of excluded claims."""
    fx = {(r["month"], r["currency"]): float(r["rate_dkk_per_unit"]) for r in rows("fx_rates")}
    portfolio_of_asset = {r["asset_id"]: r["portfolio_id"] for r in rows("assets")}
    figures = defaultdict(lambda: {"policy_count": 0, "earned_premium": 0.0, "incurred_loss": 0.0,
                                   "claim_count": 0, "largest_claim": 0.0})

    policies = {}
    for p in rows("policies"):
        key = (portfolio_of_asset[p["asset_id"]], p["peril"].strip().lower())
        inception = parse_date(p["inception_date"])
        policies[p["policy_id"]] = (key, inception, parse_date(p["expiry_date"]))
        figures[key]["policy_count"] += 1
        figures[key]["earned_premium"] += float(p["annual_premium"]) * fx[(inception.strftime("%Y-%m"), p["currency"])]

    excluded = 0
    for c in rows("claims"):
        loss = parse_date(c["loss_date"])
        policy = policies.get(c["policy_id"])
        paid, reserve = float(c["paid_amount"]), float(c["reserve_amount"])
        if paid < 0 or policy is None or not (policy[1] <= loss <= policy[2]):
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


def main() -> int:
    from app.data import load_book
    from app.report import loss_experience

    figures, n_excluded = independent_figures()
    book = load_book(DATA)
    ok = True

    n_source = len(rows("claims"))
    kept = len(book.claims)
    print(f"claims: {n_source} in source = {kept} kept + {n_excluded} excluded")
    ok &= kept + n_excluded == n_source

    mismatches = 0
    portfolios = sorted({portfolio for portfolio, _ in figures})
    for portfolio in portfolios:
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

    checked = len(figures) * 5
    print(f"compared {checked} figures ({len(figures)} portfolio/peril pairs x 5 fields): {mismatches} mismatches")
    ok &= mismatches == 0
    print("ALL MATCH" if ok else "MISMATCH FOUND")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
