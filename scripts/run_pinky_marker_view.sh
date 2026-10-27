#!/usr/bin/env bash
set -eo pipefail
cd "$(dirname "$0")/.."
export DISPLAY="${DISPLAY:-:0}"
export XAUTHORITY="${XAUTHORITY:-$(find /run/user/$(id -u) -maxdepth 1 -name '.mutter-Xwaylandauth.*' -print -quit)}"
exec /usr/bin/python3 -u -m scripts.pinky_marker_view "$@"
