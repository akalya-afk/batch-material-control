import pytest
from app.main import create_app


@pytest.fixture()
def client(tmp_path):
    app = create_app(str(tmp_path / "test.db"))
    return app.test_client()


def issue(client, order, item, lot, qty):
    return client.post("/api/issues", json={"order": order, "item": item, "lot": lot, "qty": qty})


def lot_bal(client, lot):
    return client.get(f"/api/lots/{lot}/batches").get_json()["balance"]


def test_seed_loaded(client):
    d = client.get("/api/state").get_json()
    assert len(d["orders"]) == 3 and len(d["lots"]) == 8 and len(d["bom"]) == 5


def test_quarantined_lot_is_refused_and_logged(client):
    r = issue(client, "PO-1042", "RM-PP-001", "PP-2609-B", 412)
    assert r.status_code == 409 and "quarantined" in r.get_json()["detail"]
    assert lot_bal(client, "PP-2609-B") == 800            # nothing left the lot
    issues = client.get("/api/state").get_json()["issues"]
    blocked = [i for i in issues if not i["ok"]]
    assert len(blocked) == 1 and blocked[0]["lot"] == "PP-2609-B"


def test_partly_used_lot(client):
    r = issue(client, "PO-1042", "RM-PP-001", "PP-2610-C", 412)
    assert r.status_code == 200
    assert lot_bal(client, "PP-2610-C") == 188
    # EL-2610-A already partly used by two batches
    d = client.get("/api/lots/EL-2610-A/batches").get_json()
    assert d["balance"] == 44500 and set(d["batches"]) == {"PO-1041", "PO-1042"}


def test_cannot_issue_more_than_lot_balance(client):
    issue(client, "PO-1042", "RM-PP-001", "PP-2610-C", 412)
    r = issue(client, "PO-1042", "RM-PP-001", "PP-2610-C", 999)
    assert r.status_code == 409 and lot_bal(client, "PP-2610-C") == 188


def test_lot_must_match_item(client):
    assert issue(client, "PO-1042", "RM-PP-001", "BL-2609-A", 10).status_code == 409


def test_closed_order_rejects_issue(client):
    assert issue(client, "PO-1041", "RM-PP-001", "PP-2610-C", 10).status_code == 409


def test_over_plan_issue_is_variance(client):
    issue(client, "PO-1042", "RM-PP-001", "PP-2610-C", 412)
    r = issue(client, "PO-1042", "RM-PP-001", "PP-2610-C", 10)
    assert r.get_json()["warn"] is True
    m = client.get("/api/orders/PO-1042/summary").get_json()["materials"][0]
    assert m["plan"] == 700 and m["issued"] == 710 and m["variance"] == 10


def test_first_issue_starts_order(client):
    issue(client, "PO-1043", "PK-CT-005", "CT-2610-A", 500)
    orders = {o["no"]: o["status"] for o in client.get("/api/state").get_json()["orders"]}
    assert orders["PO-1043"] == "In production"


def test_yield_against_standard(client):
    s = client.get("/api/orders/PO-1041/summary").get_json()
    assert (s["good"], s["scrap"]) == (96400, 3100)
    assert s["yield_pct"] == 96.88 and s["gap_points"] == -1.12 and s["excess_scrap"] == 1110
    s2 = client.get("/api/orders/PO-1042/summary").get_json()
    assert s2["yield_pct"] == 97.16 and s2["gap_points"] == -0.84


def test_record_output_updates_yield(client):
    client.post("/api/outputs", json={"order": "PO-1042", "kind": "good", "qty": 10000})
    client.post("/api/outputs", json={"order": "PO-1042", "kind": "scrap", "qty": 100, "reason": "Short shot"})
    s = client.get("/api/orders/PO-1042/summary").get_json()
    assert (s["good"], s["scrap"]) == (40800, 1000)


def test_scrap_needs_reason_and_whole_qty(client):
    assert client.post("/api/outputs", json={"order": "PO-1042", "kind": "scrap", "qty": 5}).status_code == 422
    assert client.post("/api/outputs", json={"order": "PO-1042", "kind": "good", "qty": 5.5}).status_code == 422


def test_create_order_from_bom(client):
    r = client.post("/api/orders", json={"qty": 50000})
    assert r.status_code == 201 and r.get_json()["no"] == "PO-1044"
    assert client.post("/api/orders", json={"qty": 10}).status_code == 422
    s = client.get("/api/orders/PO-1044/summary").get_json()
    assert s["materials"][0]["plan"] == 350 and s["materials"][2]["plan"] == 1.2


def test_reset_restores_seed(client):
    issue(client, "PO-1042", "RM-PP-001", "PP-2610-C", 412)
    client.post("/api/reset")
    assert lot_bal(client, "PP-2610-C") == 600
