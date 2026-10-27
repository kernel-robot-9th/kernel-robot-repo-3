#!/usr/bin/env bash
# P1 field files live in ~/cartrina-field. Start only the selected setup phase.
set -eo pipefail
source /opt/ros/jazzy/setup.bash
source "$HOME/pinky_pro/install/local_setup.bash"
export ROS_DOMAIN_ID="${PINKY_DOMAIN_ID:-1}"
robot_id="${PINKY_ROBOT_ID:-pinky-1}"
number="${robot_id##*-}"
map_file="${PINKY_MAP_FILE:-$HOME/pinky_pro/pinky_map_new.yaml}"
root="$HOME/cartrina-field"
mkdir -p "$root/logs"
start_relay() {
    python3 - "$root" "$robot_id" "$ROS_DOMAIN_ID" <<'PY'
import os
from pathlib import Path
import signal
import subprocess
import sys
root, robot, domain = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
script = str(root/'pinky_drive_gate.py')
for entry in Path('/proc').iterdir():
    if not entry.name.isdigit():
        continue
    try:
        args = [x.decode(errors='replace') for x in (entry/'cmdline').read_bytes().split(b'\0') if x]
        if script in args:
            os.kill(int(entry.name), signal.SIGTERM)
    except (OSError, ValueError):
        pass
with (root/'logs/drive-gate.log').open('ab') as log:
    process = subprocess.Popen(['python3', script, '--robot-id', robot, '--domain-id', domain,
        '--output-topic', '/cartrina/p'+robot.split('-')[-1]+'/drive_cmd_vel'],
        stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
(root/'drive-gate.pid').write_text(str(process.pid)+'\n')
print(robot+' Nav2/영상 주차 명령 중계 기동. 이동 명령은 전송하지 않았습니다.')
PY
}
case "${1:-}" in
  relay)
    start_relay
    ;;
  localize)
    nohup ros2 launch "$root/bringup_field.launch.xml" >"$root/logs/bringup.log" 2>&1 </dev/null &
    echo "$!" >"$root/bringup.pid"
    start_relay
    nohup ros2 launch pinky_navigation localization_launch.xml use_composition:=False \
      map:="$map_file" params_file:="$root/nav2_basket.yaml" \
      >"$root/logs/localization.log" 2>&1 </dev/null &
    echo "$!" >"$root/localization.pid"
    echo "$robot_id 센서·지도 기동. RViz에서 현재 위치와 앞방향을 지정하세요."
    ;;
  navigation|restart-navigation)
    # Legacy nohup launches can ignore SIGINT. Find every navigation launch
    # and its children, including orphaned nodes using this exact config.
    python3 - "$root/nav2_basket.yaml" <<'PY'
import os
from pathlib import Path
import signal
import sys
import time

config = sys.argv[1]
processes = {}
for entry in Path('/proc').iterdir():
    if not entry.name.isdigit():
        continue
    try:
        args = [x.decode(errors='replace') for x in (entry/'cmdline').read_bytes().split(b'\0') if x]
        stat = (entry/'stat').read_text().rsplit(') ', 1)[1].split()
        processes[int(entry.name)] = (args, int(stat[1]))
    except (OSError, ValueError, IndexError):
        pass
targets = set()
nav_nodes = {
    '/opt/ros/jazzy/lib/nav2_controller/controller_server',
    '/opt/ros/jazzy/lib/nav2_planner/planner_server',
    '/opt/ros/jazzy/lib/nav2_behaviors/behavior_server',
    '/opt/ros/jazzy/lib/nav2_bt_navigator/bt_navigator',
    '/opt/ros/jazzy/lib/nav2_waypoint_follower/waypoint_follower',
    '/opt/ros/jazzy/lib/nav2_velocity_smoother/velocity_smoother',
    '/opt/ros/jazzy/lib/nav2_smoother/smoother_server',
}
for pid, (args, parent) in processes.items():
    launch = any(Path(arg).name == 'ros2' and args[i+1:i+4] ==
                 ['launch', 'pinky_navigation', 'navigation_launch.xml'] for i, arg in enumerate(args))
    node = bool(args and args[0] in nav_nodes and config in args)
    manager = bool(args and args[0] == '/opt/ros/jazzy/lib/nav2_lifecycle_manager/lifecycle_manager'
                   and '__node:=lifecycle_manager_navigation' in args)
    if launch or node or manager:
        targets.add(pid)
while True:
    children = {pid for pid, (_, parent) in processes.items() if parent in targets}
    if children <= targets:
        break
    targets |= children

def running(pid):
    try:
        return (Path('/proc')/str(pid)/'stat').read_text().rsplit(') ', 1)[1].split()[0] != 'Z'
    except (OSError, IndexError):
        return False

for pid in targets:
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
deadline = time.monotonic() + 5
while any(running(pid) for pid in targets) and time.monotonic() < deadline:
    time.sleep(.1)
for pid in targets:
    if running(pid):
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
print(f'기존 Nav2 실행 정리: {len(targets)}개 프로세스 (지도·센서·구동부 유지)', flush=True)
PY
    setsid nohup ros2 launch pinky_navigation navigation_launch.xml use_composition:=False \
      params_file:="$root/nav2_basket.yaml" \
      "lifecycle_nodes:=['controller_server','planner_server','behavior_server','bt_navigator','waypoint_follower','velocity_smoother']" \
      >"$root/logs/navigation.log" 2>&1 </dev/null &
    echo "$!" >"$root/navigation.pid"
    echo "$robot_id 관제 경로 실행부 기동. 이동 목표는 전송하지 않았습니다."
    ;;
  *) echo '사용: bash run_pinky_robot.sh relay|localize|navigation|restart-navigation' >&2; exit 2;;
esac
