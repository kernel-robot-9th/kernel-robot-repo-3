"""Isolated HTTP integration scenario with two processes and a temporary DB.

Creates NO orders in a user's running server. It starts its own loopback server
and gateway, saves evidence under reports/, and removes temporary credentials.
"""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import platform
import secrets
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from robot_gateway.mock import Client


def scenario():
    if platform.system() != "Linux":
        raise SystemExit("Ubuntu에서 실행하세요")
    reports = ROOT / "reports"
    reports.mkdir(exist_ok=True)
    report = {"mode": "mock", "physical_robot_verified": False, "status": "RUNNING",
              "started_at": datetime.now(timezone.utc).isoformat()}
    server = gateway = None
    with tempfile.TemporaryDirectory(prefix="shopping-demo-") as tmp:
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        base = f"http://127.0.0.1:{port}"
        admin_token, gateway_token = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        env = {**os.environ, "SHOP_ADMIN_TOKEN": admin_token, "SHOP_GATEWAY_TOKEN": gateway_token,
               "SHOP_DB": str(Path(tmp) / "demo.db")}
        public, admin = Client(base, ""), Client(base, admin_token)
        try:
            with (reports / "demo-server.log").open("w") as server_log, (reports / "demo-gateway.log").open("w") as gateway_log:
                server = subprocess.Popen([sys.executable, "-m", "uvicorn", "server.api:create_app", "--factory",
                                            "--host", "127.0.0.1", "--port", str(port), "--workers", "1"],
                                           cwd=ROOT, env=env, stdout=server_log, stderr=subprocess.STDOUT)
                deadline = time.monotonic() + 20
                while True:
                    if server.poll() is not None:
                        raise RuntimeError("시험 서버 시작 실패: demo-server.log 확인")
                    try:
                        public.call("/api/health")
                        break
                    except (urllib.error.URLError, TimeoutError):
                        if time.monotonic() > deadline:
                            raise RuntimeError("시험 서버 시작 시간 초과")
                        time.sleep(0.2)
                gateway = subprocess.Popen([sys.executable, "-m", "robot_gateway.mock", "--auto", "--server", base,
                                             "--state", str(Path(tmp) / "world.json")],
                                            cwd=ROOT, env=env, stdout=gateway_log, stderr=subprocess.STDOUT)
                people = []
                for name in ["고객 A", "고객 B"]:
                    person = public.call("/api/sessions", {"label": name})
                    customer = Client(base, person["token"])
                    customer.call("/api/customer/orders", {"request_id": secrets.token_hex(12), "items": [
                        {"sku": "DEMO-APPLE", "quantity": 1}, {"sku": "DEMO-SNACK", "quantity": 1}]})
                    customer.call("/api/customer/checkout", {})
                    people.append(person)
                assert people[0]["robot_id"] != people[1]["robot_id"]
                observed_queue = False
                prepared = set()
                deadline = time.monotonic() + 120
                while time.monotonic() < deadline:
                    if gateway.poll() is not None:
                        raise RuntimeError("모의 연결 프로그램 종료: demo-gateway.log 확인")
                    snapshot = admin.call("/api/admin/state")
                    observed_queue |= any(z["queue"] for z in snapshot["zones"].values())
                    for sid, session in snapshot["sessions"].items():
                        assert not session["error"], session["error"]
                        if session["current_task"]:
                            task = snapshot["tasks"][session["current_task"]]
                            if task["state"] == "WAIT_BASKET" and task["id"] not in prepared:
                                # Simulates the operator's customer-specific basket readiness input.
                                admin.call("/api/admin/basket-ready", {"session_id": sid, "task_id": task["id"], "basket_id": session["basket_id"]})
                                prepared.add(task["id"])
                    if all(s["state"] == "COMPLETED" and s["current_task"] is None for s in snapshot["sessions"].values()):
                        assert len(snapshot["sessions"]) == 2 and observed_queue
                        assert all(len(s["inventory"]) == 2 and all(i["delivered"] for i in s["inventory"])
                                   for s in snapshot["sessions"].values())
                        assert all(z["owner"] is None for z in snapshot["zones"].values())
                        report.update(status="PASS", observed_queue=True, final_state=snapshot,
                                      audit=admin.call("/api/admin/logs")["items"])
                        break
                    time.sleep(0.2)
                else:
                    raise RuntimeError("통합 시나리오 시간 초과")
        except Exception as exc:
            report.update(status="FAIL", error=str(exc))
            raise
        finally:
            for process in [gateway, server]:
                if process and process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=8)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
            report["finished_at"] = datetime.now(timezone.utc).isoformat()
            (reports / "demo.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("두 고객 HTTP 모의 시나리오 PASS · reports/demo.json · 실제 로봇 검증 아님")


if __name__ == "__main__":
    scenario()
