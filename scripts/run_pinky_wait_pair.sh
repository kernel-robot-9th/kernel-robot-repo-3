#!/usr/bin/env bash
# Operator-run sequence: P1 to front, then P2 to back. No arm commands.
set -eo pipefail
cd "$(dirname "$0")/.."
bash scripts/run_pinky_control.sh wait --robot P1 --zone front
bash scripts/run_pinky_control.sh wait --robot P2 --zone back
