# Copyright (c) 2023 Alberto J. Tudela Roldán
# Modified 2026: Python adaptation, forward-only parking with fixed nominal speed.
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#     http://www.apache.org/licenses/LICENSE-2.0
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Nav2 1.3.12 SmoothControlLaw curvature, with v_min == v_max.

Source: https://github.com/ros-navigation/navigation2/tree/1.3.12/nav2_graceful_controller
The angular bound reduces linear speed to preserve the commanded curvature.
"""
import math


def docking_velocity(x, y, yaw, speed, angular_limit):
    """Target pose in the robot frame; return forward and angular velocity."""
    radius = math.hypot(x, y)
    if radius == 0:
        return 0., 0.
    delta = -math.atan2(y, x)
    phi = math.atan2(math.sin(yaw+delta), math.cos(yaw+delta))
    k_phi, k_delta = 3., 2.
    curvature = -(k_delta*(delta-math.atan(-k_phi*phi)) +
                  (1+k_phi/(1+(k_phi*phi)**2))*math.sin(delta))/radius
    angular = max(-angular_limit, min(angular_limit, curvature*speed))
    return (angular/curvature if curvature else speed), angular
