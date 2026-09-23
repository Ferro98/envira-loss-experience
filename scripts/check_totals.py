"""Independent cross-check of the loss-experience figures.

Recomputes premium and incurred loss per portfolio straight from the CSVs with
the standard library only (no pandas, no app code), then compares with what the
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


def independent_totals():
    fx = {(r["month"], r["currency"]): float(r["rate_dkk_per_unit"]) for r in rows("fx_rates")}
    portfolio_of_asset = {r["asset_id"]: r["portfolio_id"] for r in rows("assets")}

    premium = defaultdict(float)
    policies = {}
    for p in rows("policies"):
        inception = parse_date(p["inception_date"])
        policies[p["policy_id"]] = (portfolio_of_asset[p["asset_id"]], inception, parse_date(p["expiry_date"]))
        premium[policies[p["policy_id"]][0]] += float(p["annual_premium"]) * fx[(inception.strftime("%Y-%m"), p["currency"])]

    incurred = defaultdict(float)
    excluded = 0
    source_claims = rows("claims")
    for c in source_claims:
        loss = parse_date(c["loss_date"])
        policy = policies.get(c["policy_id"])
        paid, reserve = float(c["paid_amount"]), float(c["reserve_amount"])
        if paid < 0 or policy is None or not (policy[1] <= loss <= policy[2]):
            excluded += 1
            continue
        amount = {"settled": paid, "open": paid + reserve}.get(c["status"], 0.0)
        incurred[policy[0]] += amount * fx[(loss.strftime("%Y-%m"), c["currency"])]
    return premium, incurred, len(source_claims), excluded


def main() -> int:
    from app.data import load_book
    from app.report import loss_experience

    premium, incurred, n_source, n_excluded = independent_totals()
    book = load_book(DATA)
    ok = True

    kept = len(book.claims)
    print(f"claims: {n_source} in source = {kept} kept + {n_excluded} excluded")
    ok &= kept + n_excluded == n_source

    print(f"{'portfolio':<10}{'premium':>16}{'incurred':>16}{'loss ratio':>12}  match")
    for pf in sorted(premium):
        service = loss_experience(book, pf)["total"]
        match = (abs(service["earned_premium"] - premium[pf]) < 0.01
                 and abs(service["incurred_loss"] - incurred[pf]) < 0.01)
        ok &= match
        print(f"{pf:<10}{premium[pf]:>16,.2f}{incurred[pf]:>16,.2f}{incurred[pf] / premium[pf]:>12.3f}  {'OK' if match else 'MISMATCH'}")

    print("ALL MATCH" if ok else "MISMATCH FOUND")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
