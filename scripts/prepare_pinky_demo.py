"""Prepare demo overrides and route assets from local field files, without device I/O."""
import argparse
import json
from pathlib import Path

from robot_gateway.hardware.pinky import atomic_json
from robots.pinky import compact
from robots.pinky.field_routes import plan, registration


def prepare_central(directory='runtime/field/pinky-demo', preferred_robot='P1'):
    destination = Path(directory)
    profiles = {'pinky-1': 'runtime/field/pinky-mobile.json',
                'pinky-2': 'runtime/field/pinky-mobile-p2.json'}
    routes = {robot: json.loads(Path(location).read_text())['goals_file']
              for robot, location in profiles.items()}
    readiness = json.loads(Path('runtime/field/pinky-first-a.readiness.json').read_text())
    readiness['pinky_routes_files'] = routes
    readiness['preferred_robot'] = 'pinky-'+preferred_robot[-1]
    atomic_json(destination/'readiness.json', readiness)
    path = routes['pinky-1']
    registry, transform, signature = registration(path)
    tx, ty, yaw = transform
    import math
    def convert(p):
        x, y, a = p
        return [tx+math.cos(yaw)*x-math.sin(yaw)*y,
                ty+math.sin(yaw)*x+math.cos(yaw)*y,
                math.atan2(math.sin(a+yaw), math.cos(a+yaw))]
    raw = compact.bundle()[1]
    assets = {key: plan(path, key, taught_dock=False) for key in raw}
    assets.update({key: plan(path, key, taught_dock=False) for key in ('exit_A', 'exit_B')})
    waits = {slot: convert(compact.route('handoff_to_home_'+slot).poses[-1]) for slot in ('front','back')}
    atomic_json(destination/'routes.json', {'schema_version': 1, 'frame_id': registry['frame_id'],
                'registration_sha256': signature, 'routes': assets, 'waiting_spots': waits,
                'taught_parking_goals': {zone: goal['arrival'] for zone, goal in registry['goals'].items()},
                'route_server_active': False, 'physical_hardware_verified': False,
                'note': 'Existing v4 route geometry for Route Server integration; not a running graph or scheduler.'})
    return destination/'readiness.json'


def prepare(node='gateway-a', directory='runtime/field/pinky-demo'):
    source = Path('runtime/field') / (node+'.hardware.json')
    config = json.loads(source.read_text())
    config['state_directory'] = 'runtime/hardware/pinky-demo'
    if node == 'gateway-a':
        config['mobile_factory'] = 'robot_gateway.hardware.pinky:create_mobile'
        config['mobile_profiles'] = {'pinky-1': 'runtime/field/pinky-mobile.json',
                                     'pinky-2': 'runtime/field/pinky-mobile-p2.json'}
        config['parking'] = {'config': 'runtime/field/pinky-parking.json', 'zones': ['A']}
        parking = Path(config['parking']['config'])
        if not parking.exists():
            example = Path(__file__).resolve().parents[1]/'config/pinky-parking.example.json'
            atomic_json(parking, json.loads(example.read_text()))
    output = Path(directory)/(node+'.hardware.json')
    atomic_json(output, config)
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--node', choices=['gateway-a', 'gateway-b'], default='gateway-a')
    parser.add_argument('--output-directory', default='runtime/field/pinky-demo')
    parser.add_argument('--central', action='store_true')
    parser.add_argument('--preferred-robot', choices=['P1','P2'], default='P1')
    args = parser.parse_args()
    print(prepare_central(args.output_directory, args.preferred_robot) if args.central else prepare(args.node, args.output_directory))


if __name__ == '__main__':
    main()
