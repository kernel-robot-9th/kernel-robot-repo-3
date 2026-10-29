import numpy as np

from robot_gateway.hardware.overhead import project
from scripts.pinky_camera_drive_calibrate import corners_in_odom, evaluate, fit_samples


def test_recovers_perspective_and_mount_offset_at_withheld_pose():
    matrix = np.array([[-.001, .0001, 1], [.00005, .001, -.6], [.0001, .0002, 1.]])
    samples = []
    poses = [(0, 0, 0), (.3, 0, 0), (.3, .25, 1.5), (-.3, .25, 3),
             (-.3, -.2, 4.5), (.1, -.1, .7)]
    for i, (x, y, yaw) in enumerate(poses):
        sample = {'name': str(i), 'odom': dict(x=x, y=y, yaw=yaw)}
        sample['corners'] = project(corners_in_odom(sample, 3.12, [.008, -.005]),
                                    np.linalg.inv(matrix)).tolist()
        samples.append(sample)
    result = fit_samples(samples[:-1])
    check = evaluate(samples[-1], result)
    assert check['center_error_m'] < 1e-5
    np.testing.assert_allclose(check['side_lengths_m'], .08, atol=1e-5)
    np.testing.assert_allclose(result['base_to_marker_m'], [.008, -.005], atol=1e-5)
