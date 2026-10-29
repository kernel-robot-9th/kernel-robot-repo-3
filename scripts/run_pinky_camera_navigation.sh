#!/usr/bin/env bash
set -eo pipefail
cd "$(dirname "$0")/.."
export DISPLAY="${DISPLAY:-:0}"
if [ -z "${XAUTHORITY:-}" ]; then
  export XAUTHORITY="$(find /run/user/$(id -u) -maxdepth 1 -name '.mutter-Xwaylandauth.*' -print -quit)"
fi
exec /usr/bin/python3 -u -m scripts.pinky_camera_navigation "$@"
