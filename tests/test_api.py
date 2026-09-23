import pytest
from fastapi.testclient import TestClient

from app.main import app

CSV = {
    "assets.csv": """asset_id,portfolio_id,region,asset_type,construction_year,sum_insured_dkk
A1,PF-01,Syddanmark,residential,1990,1000000
A2,PF-02,Hovedstaden,commercial,2000,2000000
A3,PF-01,Hovedstaden,industrial,2010,3000000
""",
    "policies.csv": """policy_id,asset_id,peril,inception_date,expiry_date,annual_premium,currency
P1,A1,fire,2023-01-10,2024-01-09,1000,DKK
P2,A1, Flood,2023-01-10,2024-01-09,100,EUR
P3,A2,fire,2023-01-10,2024-01-09,500,DKK
P4,A3,storm,2024-03-01,2025-02-28,200,DKK
""",
    "claims.csv": """claim_id,policy_id,loss_date,reported_date,paid_amount,reserve_amount,currency,status
C1,P1,2023-06-15,2023-06-20,300,0,DKK,settled
C2,P1,2023-06-16,2023-06-20,100,200,DKK,open
C3,P1,2023-06-17,2023-06-20,0,0,DKK,declined
C4,P2,15-06-2023,2023-06-20,10,0,EUR,settled
C5,P-MISSING,2023-06-15,2023-06-20,999,0,DKK,settled
C6,P4,2024-05-01,2024-05-10,50,0,DKK,settled
""",
    "fx_rates.csv": """month,currency,rate_dkk_per_unit
2023-01,EUR,7.5
2023-01,DKK,1.0
2023-06,EUR,7.4
2023-06,DKK,1.0
2024-03,DKK,1.0
2024-05,DKK,1.0
""",
}


@pytest.fixture
def client(tmp_path, monkeypatch):
    for name, content in CSV.items():
        (tmp_path / name).write_text(content)
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    with TestClient(app) as client:
        yield client


def test_loss_experience_per_peril(client):
    body = client.get("/portfolios/PF-01/loss-experience").json()
    perils = {p["peril"]: p for p in body["perils"]}

    assert perils["fire"] == {
        "peril": "fire",
        "policy_count": 1,
        "earned_premium": 1000.0,
        "incurred_loss": 600.0,  # 300 settled + (100 + 200) open + 0 declined
        "loss_ratio": 0.6,
        "claim_count": 2,  # declined claim not counted
        "largest_claim": 300.0,
    }
    assert perils["flood"]["earned_premium"] == 750.0  # 100 EUR at 7.5
    assert perils["flood"]["incurred_loss"] == 74.0  # 10 EUR at 7.4
    assert body["total"]["incurred_loss"] == 724.0  # 674 (2023) + 50 (2024); orphan claim C5 not included


def test_unknown_portfolio_returns_404(client):
    assert client.get("/portfolios/PF-99/loss-experience").status_code == 404


def test_portfolios_are_ordered_by_loss_ratio(client):
    body = client.get("/portfolios/loss-experience").json()
    ratios = [p["loss_ratio"] for p in body["portfolios"]]
    assert [p["portfolio_id"] for p in body["portfolios"]] == ["PF-01", "PF-02"]  # 724/1950 > 0/500
    assert ratios == sorted(ratios, reverse=True)


def test_data_quality_reports_exclusions(client):
    body = client.get("/data-quality").json()
    assert body["claims_kept"] == 5  # C5 excluded: 6 claims in source
    orphan = next(i for i in body["issues"] if i["problem"] == "policy_id not in policies")
    assert orphan["rows"] == 1 and orphan["amount_dkk"] == 999.0


@pytest.mark.parametrize(
    "query, perils, incurred",
    [
        ("underwriting_year=2024", ["storm"], 50.0),
        ("region=Hovedstaden", ["storm"], 50.0),
        ("asset_type=industrial", ["storm"], 50.0),
        ("underwriting_year=2023&region=Syddanmark", ["fire", "flood"], 674.0),
    ],
)
def test_filters_keep_only_matching_policies_and_their_claims(client, query, perils, incurred):
    body = client.get(f"/portfolios/PF-01/loss-experience?{query}").json()
    assert [p["peril"] for p in body["perils"]] == perils
    assert body["total"]["incurred_loss"] == incurred


def test_filter_with_no_matching_policies_returns_404(client):
    assert client.get("/portfolios/PF-02/loss-experience?underwriting_year=2024").status_code == 404


def test_comparison_applies_filters(client):
    body = client.get("/portfolios/loss-experience?region=Hovedstaden").json()
    assert [p["portfolio_id"] for p in body["portfolios"]] == ["PF-01", "PF-02"]  # 50/200 > 0/500
    assert body["portfolios"][0]["earned_premium"] == 200.0
