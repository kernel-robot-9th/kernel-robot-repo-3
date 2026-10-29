#!/usr/bin/env bash
# Run by the operator: deploy the prepared web build and restart the demo server.
set -eo pipefail
cd "$(dirname "$0")/.."
build="${1:-runtime/field/camera-web-build}"
test -f "$build/index.html"
mkdir -p web/dist
cp -a "$build/." web/dist/
python3 - <<'PY'
import os
from pathlib import Path
import signal
import time
root = Path.cwd()
targets = []
for entry in Path('/proc').iterdir():
    if not entry.name.isdigit():
        continue
    try:
        args = (entry/'cmdline').read_bytes().split(b'\0')
        if (entry/'cwd').resolve() == root and b'uvicorn' in args and b'server.api:create_app' in args and b'8000' in args:
            targets.append(int(entry.name))
    except (OSError, RuntimeError):
        pass
for pid in targets:
    os.kill(pid, signal.SIGTERM)
for pid in targets:
    while Path('/proc', str(pid)).exists():
        stat = Path('/proc', str(pid), 'stat')
        try:
            if stat.read_text().rsplit(') ', 1)[1].startswith('Z'):
                break
        except FileNotFoundError:
            break
        time.sleep(.1)
PY
nohup bash scripts/run_pinky_demo_server.sh >runtime/field/camera-server.log 2>&1 </dev/null &
echo "$!" >runtime/field/server.pid
echo '관제 서버 시작 요청 완료. http://192.168.0.11:8000/admin/pinky/movement'
