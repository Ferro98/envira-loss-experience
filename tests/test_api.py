import pytest
from fastapi.testclient import TestClient

from app.main import app

CSV = {
    "assets.csv": """asset_id,portfolio_id,region,asset_type,construction_year,sum_insured_dkk
A1,PF-01,Syddanmark,residential,1990,1000000
A2,PF-02,Hovedstaden,commercial,2000,2000000
""",
    "policies.csv": """policy_id,asset_id,peril,inception_date,expiry_date,annual_premium,currency
P1,A1,fire,2023-01-10,2024-01-09,1000,DKK
P2,A1, Flood,2023-01-10,2024-01-09,100,EUR
P3,A2,fire,2023-01-10,2024-01-09,500,DKK
""",
    "claims.csv": """claim_id,policy_id,loss_date,reported_date,paid_amount,reserve_amount,currency,status
C1,P1,2023-06-15,2023-06-20,300,0,DKK,settled
C2,P1,2023-06-16,2023-06-20,100,200,DKK,open
C3,P1,2023-06-17,2023-06-20,0,0,DKK,declined
C4,P2,15-06-2023,2023-06-20,10,0,EUR,settled
C5,P-MISSING,2023-06-15,2023-06-20,999,0,DKK,settled
""",
    "fx_rates.csv": """month,currency,rate_dkk_per_unit
2023-01,EUR,7.5
2023-01,DKK,1.0
2023-06,EUR,7.4
2023-06,DKK,1.0
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
    assert body["total"]["incurred_loss"] == 674.0  # orphan claim C5 not included


def test_unknown_portfolio_returns_404(client):
    assert client.get("/portfolios/PF-99/loss-experience").status_code == 404
