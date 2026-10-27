#!/usr/bin/env bash
set -eo pipefail
if [ "${1:-}" = sync-clock ]; then
  sudo -v
  sudo timedatectl set-ntp false
  stamp=$(curl -sSI --connect-timeout 3 --max-time 5 http://192.168.0.11:8000/health \
    | sed -n 's/^[Dd]ate: //p' | tr -d '\r')
  sudo date -u -s "$stamp"
  exit
fi
export PINKY_DOMAIN_ID=2 PINKY_ROBOT_ID=pinky-2
export PINKY_MAP_FILE="$HOME/cartrina-field/maps/pinky_map_new.yaml"
exec bash "$HOME/cartrina-field/run_pinky_robot.sh" "$@"
