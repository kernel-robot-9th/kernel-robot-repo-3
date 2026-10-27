"""ComputeRoute and lifecycle queries only; no wheel, FollowPath or Spin commands."""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path

import rclpy
from rclpy.action import ActionClient
from rclpy.context import Context
from rclpy.executors import SingleThreadedExecutor
from rclpy.node import Node
from nav2_msgs.action import ComputeRoute
from lifecycle_msgs.srv import GetState


def check(domain):
    control = json.loads(Path('runtime/field/pinky-control.json').read_text())
    profile = json.loads(Path(control['profiles']['P'+str(domain)]).read_text())
    routes = json.loads(Path(profile['route_index_file']).read_text())['routes']
    context = Context(); context.init(domain_id=domain)
    node = Node('central_route_check_p'+str(domain), context=context)
    executor = SingleThreadedExecutor(context=context); executor.add_node(node)
    client = ActionClient(node, ComputeRoute, '/compute_route')
    report = dict(domain=domain, routes=len(routes), segments=0, motion_command_sent=False)
    def wait(future):
        executor.spin_until_future_complete(future, timeout_sec=8)
        if not future.done(): raise RuntimeError('경로 조회 응답 없음')
        return future.result()
    try:
        if not client.wait_for_server(timeout_sec=8): raise RuntimeError('Route Server 발견 안 됨')
        for name, route in routes.items():
            for segment in route['segments']:
                if segment['direction'] == 0: continue
                goal = ComputeRoute.Goal(); goal.use_poses = False
                goal.start_id, goal.goal_id = segment['start_id'], segment['goal_id']
                accepted = wait(client.send_goal_async(goal))
                if not accepted.accepted: raise RuntimeError(name+' 거부')
                result = wait(accepted.get_result_async())
                if result.status != 4 or result.result.error_code or not result.result.path.poses:
                    raise RuntimeError(name+' 실패 '+str(result.result.error_code))
                for actual, expected in [(result.result.path.poses[0].pose.position, segment['poses'][0]),
                                         (result.result.path.poses[-1].pose.position, segment['poses'][-1])]:
                    if abs(actual.x-expected[0])+abs(actual.y-expected[1]) > 1e-5:
                        raise RuntimeError(name+' 끝점 다름')
                report['segments'] += 1
        report['states'] = {}
        for name in ['route_server','controller_server','amcl','map_server']:
            service = node.create_client(GetState, '/'+name+'/get_state')
            report['states'][name] = (wait(service.call_async(GetState.Request())).current_state.label
                                      if service.wait_for_service(timeout_sec=2) else 'not_discovered')
        return report
    finally:
        executor.shutdown(); node.destroy_node(); context.shutdown()


if __name__ == '__main__':
    with ThreadPoolExecutor(max_workers=2) as pool: reports = list(pool.map(check, [1,2]))
    Path('runtime/field/pinky-two-robot-route-check.json').write_text(json.dumps(reports, indent=2)+'\n')
    for report in reports: print(json.dumps(report))
