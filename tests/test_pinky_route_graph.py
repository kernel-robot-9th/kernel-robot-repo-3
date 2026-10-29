import math
from types import SimpleNamespace as Obj
import unittest

from robots.pinky.route_graph import build_graph, directed_path, observation_arrival, departure_path, observation_heading, path_goal_checker


class RouteGraphTest(unittest.TestCase):
    def test_v3_all_station_and_return_transits_use_position_checker(self):
        from robots.pinky import catalog
        checked=set()
        for name in ('home_to_A','home_to_B','home_to_handoff','A_to_B','A_to_handoff',
                     'B_to_handoff','handoff_to_home_front','handoff_to_home_back'):
            for original in catalog.route(name).segments:
                segment=dict(name=original.name,direction=original.direction,poses=original.poses)
                if original.direction == 1:
                    self.assertEqual(path_goal_checker(segment,3),'observation_goal_checker')
                    checked.add(original.name)
                else:
                    self.assertEqual(path_goal_checker(segment,3),'general_goal_checker')
                self.assertEqual(path_goal_checker(segment,4),'general_goal_checker')
        self.assertTrue({'dock_leave','exit','road','entry'} <= checked)

    def test_transit_policy_keeps_dock_heading_and_camera_parking_separate(self):
        transit=dict(name='dock_leave',direction=1,poses=[[0,0,0],[1,0,.35]])
        dock=dict(name='dock_reverse',direction=-1,poses=[[1,0,0],[2,0,0]],
                  goal_checker_id='observation_goal_checker')
        segments=[transit,dict(name='align_turn',direction=0,poses=[[1,0,0]]),dock]
        result=observation_heading(segments)
        self.assertEqual([s['name'] for s in result],
                         ['dock_leave','align_turn','dock_reverse','observation_heading'])
        self.assertEqual(path_goal_checker(result[0],3),'observation_goal_checker')
        self.assertNotIn('goal_checker_id',transit)  # Request policy must not add a transit spin.
        self.assertEqual(path_goal_checker(result[2],3),'observation_goal_checker')
        camera=dict(name='waiting_back_curve',direction=1,camera_guided=True)
        self.assertEqual(path_goal_checker(camera,3),'general_goal_checker')

    def test_observation_position_and_heading_are_separate_without_changing_route(self):
        # The field failure reached within 5mm but retained a 175-degree heading error.
        goal = [.915586233, 1.003736973, 3.099638309]
        segments = [{'name':'home_to_dock', 'direction':-1,
                     'goal_checker_id':'observation_goal_checker', 'poses':[[0,0,0], goal]}]
        result = observation_heading(segments)
        self.assertEqual(len(segments), 1)
        self.assertIs(result[0], segments[0])
        self.assertEqual(result[-1], {'name':'observation_heading', 'direction':0, 'poses':[goal]})
        self.assertEqual(observation_heading(result), result)  # Never append a second spin.
        waiting = [{'name':'queue_advance', 'direction':1, 'poses':[[0,0,0], [0,1,0]]}]
        self.assertIs(observation_heading(waiting), waiting)

    def test_offset_departures_start_behind_robot_and_keep_existing_lane(self):
        # Two failed field starts, before rotation. The fixed start was 14cm away.
        start = [-.039589514, 1.084466249, -3.111759846]
        poses = [[start[0]-.005*i*math.cos(start[2]),
                  start[1]-.005*i*math.sin(start[2]), start[2]] for i in range(81)]
        original = [p[:] for p in poses]
        for x, y, yaw in [(.029, .962, -1.604), (.013, .958, -1.563)]:
            current = dict(x=x, y=y, yaw=yaw)
            aligned = departure_path(poses, current, align_heading=True)
            # Include a position/heading adjustment during the initial spin.
            for dx, dy, dyaw in [(0., 0., 0.), (.035, -.025, .04)]:
                actual = dict(x=x+dx, y=y+dy, yaw=aligned[0][2]+dyaw)
                path = departure_path(poses, actual)
                self.assertEqual(path[0][:2], [actual['x'], actual['y']])
                self.assertEqual(path[-21:], poses[60:])
                # RPP selects the velocity sign from the lookahead point's base-frame x.
                for lookahead in (.12, .20, .25):
                    carrot = next(p for p in path if math.dist(p[:2], path[0][:2]) >= lookahead)
                    rx = math.cos(actual['yaw'])*(carrot[0]-actual['x'])+math.sin(actual['yaw'])*(carrot[1]-actual['y'])
                    self.assertLess(rx, 0., 'departure must select reverse')
                self.assertLess(max(math.dist(a[:2], b[:2]) for a,b in zip(path,path[1:])), .006)
        self.assertEqual(poses, original)

    def test_observation_offset_uses_goal_axes_without_moving_parking_goal(self):
        for yaw in (0., math.pi/2, -3.1):
            original = {'route_id':'home_to_A', 'frame_id':'map', 'registration_sha256':'test',
                        'segments':[{'name':'home_to_dock', 'direction':-1,
                                     'poses':[[1., 2., yaw]]}]}
            changed = observation_arrival(original, {'goal_forward_m':.06, 'goal_left_m':-.01})
            end = changed['segments'][-1]['poses'][-1]
            dx, dy = 1.-end[0], 2.-end[1]
            self.assertAlmostEqual(math.cos(yaw)*dx+math.sin(yaw)*dy, .06)
            self.assertAlmostEqual(-math.sin(yaw)*dx+math.cos(yaw)*dy, -.01)
            self.assertEqual(original['segments'][0]['poses'], [[1., 2., yaw]])
            _, index = build_graph([changed])
            self.assertEqual(index['routes']['home_to_A']['parking_start'], 'observe')
            self.assertEqual(index['routes']['home_to_A']['segments'][-1]['goal_checker_id'],
                             'observation_goal_checker')

    def test_fixed_curve_and_spin_remain_directed_and_separate(self):
        segments = [
            {'name': 'spin', 'direction': 0, 'poses': [[0, 0, 0], [0, 0, math.pi]]},
            {'name': 'reverse', 'direction': -1, 'poses': [[0, 0, math.pi], [.1, .02, math.pi], [.2, 0, math.pi]]},
            {'name': 'dock', 'direction': -1, 'poses': [[.2, 0, math.pi], [.3, 0, math.pi]]}]
        graph, index = build_graph([{'route_id': 'home_to_A', 'frame_id': 'map',
                                    'registration_sha256': 'test', 'segments': segments}])
        nodes = {f['properties']['id']: f['geometry']['coordinates'] for f in graph['features']
                 if f['geometry']['type'] == 'Point'}
        edges = [f['properties'] for f in graph['features'] if f['geometry']['type'] == 'LineString']
        routed = index['routes']['home_to_A']['segments']
        self.assertEqual(routed[0], segments[0])
        self.assertEqual([nodes[i] for i in range(5)], [[0, 0], [.1, .02], [.2, 0], [.2, 0], [.3, 0]])
        self.assertEqual([(e['startid'], e['endid']) for e in edges], [(0, 1), (1, 2), (3, 4)])
        self.assertEqual([(s['start_id'], s['goal_id']) for s in routed[1:]], [(0, 2), (3, 4)])

    def test_route_server_travel_heading_is_reversed_for_body_heading(self):
        point = lambda x: Obj(pose=Obj(position=Obj(x=x, y=0.), orientation=Obj(x=0., y=0., z=0., w=1.)))
        path = Obj(poses=[point(0.), point(.1)])
        reverse = directed_path(path, -1, -3.)
        forward = directed_path(path, 1, .2)
        self.assertAlmostEqual(abs(reverse[0][2]), math.pi)
        self.assertEqual(reverse[-1][2], -3.)
        self.assertEqual(forward[0][2], 0.)
        self.assertEqual(forward[-1][2], .2)


if __name__ == '__main__':
    unittest.main()
