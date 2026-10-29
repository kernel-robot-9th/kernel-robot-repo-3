#!/usr/bin/env bash
set -eo pipefail
cd "$(dirname "$0")/.."
exec /usr/bin/python3 -u -m scripts.field_video "${1:-start}"
