import pandas as pd
import pytest

from app.data import build_book

ASSETS = pd.DataFrame(
    [{"asset_id": "A1", "portfolio_id": "PF-01", "region": "Syddanmark", "asset_type": "residential",
      "construction_year": "1990", "sum_insured_dkk": "1000000"}]
)
FX = pd.DataFrame(
    [
        {"month": "2022-12", "currency": "DKK", "rate_dkk_per_unit": "1.0"},
        {"month": "2023-01", "currency": "EUR", "rate_dkk_per_unit": "7.5"},
        {"month": "2023-01", "currency": "DKK", "rate_dkk_per_unit": "1.0"},
        {"month": "2023-06", "currency": "EUR", "rate_dkk_per_unit": "7.4"},
        {"month": "2023-06", "currency": "DKK", "rate_dkk_per_unit": "1.0"},
    ]
)


def policy(policy_id="P1", peril="fire", premium="1000", currency="DKK", inception="2023-01-10", expiry="2024-01-09"):
    return {"policy_id": policy_id, "asset_id": "A1", "peril": peril, "inception_date": inception,
            "expiry_date": expiry, "annual_premium": premium, "currency": currency}


def claim(claim_id="C1", policy_id="P1", loss="2023-06-15", paid="100", reserve="0", currency="DKK", status="settled"):
    return {"claim_id": claim_id, "policy_id": policy_id, "loss_date": loss, "reported_date": loss,
            "paid_amount": paid, "reserve_amount": reserve, "currency": currency, "status": status}


def book(policies, claims):
    return build_book(ASSETS, pd.DataFrame(policies), pd.DataFrame(claims, columns=list(claim())), FX)


def issue_rows(b, issue_prefix):
    return sum(i["rows"] for i in b.issues if i["issue"].startswith(issue_prefix))


def test_peril_is_normalised_and_reported():
    b = book([policy("P1", " Fire  "), policy("P2", "FIRE"), policy("P3", "fire")], [])
    assert set(b.policies["peril"]) == {"fire"}
    assert issue_rows(b, "peril") == 2


def test_premium_converted_at_inception_month_rate():
    b = book([policy(premium="100", currency="EUR", inception="2023-01-10")], [])
    assert b.policies.loc[0, "premium_dkk"] == pytest.approx(750.0)


@pytest.mark.parametrize(
    "status, paid, reserve, expected",
    [
        ("settled", "100", "50", 100.0),  # settled: paid only, reserve ignored
        ("open", "100", "50", 150.0),  # open: paid + reserve
        ("withdrawn", "0", "0", 0.0),
        ("declined", "0", "0", 0.0),
    ],
)
def test_incurred_by_status(status, paid, reserve, expected):
    b = book([policy()], [claim(status=status, paid=paid, reserve=reserve)])
    assert b.claims.loc[0, "incurred_dkk"] == pytest.approx(expected)


def test_claim_converted_in_its_own_currency_at_loss_month():
    # DKK policy, EUR claim: each amount uses its own currency
    b = book([policy(currency="DKK")], [claim(currency="EUR", paid="10", loss="2023-06-15")])
    assert b.claims.loc[0, "incurred_dkk"] == pytest.approx(74.0)


def test_day_first_dates_are_parsed():
    b = book([policy()], [claim(loss="02-06-2023")])
    assert b.claims.loc[0, "loss_date"] == pd.Timestamp("2023-06-02")
    assert issue_rows(b, "date in DD-MM-YYYY") == 1


def test_negative_paid_uses_absolute_value():
    b = book([policy()], [claim(paid="-100")])
    assert b.claims.loc[0, "incurred_dkk"] == pytest.approx(100.0)
    assert issue_rows(b, "negative paid_amount") == 1


def test_orphan_claim_is_excluded_and_reported():
    b = book([policy()], [claim("C1"), claim("C2", policy_id="P-MISSING", paid="500")])
    assert list(b.claims["claim_id"]) == ["C1"]
    orphan = next(i for i in b.issues if i["issue"].startswith("policy_id not in"))
    assert orphan["rows"] == 1 and orphan["amount_dkk"] == 500.0


def test_loss_before_inception_is_excluded_and_reported():
    b = book([policy(inception="2023-01-10")], [claim("C1"), claim("C2", loss="2022-12-01")])
    assert list(b.claims["claim_id"]) == ["C1"]
    assert issue_rows(b, "loss date outside") == 1


def test_duplicate_claim_id_is_not_double_counted():
    b = book([policy()], [claim("C1"), claim("C1")])
    assert len(b.claims) == 1
    assert issue_rows(b, "duplicate claim_id") == 1


def test_every_source_claim_is_either_kept_or_reported_as_excluded():
    claims = [claim("C1"), claim("C2", policy_id="X"), claim("C3", loss="2020-01-01"), claim("C1")]
    b = book([policy()], claims)
    excluded = sum(i["rows"] for i in b.issues if i["table"] == "claims" and i["action"].startswith("excluded"))
    assert len(b.claims) + excluded == len(claims)
