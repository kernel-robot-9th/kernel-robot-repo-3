#!/usr/bin/env bash
# 시나리오용 낙하: bash demo_drop.sh choco|shrimp|ramen  -> 끌 때까지 그 물건 주문마다 첫 시도에서 떨어뜨리고, 바로 다시 집음
# 끄기: bash demo_drop.sh off
cd /home/omen/doosan_ws/vla_test
if [ "${1:-}" = "off" ]; then rm -f demo_drop.json; echo "꺼짐"; else echo "{\"object\": \"$1\"}" > demo_drop.json; echo "켜짐: $1 (끌 때까지)"; fi
