"""Run only on the Ubuntu target. Record actual exits, never assumed passes."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def source_digest():
    value = hashlib.sha256()
    paths = []
    for folder in ["server", "robot_gateway", "tests", "scripts", "web/src"]:
        paths.extend(p for p in (ROOT / folder).rglob("*") if p.is_file() and "__pycache__" not in p.parts)
    paths.extend(ROOT / p for p in ["pyproject.toml", "web/package.json", "web/vite.config.ts", "web/tsconfig.json"])
    for path in sorted(paths):
        value.update(str(path.relative_to(ROOT)).replace("\\", "/").encode())
        value.update(path.read_bytes())
    return value.hexdigest()


def main():
    if platform.system() != "Linux":
        raise SystemExit("이 검증은 Ubuntu 노트북에서 실행하세요. Windows 정적 검토와 구분합니다.")
    reports = ROOT / "reports"
    reports.mkdir(exist_ok=True)
    result = {"started_at": datetime.now(timezone.utc).isoformat(), "platform": platform.platform(),
              "python": platform.python_version(), "mode": "mock", "source_sha256": source_digest(),
              "physical_robot_verified": False, "checks": [], "status": "RUNNING"}
    checks = [("control_and_api_tests", [sys.executable, "-m", "pytest", "-q", "--junitxml=reports/junit.xml"], ROOT),
              ("typescript_and_web_build", ["pnpm", "run", "build"], ROOT / "web"),
              ("separate_process_http_demo", [sys.executable, "scripts/demo_ubuntu.py"], ROOT),
              ("three_gateway_http_demo", [sys.executable, "scripts/demo_distributed.py"], ROOT)]
    try:
        for name, command, cwd in checks:
            with (reports / f"{name}.log").open("w", encoding="utf-8") as log:
                try:
                    run = subprocess.run(command, cwd=cwd, stdout=log, stderr=subprocess.STDOUT, timeout=180)
                    code = run.returncode
                except (OSError, subprocess.TimeoutExpired) as exc:
                    log.write(str(exc))
                    code = 124
            result["checks"].append({"name": name, "exit_code": code, "log": f"{name}.log"})
            print(f"{name}: {'PASS' if code == 0 else 'FAIL'}", flush=True)
        with (reports / "python-packages.txt").open("w") as output:
            subprocess.run([sys.executable, "-m", "pip", "freeze"], stdout=output, timeout=30, check=True)
        with (reports / "node-version.txt").open("w") as output:
            subprocess.run(["node", "--version"], stdout=output, timeout=10, check=True)
        result["status"] = "PASS" if all(c["exit_code"] == 0 for c in result["checks"]) else "FAIL"
    finally:
        result["finished_at"] = datetime.now(timezone.utc).isoformat()
        (reports / "verification.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print("결과: reports/verification.json (실물 검증 아님)")
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
