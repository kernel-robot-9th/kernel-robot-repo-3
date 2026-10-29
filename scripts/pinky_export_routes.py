"""Export registered field routes without opening ROS or robot devices."""
import argparse
import json
from pathlib import Path

from robots.pinky.field_routes import plan, network_plan
from robots.pinky.route_graph import build_graph, observation_arrival


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile', required=True)
    parser.add_argument('--routes', nargs='+', default=['home_to_A'])
    parser.add_argument('--network', action='store_true', help='공용 대기 자리와 구역 간 연결 사용')
    parser.add_argument('--output', default='runtime/field/pinky-route-server.json')
    args = parser.parse_args()
    profile = json.loads(Path(args.profile).read_text())
    planner = network_plan if args.network else plan
    observations = (json.loads(Path(profile['observation_goals_file']).read_text())
                    if profile.get('observation_goals_file') else {})
    plans = []
    for route in args.routes:
        selected = planner(profile['goals_file'], route)
        destination = route.rsplit('_to_', 1)[-1]
        zone = {'A':'A', 'B':'B', 'handoff':'C'}.get(destination)
        if zone and observations:
            observation = dict(observations[zone+'/P'+profile['robot_id'][-1]])
            observation['goal_forward_m'] += profile.get('observation_extra_reverse_m', {}).get(zone, 0.)
            selected = observation_arrival(selected, observation)
        if profile.get('wait_targets_file'):
            from robot_gateway.hardware.wait_parking import waiting_route
            selected = waiting_route(selected, 'P'+profile['robot_id'][-1],
                                     json.loads(Path(profile['wait_targets_file']).read_text()))
        plans.append(selected)
    graph, index = build_graph(plans)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    graph_file = output.with_suffix('.geojson')
    index['graph_file'] = str(graph_file)
    graph_file.write_text(json.dumps(graph, ensure_ascii=False)+'\n')
    output.write_text(json.dumps(index, ensure_ascii=False)+'\n')
    print(json.dumps({'index': str(output), 'graph': str(graph_file), 'routes': args.routes,
                      'features': len(graph['features'])}))


if __name__ == '__main__':
    main()
