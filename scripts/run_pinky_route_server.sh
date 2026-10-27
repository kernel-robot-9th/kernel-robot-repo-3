#!/usr/bin/env bash
# ComputeRoute only: this server does not publish wheel commands.
set -eo pipefail
source /opt/ros/jazzy/setup.bash
export ROS_DOMAIN_ID="${PINKY_DOMAIN_ID:-2}"
root="$HOME/cartrina-field"
mkdir -p "$root/logs"
if ! { [ -f "$root/route-server.pid" ] && kill -0 "$(cat "$root/route-server.pid")" 2>/dev/null; }; then
  nohup ros2 run nav2_route route_server --ros-args --params-file "$root/route_server.yaml" \
    >"$root/logs/route-server.log" 2>&1 </dev/null &
  echo "$!" >"$root/route-server.pid"
fi
python3 - "${1:-}" <<'PY'
import sys
import rclpy
from rclpy.node import Node
from lifecycle_msgs.srv import GetState, ChangeState
rclpy.init()
node = Node('pinky_start_route_server')
def call(kind, suffix, request):
    client = node.create_client(kind, '/route_server/'+suffix)
    if not client.wait_for_service(timeout_sec=10):
        raise RuntimeError('Route Server 시작 실패: logs/route-server.log 확인')
    future = client.call_async(request)
    rclpy.spin_until_future_complete(node, future, timeout_sec=10)
    if not future.done():
        raise RuntimeError('Route Server 초기화 응답 없음')
    return future.result()
state = call(GetState, 'get_state', GetState.Request()).current_state.id
transitions = ([(3, 4), (2, 2)] if sys.argv[1] == 'reload' else []) + [(1, 1), (2, 3)]
for required, transition in transitions:
    if state == required:
        request = ChangeState.Request()
        request.transition.id = transition
        if not call(ChangeState, 'change_state', request).success:
            raise RuntimeError('Route Server 초기화 실패: logs/route-server.log 확인')
        state = call(GetState, 'get_state', GetState.Request()).current_state.id
print('Route Server 상태:', state, '(3=active)')
node.destroy_node()
rclpy.shutdown()
if state != 3:
    raise SystemExit(1)
PY
