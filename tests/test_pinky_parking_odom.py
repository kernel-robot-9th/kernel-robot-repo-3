"""Metric lever-arm transform and parking with intermittent camera observations."""
import math
import unittest

import numpy as np

from robot_gateway.hardware.aruco_parking import OdomParking, camera_odom_goal, rotate, wrap


TARGET = {'corners': [[300, 300], [400, 300], [400, 400], [300, 400]], 'forward_yaw': .25}
GEOMETRY = {'marker_size_mm': 25., 'base_to_marker_mm': [12., -7.]}
CONTROL = {'position_tolerance_mm': 5., 'yaw_tolerance_deg': 2.,
           'virtual_goal_offset_mm': 25., 'linear_speed_mps': .02,
           'angular_speed_rps': .3, 'heading_gain': 1.2}


def marker_at(pose):
    """Project an independently constructed rigid base+marker into the taught image."""
    offset = rotate(.012, -.007, pose['yaw'])
    cx, cy = pose['x']+offset[0], pose['y']+offset[1]
    corners = []
    for x, y in [(-.0125, .0125), (.0125, .0125), (.0125, -.0125), (-.0125, -.0125)]:
        x, y = rotate(x, y, pose['yaw']-TARGET['forward_yaw'])
        corners.append([350+4000*(cx+x), 350-4000*(cy+y)])
    return {'corners': corners}


def odom_at(pose, drift=(0., 0.)):
    x, y = rotate(pose['x'], pose['y'], .8)
    return {'pose': {'x': 1.1+x+drift[0], 'y': -.4+y+drift[1], 'yaw': wrap(pose['yaw']+.8)},
            'frame_id': 'odom', 'base_frame': 'base_footprint', 'observed_at': 1.}


def true_goal():
    x, y = rotate(-.012, .007, TARGET['forward_yaw'])
    return {'x': x, 'y': y, 'yaw': TARGET['forward_yaw']}


class OdomParkingTest(unittest.TestCase):
    def test_arrival_at_observation_starts_without_another_retreat(self):
        pose = {'x':.05, 'y':.01, 'yaw':.3}
        controller = OdomParking(TARGET, GEOMETRY, CONTROL, {'retreat_m':.07},
                                 start_at_observation=True)
        now = controller.phase_since+.3
        waiting = controller.update(odom_at(pose), now=now)
        self.assertEqual(waiting['parking_phase'], 'observe')
        self.assertEqual(waiting['command']['linear'], 0.)
        observed = controller.update(odom_at(pose), marker_at(pose), now=now+.1)
        self.assertEqual(observed['parking_phase'], 'advance')
        self.assertEqual(observed['command']['linear'], 0.)

    def test_metric_target_with_rotated_frames_and_nonzero_marker_offset(self):
        pose = {'x': .08, 'y': .02, 'yaw': .95}
        goal = camera_odom_goal(TARGET, marker_at(pose), GEOMETRY, odom_at(pose)['pose'])
        expected = odom_at(true_goal())['pose']
        np.testing.assert_allclose(list(goal.values()), list(expected.values()), atol=1e-7)

    def test_staged_reverse_observe_advance_converges_without_camera_during_motion(self):
        goal = true_goal()
        for dx, dy, angle in [(.005, .004, .08), (-.005, -.004, -.1), (.01, .008, .15)]:
            with self.subTest(offset=(dx, dy, angle)):
                pose = {'x': goal['x']+dx, 'y': goal['y']+dy, 'yaw': goal['yaw']+angle}
                controller = OdomParking(TARGET, GEOMETRY, CONTROL, {'retreat_m': .07})
                phases, commands = set(), []
                for step in range(40000):
                    phase = controller.phase
                    marker = marker_at(pose) if phase == 'observe' else None
                    state = controller.update(odom_at(pose), marker, now=step*.05)
                    phases.add(state['parking_phase'])
                    command = state['command']
                    commands.append((phase, command['linear'], command['angular']))
                    if command['aligned']:
                        break
                    pose['x'] += command['linear']*math.cos(pose['yaw'])*.05
                    pose['y'] += command['linear']*math.sin(pose['yaw'])*.05
                    pose['yaw'] = wrap(pose['yaw']+command['angular']*.05)
                self.assertTrue(command['aligned'], (state, pose))
                self.assertTrue({'reverse_observe', 'observe', 'advance', 'verify', 'aligned'} <= phases)
                self.assertTrue(any(v < 0 for phase, v, w in commands if phase == 'reverse_observe'))
                self.assertTrue(all(v >= 0 for phase, v, w in commands if phase == 'advance'))
                self.assertTrue(all(v == -.02 for phase, v, w in commands if phase == 'reverse_observe' and v))
                self.assertLessEqual(math.hypot(pose['x']-goal['x'], pose['y']-goal['y']), .005)
                self.assertLess(abs(wrap(pose['yaw']-goal['yaw'])), math.radians(2.1))
                self.assertEqual(state['verification_source'], 'odom')

    def test_reverse_does_not_stall_at_previous_1_3_mm_remaining(self):
        controller = OdomParking(TARGET, GEOMETRY, CONTROL, {'retreat_m': .095817})
        pose = {'pose': {'x': 0., 'y': 0., 'yaw': 0.}}
        controller.update(pose, now=0.)
        pose['pose']['x'] = -(.095817-.001324)
        state = controller.update(pose, now=600.)
        self.assertEqual(state['command']['linear'], -.02)
        self.assertEqual(state['parking_phase'], 'reverse_observe')
        pose['pose']['x'] = -.096
        state = controller.update(pose, now=600.1)
        self.assertEqual(state['command']['linear'], 0.)
        self.assertEqual(state['parking_phase'], 'observe')

    def test_camera_jitter_cannot_move_goal_during_advance(self):
        pose = {'x': .03, 'y': -.02, 'yaw': .7}
        controller = OdomParking(TARGET, GEOMETRY, CONTROL, {'retreat_m': .07})
        controller.phase = 'observe'
        controller.phase_since = 0.
        first = controller.update(odom_at(pose), marker_at(pose), now=1.)
        controller.phase = 'advance'
        jittered = marker_at({'x': pose['x']+.02, 'y': pose['y']-.01, 'yaw': pose['yaw']+.4})
        during = controller.update(odom_at(pose), jittered, now=2.)
        self.assertEqual(first['odom_goal'], during['odom_goal'])
        self.assertGreaterEqual(during['command']['linear'], 0.)

    def test_camera_reacquisition_corrects_goal_only_at_stationary_observation(self):
        pose = {'x': .03, 'y': -.02, 'yaw': .7}
        controller = OdomParking(TARGET, GEOMETRY, CONTROL, {'retreat_m': .07})
        controller.phase, controller.phase_since = 'observe', 0.
        first = controller.update(odom_at(pose), marker_at(pose), now=1.)
        controller.phase = 'observe'
        corrected = controller.update(odom_at(pose, (.02, -.01)), marker_at(pose), now=2.)
        self.assertEqual(corrected['control_source'], 'camera+odom')
        for key, drift in [('x', .02), ('y', -.01)]:
            self.assertAlmostEqual(corrected['odom_goal'][key]-first['odom_goal'][key], drift)
        self.assertEqual(corrected['command']['linear'], 0.)
        self.assertEqual(corrected['command']['angular'], 0.)

    def test_camera_shortfall_after_odom_arrival_resumes_forward_without_retreat(self):
        goal = true_goal()
        yaw = goal['yaw']-math.radians(.83)
        dx, dy = rotate(-.00986, .00085, yaw)
        pose = {'x': goal['x']+dx, 'y': goal['y']+dy, 'yaw': yaw}
        controller = OdomParking(TARGET, GEOMETRY, CONTROL, {'retreat_m': .095817})
        old_dx, old_dy = rotate(.00238, 0., yaw)
        old_goal = {'x': pose['x']+old_dx, 'y': pose['y']+old_dy, 'yaw': goal['yaw']}
        controller.goal, controller.phase = odom_at(old_goal)['pose'], 'advance'
        stopped = controller.update(odom_at(pose), now=1.)
        self.assertEqual(stopped['parking_phase'], 'verify')
        corrected = controller.update(odom_at(pose), marker_at(pose), now=1.5)
        self.assertEqual(corrected['parking_phase'], 'advance')
        self.assertAlmostEqual(corrected['error']['forward_error_mm'], 9.86, places=3)
        resumed = controller.update(odom_at(pose), now=1.6)
        self.assertGreater(resumed['command']['linear'], 0.)
        self.assertEqual(corrected['odom_goal'], resumed['odom_goal'])
        reached = controller.update(odom_at(goal), now=2.)
        self.assertEqual(reached['parking_phase'], 'verify')
        verified = controller.update(odom_at(goal), marker_at(goal), now=2.5)
        self.assertTrue(verified['command']['aligned'])

    def test_small_lateral_error_turns_in_place_then_finishes_without_retreat(self):
        for distance, yaw_degrees in [(.00925, -4.59), (.001, 4.59)]:
            with self.subTest(distance=distance, yaw=yaw_degrees):
                goal = true_goal()
                yaw = goal['yaw']-math.radians(yaw_degrees)
                dx, dy = rotate(-distance, -.00068, yaw)
                pose = {'x': goal['x']+dx, 'y': goal['y']+dy, 'yaw': yaw}
                controller = OdomParking(TARGET, GEOMETRY, CONTROL, {'retreat_m': .095817})
                controller.goal, controller.phase = odom_at(goal)['pose'], 'verify'
                phases = set()
                for step in range(300):
                    phase = controller.phase
                    marker = marker_at(pose) if phase == 'verify' else None
                    state = controller.update(odom_at(pose), marker, now=1.+step*.05)
                    phases.add(state['parking_phase'])
                    command = state['command']
                    self.assertNotEqual(state['parking_phase'], 'reverse_observe')
                    self.assertGreaterEqual(command['linear'], 0.)
                    if phase == 'align_heading':
                        self.assertEqual(command['linear'], 0.)
                    if command['aligned']:
                        break
                    pose['x'] += command['linear']*math.cos(pose['yaw'])*.05
                    pose['y'] += command['linear']*math.sin(pose['yaw'])*.05
                    pose['yaw'] = wrap(pose['yaw']+command['angular']*.05)
                self.assertTrue(command['aligned'], state)
                self.assertIn('align_heading', phases)
                if distance > .005:
                    self.assertIn('advance', phases)

    def test_crossing_goal_plane_stops_and_retries_instead_of_orbiting(self):
        pose = true_goal()
        controller = OdomParking(TARGET, GEOMETRY, CONTROL, {'retreat_m': .07})
        controller.goal = odom_at(pose)['pose']
        controller.phase = 'advance'
        bad = odom_at({'x': pose['x']+.005, 'y': pose['y']+.03, 'yaw': pose['yaw']+.8})
        stopped = controller.update(bad, now=1.)
        self.assertEqual(stopped['parking_phase'], 'verify')
        self.assertEqual(stopped['command'], {'linear': 0., 'angular': 0., 'aligned': False})
        retry = controller.update(bad, now=1.5)
        self.assertEqual(retry['parking_phase'], 'reverse_observe')
        self.assertFalse(retry['command']['aligned'])
        moving_back = controller.update(bad, now=1.6)
        self.assertLess(moving_back['command']['linear'], 0.)


if __name__ == '__main__':
    unittest.main()
