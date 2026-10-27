#!/usr/bin/env bash
set -eo pipefail
cd "$(dirname "$0")/.."
source /opt/ros/jazzy/setup.bash
export PYTHONPATH="$PWD/runtime/pinky-ros-overlay/lib/python3.12/site-packages${PYTHONPATH:+:$PYTHONPATH}"
export LD_LIBRARY_PATH="$PWD/runtime/pinky-ros-overlay/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
set -a
source runtime/field/gateway-a.env
set +a
python="${PINKY_WORKER_PYTHON:-$HOME/dev_ws/omxtest/.venv-pick/bin/python}"
exec "$python" -m robot_gateway.hardware.worker --config "$SHOP_HARDWARE_CONFIG" --server "$SHOP_SERVER_URL" --execute
