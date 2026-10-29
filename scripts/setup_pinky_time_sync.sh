#!/usr/bin/env bash
# 관제 터미널에서 실행. sudo 암호는 각 장비의 터미널에 직접 입력한다.
set -euo pipefail

case "${1:-all}" in
  server)
    apt-get install -y chrony
    mkdir -p /etc/chrony/conf.d
    if ! grep -Eq '^[[:space:]]*confdir[[:space:]]+/etc/chrony/conf.d([[:space:]]|$)' /etc/chrony/chrony.conf; then
      printf '\nconfdir /etc/chrony/conf.d\n' >> /etc/chrony/chrony.conf
    fi
    cat > /etc/chrony/conf.d/cartrina-field.conf <<'EOF'
# 인터넷이 없을 때도 관제 시각을 현장 공통 기준으로 사용한다.
local stratum 10
allow 192.168.0.16
allow 192.168.0.17
EOF
    if command -v ufw >/dev/null && ufw status | grep -q '^Status: active'; then
      ufw allow from 192.168.0.16 to 192.168.0.11 port 123 proto udp
      ufw allow from 192.168.0.17 to 192.168.0.11 port 123 proto udp
    fi
    systemctl enable chrony
    systemctl restart chrony
    chronyc tracking
    ;;
  client)
    mkdir -p /etc/systemd/timesyncd.conf.d
    cat > /etc/systemd/timesyncd.conf.d/90-cartrina-field.conf <<'EOF'
[Time]
NTP=
NTP=192.168.0.11
FallbackNTP=
PollIntervalMinSec=16
PollIntervalMaxSec=64
EOF
    systemctl enable systemd-timesyncd
    timedatectl set-ntp true
    systemctl restart systemd-timesyncd
    echo '자동 동기화 설정 완료. 서버 응답 후 시각이 보정됩니다.'
    ;;
  all)
    script=$(readlink -f "$0")
    key=/home/noma/.ssh/cartrina_field_ed25519
    echo '관제 시간 서버 설정 — 관제 sudo 암호 입력'
    sudo bash "$script" server
    for address in 192.168.0.16 192.168.0.17; do
      scp -q -i "$key" -o BatchMode=yes -o ConnectTimeout=5 \
        "$script" "pinky@$address:cartrina-field/setup_pinky_time_sync.sh"
      echo "$address 자동 동기화 설정 — 해당 Pinky sudo 암호 입력"
      ssh -t -i "$key" -o BatchMode=yes -o ConnectTimeout=5 "pinky@$address" \
        'sudo bash "$HOME/cartrina-field/setup_pinky_time_sync.sh" client'
    done
    echo '설정 완료. 확인: bash scripts/setup_pinky_time_sync.sh status'
    ;;
  status)
    date -u
    systemctl is-active chrony
    for address in 192.168.0.16 192.168.0.17; do
      echo "$address"
      ssh -i /home/noma/.ssh/cartrina_field_ed25519 -o BatchMode=yes -o ConnectTimeout=5 "pinky@$address" \
        'date -u; timedatectl show -p NTP -p NTPSynchronized; timedatectl timesync-status --no-pager'
    done
    ;;
  *) echo '사용: bash scripts/setup_pinky_time_sync.sh [all|status]' >&2; exit 2 ;;
esac
