#!/usr/bin/env python3
"""성공률·소요 시간 정리 (2026-10-22). twin/attempts.jsonl 중 measure_t0.txt 이후 시도를 상품 1개(=재시도 묶음) 단위로 묶는다.
사용: python3 measure_report.py [--t0 epoch] [--md out.md]"""
import argparse, json, math, statistics, time
from pathlib import Path

HERE = Path(__file__).resolve().parent
NAMES = {"shrimp": "새우깡", "choco": "초코송이", "ramen": "컵라면"}
CELLS = {int(k): v[:2] for k, v in json.loads((HERE / "shrimp_cells.json").read_text()).items()}


def cell_of(xy):
    if not xy: return "?"
    c, d = min(((c, math.hypot(xy[0] - p[0], xy[1] - p[1])) for c, p in CELLS.items()), key=lambda t: t[1])
    return str(c) if d < 100.0 else f"({xy[0]:.0f},{xy[1]:.0f})"


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--t0", type=float); ap.add_argument("--md")
    a = ap.parse_args()
    t0 = a.t0 or float((HERE / "measure_t0.txt").read_text())
    recs = [json.loads(l) for l in (HERE / "twin" / "attempts.jsonl").read_text().splitlines() if l.strip()]
    recs = sorted([r for r in recs if r.get("t_start", 0) >= t0 and not r.get("force_test")], key=lambda r: r["t_start"])
    units, cur = [], None
    for r in recs:
        new = (cur is None or cur["object"] != r["object"] or cur["attempts"][-1].get("outcome") == "loaded"
               or len(cur["attempts"]) >= 3 or r["t_start"] - cur["attempts"][-1].get("t_end", r["t_start"]) > 120.0)
        if new: cur = {"object": r["object"], "attempts": []}; units.append(cur)
        cur["attempts"].append(r)
    lines = [f"# 성공률 측정 ({time.strftime('%Y-%m-%d %H:%M', time.localtime(t0))} 이후)", "",
             "| # | 상품 | 칸 | 결과 | 시도 | 소요(초) | 실패 원인 |", "|---|---|---|---|---|---|---|"]
    stat = {}
    for i, u in enumerate(units, 1):
        at = u["attempts"]; ok = at[-1].get("outcome") == "loaded"
        dur = (at[-1].get("t_end") or at[-1]["t_start"]) - at[0]["t_start"]
        fails = [x.get("outcome") for x in at if x.get("outcome") != "loaded"]
        s = stat.setdefault(u["object"], {"n": 0, "ok": 0, "first": 0, "dur": [], "tries": []})
        s["n"] += 1; s["ok"] += ok; s["first"] += ok and len(at) == 1; s["tries"].append(len(at))
        if ok: s["dur"].append(dur)
        lines.append(f"| {i} | {NAMES.get(u['object'], u['object'])} | {cell_of(at[0].get('cam_xy'))} | {'성공' if ok else '실패'} | {len(at)} | {dur:.0f} | {', '.join(fails) or '-'} |")
    lines += ["", "| 상품 | 개수 | 최종 성공 | 한 번에 성공 | 평균 시도 | 성공 시 평균 소요(초) |", "|---|---|---|---|---|---|"]
    tot = {"n": 0, "ok": 0, "first": 0}
    for o, s in stat.items():
        for k in tot: tot[k] += s[k]
        lines.append(f"| {NAMES.get(o, o)} | {s['n']} | {s['ok']}/{s['n']} ({100 * s['ok'] / s['n']:.0f}%) | {s['first']}/{s['n']} ({100 * s['first'] / s['n']:.0f}%) | "
                     f"{statistics.mean(s['tries']):.2f} | {statistics.mean(s['dur']):.0f} |" if s["dur"] else
                     f"| {NAMES.get(o, o)} | {s['n']} | 0/{s['n']} | 0/{s['n']} | {statistics.mean(s['tries']):.2f} | - |")
    if tot["n"]:
        lines.append(f"| **전체** | {tot['n']} | {tot['ok']}/{tot['n']} ({100 * tot['ok'] / tot['n']:.0f}%) | {tot['first']}/{tot['n']} ({100 * tot['first'] / tot['n']:.0f}%) | | |")
    lines += ["", "※ 시도 기록이 없는 멈춤(못 찾음·안전검사·로봇 이상)은 이 표에 안 나옴 -> 따로 적음"]
    out = "\n".join(lines); print(out)
    if a.md: Path(a.md).write_text(out + "\n")


if __name__ == "__main__":
    main()
