#!/usr/bin/env python3
"""집기 재시도 흐름: vla_run.py 를 최대 N 번 돌린다. 실패(잡기 실패·떨어뜨림·적재 실패)면 정리(--home) 뒤 카메라로 다시 찾아 다시 집는다.
물건을 못 찾음·안전검사·로봇 이상 등 '시도 기록이 안 남는 멈춤'은 재시도하지 않고 끝낸다(사람이 봐야 함).
트윈에는 pick/event 로 retry / gave_up / done 을 보낸다.

  python3 vla_test/pick_loop.py --object choco [--tries 3]
"""
import argparse, os, json, subprocess, sys, time
from pathlib import Path
import rclpy
from std_msgs.msg import String

HERE = Path(__file__).resolve().parent
RETRY_ON = ("grasp_failed", "dropped", "not_in_basket", "timeout")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--object", choices=["choco", "shrimp", "ramen"], required=True)
    ap.add_argument("--tries", type=int, default=3)
    ap.add_argument("--wait", type=float, default=10.0, help="정리 뒤 다시 찾기 전 대기(초)")
    a = ap.parse_args()
    rclpy.init(); node = rclpy.create_node("pick_loop", namespace="dsr01"); pub = node.create_publisher(String, "pick/event", 10)
    def emit(event, **kw):
        m = String(); m.data = json.dumps({"event": event, "object": a.object, "t": time.time(), **kw}, ensure_ascii=False); pub.publish(m)
        rclpy.spin_once(node, timeout_sec=0.05)
    time.sleep(1.0)
    run = [sys.executable, "-u", str(HERE / "vla_run.py"), "--object", a.object]
    history = []
    for k in range(1, a.tries + 1):
        emit("retry", attempt=k, tries=a.tries, history=history)
        print(f"\n===== 시도 {k}/{a.tries} =====", flush=True)
        for w in range(4):
            t0 = time.time()
            pr = subprocess.Popen(run + ["--cam-start", "--cam-assist"] + (["--cam-grasp"] if a.object == "shrimp" else []), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1,
                                  env=dict(os.environ, DEMO_FIRST="1" if k == 1 else "0"))   # 시연 낙하는 첫 시도에서만
            lines = []
            for ln in pr.stdout: print(ln, end="", flush=True); lines.append(ln)
            pr.wait()
            # 재시도 중 물건을 못 찾으면(사람이 아직 다시 놓는 중) 시도 횟수를 쓰지 않고 10초씩 최대 3번 더 기다린다 (10-21 현장에서 10초는 짧았음)
            if k > 1 and w < 3 and any("못 찾음" in x for x in lines):
                print(f"아직 물건이 안 보임 -> {a.wait:.0f}초 더 기다림 ({w + 1}/3)", flush=True)
                emit("waiting", seconds=a.wait, history=history); time.sleep(a.wait); continue
            break
        rec = None
        f = HERE / "twin" / "attempts.jsonl"
        if f.exists():
            last = json.loads(f.read_text().strip().splitlines()[-1])
            if last.get("t_start", 0) >= t0 - 1: rec = last
        if rec is None:
            print("시도 기록 없음(못 찾음·안전검사·로봇 이상으로 멈춤) -> 재시도하지 않고 끝. 터미널 메시지 확인", flush=True)
            why = next((x.split("멈춤:", 1)[1].strip() for x in reversed(lines) if "!!! 멈춤:" in x), "stopped without attempt record")
            emit("loop_end", reason=why, history=history); break
        out = rec["outcome"]; causes = rec.get("analysis", {}).get("en", [])
        history.append(f"#{k} {out}" + (f": {causes[0]}" if causes and out != "loaded" else ""))
        if out == "loaded":
            print(f"성공 (시도 {k})", flush=True); emit("done", attempt=k, history=history); break
        if out not in RETRY_ON:
            emit("loop_end", reason=out, history=history); break
        if k == a.tries:
            print(f"{a.tries}번 모두 실패 -> 포기", flush=True); emit("gave_up", attempt=k, history=history); break
        if out == "dropped":
            # 10-23: 떨어진 물건은 작업대 위에 있음 -> 정리·대기 없이 바로 다시 찾아 집는다 (팔은 이미 위로 빠져 있고 그리퍼는 열림)
            print("떨어뜨림 -> 바로 다시 찾아 집음", flush=True); continue
        print(f"실패({out}) -> 정리 후 다시 찾기", flush=True)
        r = subprocess.run(run + ["--home"])
        if r.returncode != 0:
            emit("loop_end", reason="home failed", history=history); break
        print(f"정리 끝 -> {a.wait:.0f}초 뒤 다시 찾음 (그동안 물건을 작업대에 다시 놓아도 됨)", flush=True)
        emit("waiting", seconds=a.wait, history=history); time.sleep(a.wait)
    node.destroy_node(); rclpy.shutdown()

if __name__ == "__main__":
    main()
