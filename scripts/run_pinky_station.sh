#!/usr/bin/env bash
set -eo pipefail
cd "$(dirname "$0")/.."
source /opt/ros/jazzy/setup.bash
export PYTHONPATH="$PWD:$PWD/runtime/pinky-ros-overlay/lib/python3.12/site-packages${PYTHONPATH:+:$PYTHONPATH}"
export LD_LIBRARY_PATH="$PWD/runtime/pinky-ros-overlay/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export DISPLAY="${DISPLAY:-:0}"
export XAUTHORITY="${XAUTHORITY:-$(find /run/user/$(id -u) -maxdepth 1 -name '.mutter-Xwaylandauth.*' -print -quit)}"
exec "$1" -u -m scripts.pinky_station "$2"
