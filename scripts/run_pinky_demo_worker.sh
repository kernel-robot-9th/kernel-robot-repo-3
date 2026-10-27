#!/usr/bin/env bash
set -eo pipefail
cd "$(dirname "$0")/.."
node="${1:-gateway-a}"
case "$node" in gateway-a|gateway-b) ;; *) echo 'gateway-a 또는 gateway-b를 지정하세요.' >&2; exit 2;; esac
if [[ "$node" == gateway-a ]]; then
  source /opt/ros/jazzy/setup.bash
  export PYTHONPATH="$PWD/runtime/pinky-ros-overlay/lib/python3.12/site-packages${PYTHONPATH:+:$PYTHONPATH}"
  export LD_LIBRARY_PATH="$PWD/runtime/pinky-ros-overlay/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
fi
set -a
source "runtime/field/$node.env"
set +a
python="${PINKY_WORKER_PYTHON:-$HOME/dev_ws/omxtest/.venv-pick/bin/python}"
"$python" -m scripts.prepare_pinky_demo --node "$node"
exec "$python" -m robot_gateway.hardware.worker --config "runtime/field/pinky-demo/$node.hardware.json" --server "$SHOP_SERVER_URL" --execute
