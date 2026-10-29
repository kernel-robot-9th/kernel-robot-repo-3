#!/usr/bin/env bash
set -eo pipefail
cd "$(dirname "$0")/.."
source /opt/ros/jazzy/setup.bash
export PYTHONPATH="$PWD${PYTHONPATH:+:$PYTHONPATH}"
exec .venv/bin/python -u -m scripts.six_item_demo "$@"
