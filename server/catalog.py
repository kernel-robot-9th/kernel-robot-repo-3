"""Versioned product definitions, not live stock or verified robot capabilities."""
import json
from pathlib import Path
import re

PRODUCTS_PATH = Path(__file__).resolve().parents[1] / "config" / "products.json"
LOADING_STATIONS = ("load-a", "load-b")


def load_products(path=PRODUCTS_PATH):
    """Read once at engine startup; never seed or reset SQLite inventory here."""
    products = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(products, list) or not products:
        raise ValueError("상품 기준 데이터는 비어 있지 않은 목록이어야 합니다")
    by_sku, classes, class_ids = {}, set(), set()
    fields = {"sku", "name", "detector_class", "class_id", "station", "initial_stock", "physical_support"}
    for product in products:
        if not isinstance(product, dict) or set(product) != fields:
            raise ValueError("상품 기준 데이터 필드를 확인하세요")
        sku, name, detector = (product[k] for k in ("sku", "name", "detector_class"))
        if not isinstance(sku, str) or not re.fullmatch(r"SKU-[A-Z0-9]+(?:-[A-Z0-9]+)*", sku) or len(sku) > 64:
            raise ValueError("상품 SKU 형식이 올바르지 않습니다")
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"상품 표시명이 필요합니다: {sku}")
        if not isinstance(detector, str) or not re.fullmatch(r"[a-z][a-z0-9_]*", detector):
            raise ValueError(f"YOLO 클래스명이 올바르지 않습니다: {sku}")
        class_id, stock = product["class_id"], product["initial_stock"]
        if type(class_id) is not int or class_id < 0 or type(stock) is not int or stock < 0:
            raise ValueError(f"클래스 ID와 초기 수량은 0 이상의 정수여야 합니다: {sku}")
        if product["station"] not in LOADING_STATIONS:
            raise ValueError(f"등록된 상차장이 아닙니다: {sku}")
        if product["physical_support"] != "unverified":
            raise ValueError(f"현재 상품 등록은 실물 시연 지원을 확정하지 않습니다: {sku}")
        if sku in by_sku or detector in classes or class_id in class_ids:
            raise ValueError(f"SKU, YOLO 클래스명과 클래스 ID는 중복될 수 없습니다: {sku}")
        by_sku[sku] = product
        classes.add(detector)
        class_ids.add(class_id)
    return by_sku
