#!/usr/bin/env bash
set -eo pipefail
cd "$(dirname "$0")/.."
source /opt/ros/jazzy/setup.bash
export PYTHONPATH="$PWD:$PWD/runtime/pinky-ros-overlay/lib/python3.12/site-packages${PYTHONPATH:+:$PYTHONPATH}"
export LD_LIBRARY_PATH="$PWD/runtime/pinky-ros-overlay/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
exec "$HOME/dev_ws/omxtest/.venv-pick/bin/python" -u -m scripts.pinky_parking "$@"
