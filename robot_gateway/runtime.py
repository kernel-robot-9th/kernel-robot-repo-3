"""Common A/B/C worker. Current backend is MOCK ONLY, never hardware control."""
import argparse
import json
import os
from pathlib import Path
import time
import urllib.error
import uuid

from .mock import Client, make_event, next_action


def save_state(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    os.replace(temporary, path)


def main():
    parser = argparse.ArgumentParser(description="분산 중개 · MOCK ONLY · 실물 드라이버 미연결")
    parser.add_argument("--node", required=True, choices=["gateway-a", "gateway-b", "gateway-c"])
    parser.add_argument("--server", default="http://127.0.0.1:8000")
    parser.add_argument("--auto", action="store_true")
    parser.add_argument("--interval", type=float, default=0.25)
    parser.add_argument("--state")
    parser.add_argument("--token-file", help="해당 중개 토큰만 담긴 로컬 파일")
    parser.add_argument("--mode", choices=["mock"], default="mock")
    args = parser.parse_args()
    if not 0.05 <= args.interval <= 2:
        parser.error("interval은 0.05~2초 범위입니다")
    token = Path(args.token_file).read_text().strip() if args.token_file else os.getenv("SHOP_NODE_TOKEN", "")
    if len(token) < 16:
        parser.error("SHOP_NODE_TOKEN 또는 --token-file의 16자 이상 토큰이 필요합니다")
    path = Path(args.state or f"runtime/{args.node}/state.json")
    state = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"run_id": None, "pending": None}
    # New instance after process restart; do not silently adopt old commands.
    instance = str(uuid.uuid4())
    identity = {"node_id": args.node, "instance_id": instance}
    client = Client(args.server, token)
    offline = False
    print(f"{args.node} · MOCK · 실제 장비 연결 없음", flush=True)
    while True:
        try:
            hello = client.call("/api/nodes/heartbeat", identity)
            if hello["run_id"] != state["run_id"]:
                state = {"run_id": hello["run_id"], "pending": None}
                save_state(path, state)
            if state["pending"]:
                # A retained report from an earlier process needs reconciliation.
                if state["pending"].get("instance_id") != instance:
                    print("이전 프로세스의 미전달 결과를 보존했습니다. 상태 확인 후 새 실행을 시작하세요.", flush=True)
                    return 2
                client.call("/api/nodes/events", state["pending"])
                state["pending"] = None
                save_state(path, state)
            snapshot = client.call("/api/nodes/work", identity)
            choice = next_action(snapshot)
            if choice and (args.auto or client.call("/api/nodes/mock/permit", identity)["allowed"]):
                action, command = choice
                if action == "CLAIM":
                    client.call("/api/nodes/commands/claim", identity)
                else:
                    event = (make_event(command, "ACCEPTED") if action == "ACCEPTED" else
                             client.call("/api/nodes/mock/action", {**identity, "command_id": command["id"], "action": action}))
                    state["pending"] = {**identity, "event": event}
                    save_state(path, state)
                    client.call("/api/nodes/events", state["pending"])
                    state["pending"] = None
                    save_state(path, state)
            if offline:
                print("통신 재연결 · 오류 작업 자동 재실행 없음", flush=True)
            offline = False
        except urllib.error.HTTPError as exc:
            if exc.code == 409:
                # An administrator may replace the MOCK run between heartbeat
                # and work/event. Re-handshake only for a *different* run; never
                # retry an uncertain action in the same run.
                try:
                    hello = client.call("/api/nodes/heartbeat", identity)
                    if hello["run_id"] != state["run_id"]:
                        state = {"run_id": hello["run_id"], "pending": None}
                        save_state(path, state)
                        continue
                except (urllib.error.URLError, TimeoutError, ConnectionError):
                    pass
                # A duplicate process, restart or stale physical state is not a
                # retryable execution request. Preserve the outbox and stop.
                print("중개 실행 보류(409) · 관제 오류와 기존 프로세스를 확인하세요.", flush=True)
                return 2
            print(f"중개 요청 거부({exc.code}) · 결과 파일 보존", flush=True)
            return 2
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            if not offline:
                print("서버 연결 끊김 · 새 동작 중단, 미전달 결과 보존", flush=True)
            offline = True
        time.sleep(args.interval)


if __name__ == "__main__":
    raise SystemExit(main())
