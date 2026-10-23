#!/bin/bash
# 로봇 작업 환경 한 번에 켜기 (2026-10-21, OMEN 재부팅 뒤 다시 띄우려고 만듦)
#   잠자기 금지(화면 세션) -> 드라이버 -> 그리퍼 노드(상태 읽기 평소 끔) -> 키오스크 서버 -> 디지털 트윈 노드·RViz -> 상주 추론 서버
#   ssh 로 실행해도 됨: bash ~/doosan_ws/vla_test/start_all.sh
set -u
W=~/doosan_ws; V=$W/vla_test; L=$V/kiosk/logs; mkdir -p $L
export DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/$(id -u)/bus
XW=$(ps -eo args | grep "^/usr/bin/Xwayland" | head -1)
export DISPLAY=$(echo "$XW" | awk '{print $2}'); export XAUTHORITY=$(echo "$XW" | grep -o "\-auth [^ ]*" | awk '{print $2}')
if [ -z "$DISPLAY" ]; then   # Xwayland 는 X 프로그램이 처음 붙을 때 뜬다 -> 로그인돼 있으면 :0 + mutter 인증 파일
  pgrep -x gnome-shell >/dev/null || { echo "화면 로그인 안 됨: OMEN 에 로그인부터"; exit 1; }
  export DISPLAY=:0; export XAUTHORITY=$(ls -t /run/user/$(id -u)/.mutter-Xwaylandauth.* 2>/dev/null | head -1)
fi
echo "화면 $DISPLAY"
ROS="source /opt/ros/jazzy/setup.bash; source $W/install/setup.bash; export ROS_DOMAIN_ID=77"
run() { setsid nohup bash -c "$ROS; exec $1" > "$2" 2>&1 < /dev/null & }
pgrep -f "gnome-session-inhibit --inhibit suspend:idle" >/dev/null || setsid nohup gnome-session-inhibit --inhibit suspend:idle --reason "doosan robot running" --inhibit-only > /tmp/inhibit.log 2>&1 < /dev/null &
pgrep -f "ros2 launch dsr_bringup2" >/dev/null || run "ros2 launch dsr_bringup2 dsr_bringup2_rviz.launch.py mode:=real host:=110.120.1.59 port:=12345 model:=e0509 name:=dsr01" /tmp/driver.log
for i in $(seq 1 45); do grep -q "activated joint_state_broadcaster" /tmp/driver.log 2>/dev/null && break; sleep 2; done
grep -q "activated joint_state_broadcaster" /tmp/driver.log || { echo "드라이버가 안 뜸: /tmp/driver.log 확인"; exit 1; }
echo "드라이버 OK"; sleep 2
# 10-22: 드라이버가 같이 띄우는 기본 RViz 는 트윈 RViz 와 겹쳐 그래픽 부하 -> 화면이 멈춤. 기본 RViz 만 끈다(드라이버는 계속 돈다)
pkill -f "dsr_description2/rviz/default.rviz" && echo "기본 RViz 끔"
pgrep -f "dsr_gripper/gripper_service" >/dev/null || run "ros2 run dsr_gripper gripper_service --ros-args -p state_rate:=2.0 -p state_on_start:=false -p state_idle_off:=300.0" /tmp/gripper.log
pgrep -f "vla_test/kiosk_server.py" >/dev/null || run "python3 -u $V/kiosk_server.py" $L/server.log
pgrep -f "twin/twin_node.py" >/dev/null || run "python3 -u $V/twin/twin_node.py" $V/twin/twin.log
pgrep -f "rviz2 -d $V/twin/twin.rviz" >/dev/null || run "rviz2 -d $V/twin/twin.rviz" $V/twin/rviz.log
pgrep -f "infer_server.py" >/dev/null || (cd $V && setsid nohup ~/venv/il/bin/python -u infer_server.py --preload \
  $V/train/20261020_1226_choco_auto_v2/smolvla/checkpoints/015000/pretrained_model \
  $V/train/20261019_1401_shrimp_auto_v2/smolvla/checkpoints/015000/pretrained_model \
  $V/train/20261021_1749_ramen_auto_v1/smolvla/checkpoints/015000/pretrained_model > $L/infer_server.log 2>&1 < /dev/null &)
sleep 15
echo "--- 상태"
for p in "gnome-session-inhibit" "ros2_control_node" "dsr_gripper/gripper_service" "kiosk_server.py" "twin_node.py" "rviz2 -d" "infer_server.py"; do
  printf "%-30s %s\n" "$p" "$(pgrep -f "$p" >/dev/null && echo 켜짐 || echo 꺼짐)"; done
tail -1 /tmp/gripper.log
