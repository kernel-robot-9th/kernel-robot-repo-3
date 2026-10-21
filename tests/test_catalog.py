"""Catalog/YOLO contract, routing, and non-destructive checkpoint compatibility."""
from copy import deepcopy
import json

import pytest
from fastapi.testclient import TestClient

from server.api import create_app
from server.catalog import PRODUCTS_PATH, load_products
from server.domain import DomainError, Engine
from test_api import ADMIN, GATEWAY, bearer
from conftest import command, order


def test_catalog_matches_yolo_labels_and_demo_placement():
    products = list(load_products().values())
    # Original classes.txt order is part of the detector-to-product contract.
    labels = ["jin_ramen", "shin_ramen", "seoul_milk", "banana_milk_bottle",
              "banana_milk_carton", "m_and_ms", "cheetos", "choco_pie",
              "shrimp_cracker", "rice_chip"]
    assert [(p["class_id"], p["detector_class"]) for p in products] == list(enumerate(labels))
    assert len({p["sku"] for p in products}) == 10
    assert all(p["station"] == "load-a" and p["initial_stock"] == 1 for p in products[:9])
    assert products[9]["sku"] == "SKU-RICE-CHIP"
    assert products[9]["station"] == "load-b" and products[9]["initial_stock"] == 8
    assert sum(p["initial_stock"] for p in products) == 17
    assert all(p["physical_support"] == "unverified" for p in products)
    assert not any("available" in p or "on_hand" in p for p in products)


@pytest.mark.parametrize("field,value", [
    ("sku", "invalid"), ("class_id", True), ("class_id", -1),
    ("initial_stock", True), ("initial_stock", -1), ("station", "handoff"),
    ("name", " "), ("detector_class", ""), ("physical_support", "verified"),
])
def test_invalid_catalog_fails_before_creating_database(tmp_path, field, value):
    products = json.loads(PRODUCTS_PATH.read_text(encoding="utf-8"))
    products[0][field] = value
    config = tmp_path / "products.json"
    config.write_text(json.dumps(products), encoding="utf-8")
    database = tmp_path / "must-not-exist.db"
    with pytest.raises(ValueError):
        Engine(str(database), catalog_path=config)
    assert not database.exists()


@pytest.mark.parametrize("field", ["sku", "detector_class", "class_id"])
def test_ambiguous_product_mapping_is_rejected(tmp_path, field):
    products = json.loads(PRODUCTS_PATH.read_text(encoding="utf-8"))
    products[1][field] = products[0][field]
    config = tmp_path / "products.json"
    config.write_text(json.dumps(products), encoding="utf-8")
    with pytest.raises(ValueError, match="중복"):
        load_products(config)


def test_catalog_lookup_consistent_for_public_customer_and_admin(rig):
    engine, _, _ = rig
    with TestClient(create_app(engine, ADMIN, GATEWAY)) as client:
        result = client.get("/api/products")
        assert result.status_code == 200 and result.json()["mode"] == "mock"
        products = result.json()["items"]
        session = client.post("/api/sessions", json={"label": "상품 조회"}).json()
        for path, token in [("/api/customer/state", session["token"]), ("/api/admin/state", ADMIN)]:
            state = client.get(path, headers=bearer(token)).json()
            assert state["products"] == products
            assert state["mode"] == "mock"
        for sku in ["DEMO-APPLE", "UNKNOWN", "jin_ramen"]:
            response = client.post("/api/customer/orders", headers=bearer(session["token"]), json={
                "request_id": "unknown-product-001", "items": [{"sku": sku, "quantity": 1}]})
            assert response.status_code == 422
        assert not engine.snapshot()["orders"]
    exposed = engine.snapshot()
    exposed["products"][0]["station"] = "handoff"
    assert engine.snapshot()["products"][0]["station"] == "load-a"


def test_real_skus_route_to_a_and_b_and_only_mock_results_change_item_ledger(rig):
    engine, harness, _ = rig
    sid = engine.create_session("상품 연결")['session_id']
    engine.submit_order(sid, [{"sku": "SKU-JIN-RAMEN", "quantity": 1},
                              {"sku": "SKU-RICE-CHIP", "quantity": 1}], "catalog-order-001")
    tasks = list(engine.snapshot()["tasks"].values())
    assert [(t["items"][0]["sku"], t["zone_id"], t["device_id"]) for t in tasks] == [
        ("SKU-JIN-RAMEN", "load-a", "omx-a"), ("SKU-RICE-CHIP", "load-b", "omx-b")]
    harness.until(lambda s: command(s, "PICK", "ACCEPTED") is not None)
    assert engine.snapshot()["sessions"][sid]["inventory"] == []
    harness.until(lambda s: len(s["sessions"][sid]["inventory"]) == 2)
    assert {i["sku"] for i in engine.snapshot()["sessions"][sid]["inventory"]} == {
        "SKU-JIN-RAMEN", "SKU-RICE-CHIP"}
    assert sum(p["initial_stock"] for p in engine.snapshot()["products"]) == 17


def test_legacy_checkpoint_is_preserved_without_reoffering_legacy_sku(tmp_path):
    database = str(tmp_path / "legacy.db")
    engine = Engine(database)
    sid = engine.create_session("기존 고객")["session_id"]
    order(engine, sid)
    # Reproduce a checkpoint written before catalog migration, including an active task.
    for existing in engine.state["orders"].values():
        existing["items"] = {"DEMO-APPLE": 1}
    for task in engine.state["tasks"].values():
        for item in task["items"]:
            item["sku"] = "DEMO-APPLE"
    engine.store.save(engine.state, [])
    before = deepcopy(engine.state)
    engine.store.close()
    restored = Engine(database)
    try:
        state = restored.snapshot()
        assert state["run_id"] == before["run_id"]
        assert restored.state["orders"] == before["orders"]
        assert state["tasks"].keys() == before["tasks"].keys()
        assert state["sessions"][sid]["state"] == "RECOVERY_REQUIRED"
        assert all(t["items"] == before["tasks"][tid]["items"] for tid, t in state["tasks"].items())
        assert "DEMO-APPLE" not in {p["sku"] for p in state["products"]}
        with pytest.raises(DomainError):
            order(restored, sid, sku="DEMO-APPLE", request_id="legacy-new-order")
    finally:
        restored.store.close()
