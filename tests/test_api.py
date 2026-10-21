from fastapi.testclient import TestClient
from server.api import create_app

ADMIN = "test-admin-token-0001"
GATEWAY = "test-gateway-token-0002"


def bearer(value):
    return {"Authorization": "Bearer " + value}


def test_api_auth_customer_isolation_and_request_validation(rig):
    e, _, _ = rig
    with TestClient(create_app(e, ADMIN, GATEWAY)) as client:
        assert client.get("/api/admin/state").status_code == 401
        assert client.get("/api/admin/state", headers=bearer(GATEWAY)).status_code == 401
        assert client.get("/api/gateway/mock/state", headers=bearer(ADMIN)).status_code == 401
        a = client.post("/api/sessions", json={"label": "A"}).json()
        b = client.post("/api/sessions", json={"label": "B"}).json()
        mine = client.get("/api/customer/state", headers=bearer(a["token"])).json()
        assert set(mine["sessions"]) == {a["session_id"]}
        assert b["session_id"] not in str(mine)
        assert client.post("/api/customer/orders", headers=bearer(a["token"]), json={
            "request_id": "test-order-001", "items": [{"sku": "SKU-JIN-RAMEN", "quantity": True}]}).status_code == 422
        assert client.post("/api/customer/orders", headers=bearer(a["token"]), json={
            "request_id": "test-order-001", "session_id": b["session_id"],
            "items": [{"sku": "SKU-JIN-RAMEN", "quantity": 1}]}).status_code == 422
        body = {"request_id": "test-order-001", "items": [{"sku": "SKU-JIN-RAMEN", "quantity": 1}]}
        one = client.post("/api/customer/orders", headers=bearer(a["token"]), json=body)
        two = client.post("/api/customer/orders", headers=bearer(a["token"]), json=body)
        assert one.status_code == two.status_code == 201
        assert one.json()["id"] == two.json()["id"]
        assert client.get("/api/not-a-route").status_code == 404
        assert client.get("/api/admin/state", headers=bearer(ADMIN)).json()["mode"] == "mock"
