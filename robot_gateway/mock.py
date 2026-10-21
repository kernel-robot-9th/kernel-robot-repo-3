"""Explicit virtual observations, separate from the application server.

No elapsed timer completes a task. Each step either transmits/accepts a command,
changes and validates this toy world, or emits a separate observation. This does
not simulate mechanics, camera perception, navigation, or a learned policy.
"""
import argparse
from copy import deepcopy
import json
import os
from pathlib import Path
import time
import urllib.error
import urllib.request
import uuid


def make_event(cmd, kind, data=None, observed_at=None):
    return {"event_id": str(uuid.uuid4()), **{k: cmd[k] for k in
            ["run_id", "task_id", "session_id", "device_id", "mode"]},
            "command_id": cmd["id"], "kind": kind,
            "observed_at": time.time() if observed_at is None else observed_at, "data": data or {}}


class MockWorld:
    def __init__(self, data=None):
        self.data = data or {"positions": {}, "baskets": {}, "delivered": {}, "arms_clear": {}}

    def navigate(self, cmd):
        robot, zone = cmd["robot_id"], cmd["zone_id"]
        if any(r != robot and pos == zone for r, pos in self.data["positions"].items()):
            raise ValueError("모의 구역 동시 진입 감지")
        self.data["positions"][robot] = zone

    def execute_items(self, cmd):
        robot, zone = cmd["robot_id"], cmd["zone_id"]
        if self.data["positions"].get(robot) != zone:
            raise ValueError("모의 로봇이 작업 지점에 없습니다")
        basket = self.data["baskets"].setdefault(robot, {})
        for item in cmd["items"]:
            slot = str(item["slot"])
            if cmd["kind"] == "PICK" and slot in basket:
                raise ValueError("모의 슬롯 중복 적재")
            if cmd["kind"] == "HANDOFF" and basket.get(slot) != item["sku"]:
                raise ValueError("모의 인계 상품 불일치")
        self.data["arms_clear"][zone] = False
        for item in cmd["items"]:
            slot = str(item["slot"])
            if cmd["kind"] == "PICK":
                basket[slot] = item["sku"]
            else:
                del basket[slot]
                self.data["delivered"].setdefault(cmd["basket_id"], []).append(deepcopy(item))
        return deepcopy(cmd["items"])

    def clear_path(self, cmd):
        self.data["arms_clear"][cmd["zone_id"]] = True

    def leave(self, cmd):
        if not self.data["arms_clear"].get(cmd["zone_id"]):
            raise ValueError("모의 로봇팔 경로 이탈 미확인")
        self.data["positions"][cmd["robot_id"]] = "outside"

    def stop(self, cmd):
        # This toy model has no continuously moving actuator. Never report arm
        # clearance or zone vacancy as a side effect of a stop acknowledgement.
        return None

    def execute(self, cmd, fail=False):
        before = deepcopy(self.data)
        try:
            if fail and cmd["kind"] in {"PICK", "HANDOFF"}:
                return make_event(cmd, "FAILED", {"confirmed_items": [], "reason": "모의 집기/인계 실패",
                                                   **({"basket_id": cmd["basket_id"]} if cmd["kind"] == "HANDOFF" else {})})
            data = {}
            if cmd["kind"] == "NAVIGATE":
                self.navigate(cmd)
            elif cmd["kind"] in {"PICK", "HANDOFF"}:
                data["confirmed_items"] = self.execute_items(cmd)
                if cmd["kind"] == "HANDOFF":
                    data["basket_id"] = cmd["basket_id"]
                    data.update(cart_visible=True, cart_empty=not self.data["baskets"][cmd["robot_id"]],
                                last_item_placed=True, standby_reached=True)
                    return make_event(cmd, "TRANSFER_READY", data)
            elif cmd["kind"] == "LEAVE":
                self.leave(cmd)
            elif cmd["kind"] == "STOP":
                self.stop(cmd)
                data["stopped"] = True
            elif cmd["kind"] == "STOP_POLICY":
                data.update(policy_stopped=True, motion_stopped=True, hold_confirmed=True, torque_enabled=True)
            else:
                raise ValueError("지원하지 않는 모의 명령")
            return make_event(cmd, "SUCCEEDED", data)
        except ValueError as exc:
            self.data = before
            return make_event(cmd, "FAILED", {"confirmed_items": [], "reason": str(exc),
                                               **({"basket_id": cmd["basket_id"]} if cmd["kind"] == "HANDOFF" else {})})

    def observe(self, cmd, kind, observed_at=None):
        if kind == "STOPPED":
            if self.data["positions"].get(cmd["robot_id"]) != cmd["zone_id"]:
                raise ValueError("모의 정차 위치 불일치")
            return make_event(cmd, kind, {"stopped": True, "zone_id": cmd["zone_id"]}, observed_at)
        if kind == "ARM_CLEAR":
            self.clear_path(cmd)
            return make_event(cmd, kind, {"clear": True}, observed_at)
        if kind == "EXITED":
            if self.data["positions"].get(cmd["robot_id"]) != "outside":
                raise ValueError("모의 구역 이탈 미확인")
            return make_event(cmd, kind, {"outside": True, "zone_id": cmd["zone_id"]}, observed_at)
        raise ValueError("지원하지 않는 관측")


def next_action(snapshot):
    commands = list(snapshot["commands"].values())
    commands.sort(key=lambda c: c["kind"] != "STOP")
    for cmd in commands:
        task = snapshot["tasks"][cmd["task_id"]]
        if not snapshot["devices"][cmd["device_id"]]["connected"]:
            continue
        if snapshot["sessions"][cmd["session_id"]]["error"] and cmd["kind"] != "STOP":
            continue
        if cmd["status"] == "CREATED":
            return "CLAIM", cmd
        if cmd["status"] == "SENT":
            return "ACCEPTED", cmd
        if cmd["status"] == "ACCEPTED":
            return "EXECUTE", cmd
        if cmd["status"] == "SUCCEEDED":
            if cmd["kind"] == "NAVIGATE" and task["state"] in {"WAIT_STOP", "WAIT_BASKET"}:
                if task["stopped_at"] is None or snapshot["server_time"] - task["stopped_at"] > 240:
                    return "STOPPED", cmd
            if cmd["kind"] in {"PICK", "HANDOFF"} and task["state"] == "WAIT_ARM_CLEAR":
                return "ARM_CLEAR", cmd
            if cmd["kind"] == "LEAVE" and task["state"] == "WAIT_EXIT":
                return "EXITED", cmd
    return None


class Client:
    def __init__(self, base, token):
        self.base, self.token = base.rstrip("/"), token
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def call(self, path, body=None):
        request = urllib.request.Request(self.base + path,
            data=json.dumps(body).encode() if body is not None else None,
            headers={"Authorization": "Bearer " + self.token, "Content-Type": "application/json"})
        with self.opener.open(request, timeout=5) as response:
            return json.load(response)


def run():
    parser = argparse.ArgumentParser(description="가상 상태 모델만 실행합니다. 실제 장비는 연결하지 않습니다.")
    parser.add_argument("--server", default="http://127.0.0.1:8000")
    parser.add_argument("--auto", action="store_true", help="관제 단계 버튼 없이 모의 모델 단계를 처리")
    parser.add_argument("--state", default="runtime/mock-world.json")
    args = parser.parse_args()
    token = os.environ.get("SHOP_GATEWAY_TOKEN", "")
    if len(token) < 16:
        parser.error("SHOP_GATEWAY_TOKEN 환경 변수가 필요합니다")
    client, gateway_id = Client(args.server, token), str(uuid.uuid4())
    state_path = Path(args.state)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state = json.loads(state_path.read_text()) if state_path.exists() else {"run_id": None, "world": None, "pending": None}
    world = MockWorld(state["world"])

    def save():
        state["world"] = world.data
        temp = state_path.with_suffix(".tmp")
        temp.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
        os.replace(temp, state_path)

    print("MOCK ONLY · 실제 장비 검증 아님 · " + ("자동 관측" if args.auto else "관리자 화면의 단계 진행을 기다립니다"), flush=True)
    offline_reported = False
    while True:
        try:
            hello = client.call("/api/gateway/heartbeat", {"gateway_id": gateway_id})
            if hello['mode'] != 'mock':
                raise RuntimeError('모의 실행부는 실물 모드에 연결할 수 없습니다')
            if hello["run_id"] != state["run_id"]:
                state.update(run_id=hello["run_id"], pending=None)
                world = MockWorld()
                save()
            if state["pending"]:
                client.call("/api/gateway/events", state["pending"])
                state["pending"] = None
                save()
            snapshot = client.call("/api/gateway/mock/state")
            action = next_action(snapshot)
            if action and (args.auto or client.call("/api/gateway/mock/permit", {})["allowed"]):
                kind, cmd = action
                if kind == "CLAIM":
                    client.call("/api/gateway/commands/claim", {"gateway_id": gateway_id})
                else:
                    if kind == "ACCEPTED":
                        event = make_event(cmd, kind)
                    elif kind == "EXECUTE":
                        fail = cmd["kind"] in {"PICK", "HANDOFF"} and client.call(
                            "/api/gateway/mock/failure", {"device_id": cmd["device_id"]})["fail"]
                        event = world.execute(cmd, fail)
                    else:
                        event = world.observe(cmd, kind)
                    # Persist the simulated world and outbound result BEFORE send.
                    # A lost response retries this exact event, not the operation.
                    state["pending"] = event
                    save()
                    client.call("/api/gateway/events", event)
                    state["pending"] = None
                    save()
            if offline_reported:
                print("서버 통신 복구. 오류 작업은 자동 복구하지 않습니다.", flush=True)
            offline_reported = False
        except urllib.error.HTTPError as exc:
            print(f"서버가 모의 보고를 거부했습니다 ({exc.code}). 상태 파일을 보존했습니다. 관제 오류와 이력을 확인하세요.", flush=True)
            raise SystemExit(1) from exc
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            if not offline_reported:
                print("서버 연결 실패. 미전달 결과를 보존하고 연결을 재확인합니다.", flush=True)
            offline_reported = True
        time.sleep(0.5)  # Transport pacing only. It does NOT imply task success.


if __name__ == "__main__":
    run()
