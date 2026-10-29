"""Explicit Nav2 field adapter. Importing this module never opens ROS or motors."""
import hashlib
import json
import math
from pathlib import Path
import threading
import time


def map_signature(message):
    info = message.info
    origin = info.origin
    metadata = [info.width, info.height, info.resolution,
                origin.position.x, origin.position.y, origin.position.z,
                origin.orientation.x, origin.orientation.y, origin.orientation.z, origin.orientation.w]
    digest = hashlib.sha256(json.dumps(metadata, separators=(',', ':')).encode())
    digest.update(bytes((value + 1) for value in message.data))
    return digest.hexdigest()


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(path)


def pose_values(pose):
    q = pose.orientation
    if not all(math.isfinite(v) for v in (pose.position.x, pose.position.y, q.x, q.y, q.z, q.w)):
        raise ValueError('non-finite pose')
    return {'x': pose.position.x, 'y': pose.position.y,
            'yaw': math.atan2(2*(q.w*q.z + q.x*q.y), 1-2*(q.y*q.y + q.z*q.z))}


def load_profile(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


class PinkyMobile:
    """One ROS domain per instance; Nav2 owns motion execution results."""
    def __init__(self, profile, evidence=None):
        import rclpy
        from rclpy.action import ActionClient
        from rclpy.context import Context
        from rclpy.executors import SingleThreadedExecutor
        from rclpy.node import Node
        from rclpy.qos import QoSProfile, DurabilityPolicy, ReliabilityPolicy, qos_profile_sensor_data
        from nav2_msgs.action import ComputePathToPose, FollowPath, Spin
        from nav_msgs.msg import OccupancyGrid, Odometry
        from tf2_ros import Buffer, TransformListener
        self.profile, self.rclpy = profile, rclpy
        self.context = Context()
        self.context.init(args=[], domain_id=profile['domain_id'])
        self.node = Node('cartrina_' + profile['robot_id'].replace('-', '_'), context=self.context)
        self.executor = SingleThreadedExecutor(context=self.context)
        self.executor.add_node(self.node)
        self.buffer = Buffer()
        self.listener = TransformListener(self.buffer, self.node)
        self.map, self.map_hash, self.last_odom = None, None, None
        self.handle, self.pending_goal = None, None
        self.motion_lock, self.data_lock = threading.Lock(), threading.Lock()
        latched = QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL,
                             reliability=ReliabilityPolicy.RELIABLE)
        self.subscriptions = [
            self.node.create_subscription(OccupancyGrid, profile['map_topic'], self._map, latched),
            self.node.create_subscription(Odometry, profile['odom_topic'], self._odom, qos_profile_sensor_data)]
        self.action = ActionClient(self.node, FollowPath, profile['action_name'])
        self.spin_action = ActionClient(self.node, Spin, profile['spin_action_name'])
        self.action_type, self.spin_type = FollowPath, Spin
        self.planner_action = ActionClient(self.node, ComputePathToPose, '/compute_path_to_pose')
        self.planner_type = ComputePathToPose
        if profile.get('camera_socket'):
            from geometry_msgs.msg import PoseWithCovarianceStamped
            self.camera_initial_pose = self.node.create_publisher(
                PoseWithCovarianceStamped, '/initialpose', latched)
        self.route_index = {}
        self.route_graph_hash = None
        if profile.get('route_index_file'):
            from nav2_msgs.action import ComputeRoute
            index = json.loads(Path(profile['route_index_file']).read_text())
            self.route_index = index['routes']
            self.route_graph_hash = index.get('graph_sha256')
            self.route_type = ComputeRoute
            self.route_action = ActionClient(self.node, ComputeRoute, '/compute_route')
        self.thread = threading.Thread(target=self.executor.spin, daemon=True)
        self.thread.start()

    def _map(self, message):
        with self.data_lock:
            self.map, self.map_hash = message, map_signature(message)

    def _odom(self, message):
        with self.data_lock:
            self.last_odom = message

    def snapshot(self, *, wait_for_tf=False, cancelled=None, include_odometry=False):
        with self.data_lock:
            odom, signature = self.last_odom, self.map_hash
        try:
            frames = (self.profile['frame_id'], self.profile['base_frame'], self.rclpy.time.Time())
            if wait_for_tf:
                transform = self._await(self.buffer.wait_for_transform_async(*frames), cancelled)
            else:
                transform = self.buffer.lookup_transform(*frames)
        except Exception as exc:
            raise RuntimeError('Pinky map 변환 수신 대기: ' + str(exc)[:120]) from exc
        at = transform.header.stamp.sec + transform.header.stamp.nanosec / 1e9
        t = transform.transform
        pose = type('Pose', (), {'position': t.translation, 'orientation': t.rotation})()
        values = pose_values(pose)
        twist = odom.twist.twist if odom else None
        result = {'pose': values, 'observed_at': at, 'map_sha256': signature,
                  'velocity': {'linear': twist.linear.x, 'angular': twist.angular.z} if twist else None}
        if include_odometry:
            # Compare transforms at the map pose's timestamp, not a newer odom message.
            stamp = self.rclpy.time.Time.from_msg(transform.header.stamp)
            odom_frame = odom.header.frame_id if odom else self.profile.get('odom_frame', 'odom')
            try:
                for key, parent, child in [('odom_pose', odom_frame, self.profile['base_frame']),
                                           ('map_to_odom', self.profile['frame_id'], odom_frame)]:
                    t = self.buffer.lookup_transform(parent, child, stamp).transform
                    result[key] = pose_values(type('Pose', (), {'position': t.translation,
                                                               'orientation': t.rotation})())
            except Exception as exc:
                result['odometry_error'] = str(exc)[:160]
            if odom:
                result['velocity_observed_at'] = odom.header.stamp.sec+odom.header.stamp.nanosec/1e9
        return result

    def inspect(self):
        try:
            observation = self.snapshot()
            subscribers = [p.node_name for p in self.node.get_subscriptions_info_by_topic(
                self.profile['base_command_topic'])]
            return {'connected': self.action.server_is_ready(), 'observation': observation,
                    'base_command_connected': self.profile.get('base_node', 'pinky_bringup') in subscribers}
        except Exception as exc:
            return {'connected': False, 'error': str(exc)[:200]}

    def correct_from_camera(self, cancelled=None):
        if not self.profile.get('camera_socket'):
            return {'published': False, 'reason': '카메라 보정 미설정'}
        from .camera_navigation import correct_mobile
        value = correct_mobile(self, cancelled)
        print('카메라 위치 보정: '+json.dumps(value, ensure_ascii=False), flush=True)
        return value

    @staticmethod
    def _await(future, cancelled=None, timeout=None):
        deadline = time.monotonic()+timeout if timeout is not None else math.inf
        while not future.done():
            if cancelled is not None and cancelled.is_set():
                raise RuntimeError('Pinky 명령이 취소되었습니다')
            if time.monotonic() >= deadline:
                raise TimeoutError('Route Server 응답 누락')
            time.sleep(.02)
        return future.result()

    @staticmethod
    def _wait_server(client, cancelled):
        while not client.wait_for_server(timeout_sec=.2):
            if cancelled.is_set():
                raise RuntimeError('Nav2 연결 대기 중 명령 취소')

    def _cancel(self):
        if self.handle is not None and self.handle.accepted:
            return self.handle.cancel_goal_async()
        return None

    def _compute_route(self, request, cancelled, accepted, record):
        print('Route Server 연결 대기...', flush=True)
        self._wait_server(self.route_action, cancelled)
        for attempt in (1, 2):
            phase = '요청 접수'
            try:
                print(f'Route Server {phase} 응답 대기 ({attempt}/2)', flush=True)
                record('route_request', attempt=attempt, start_id=request.start_id, goal_id=request.goal_id)
                self.pending_goal = self.route_action.send_goal_async(request)
                self.pending_goal.add_done_callback(accepted)
                self.handle = self._await(self.pending_goal, cancelled, timeout=8)
                if not self.handle.accepted:
                    raise RuntimeError('Route Server 경로 요청 거부')
                phase = '계산 결과'
                print(f'Route Server {phase} 응답 대기', flush=True)
                return self._await(self.handle.get_result_async(), cancelled, timeout=8)
            except TimeoutError as exc:
                record('route_response_timeout', attempt=attempt, phase=phase)
                if attempt == 2:
                    raise RuntimeError(f'Route Server {phase} 응답 없음: 경로 계산 재요청 1회도 응답 누락') from exc
                print(f'Route Server {phase} 응답 8초간 누락: 경로 계산만 한 번 재요청', flush=True)


    def execute(self, command, cancelled):
        kind = command['kind']
        if kind == 'STOP':
            # Cancel only this adapter's goal. Never cancel another controller's work.
            pending = self.pending_goal
            if pending is not None:
                self.handle = self._await(pending)
            future = self._cancel()
            if future is not None:
                self._await(future)
            return {'cancel_requested': True}
        if kind not in {'NAVIGATE', 'LEAVE'}:
            raise RuntimeError('지원하지 않는 Pinky 명령')
        with self.motion_lock:
            from robots.pinky.field_routes import plan, command_route
            contract = command_route(self.profile['goals_file'], command)
            selected = ({'segments': []} if contract['route_id'] in self.route_index else
                        plan(self.profile['goals_file'], contract['route_id']))
            if cancelled.is_set():
                raise RuntimeError('실행 전 중지된 Pinky 명령')
            abandon = threading.Event()
            trace, trace_file = None, None
            if self.profile.get('trace_directory'):
                directory = Path(self.profile['trace_directory'])
                directory.mkdir(parents=True, exist_ok=True)
                trace_file = directory/f'{time.time_ns()}-{contract["route_id"]}.jsonl'
                trace = trace_file.open('w', buffering=1)
                print('주행 기록: '+str(trace_file), flush=True)
            def record(event, **details):
                if trace:
                    trace.write(json.dumps({'time': time.time(), 'event': event, **details})+'\n')
            def accepted(future):
                handle = future.result()
                if handle.accepted and (abandon.is_set() or cancelled.is_set()):
                    handle.cancel_goal_async()
            try:
                from geometry_msgs.msg import PoseStamped
                if self.profile.get('planning_footprint'):
                    record('navigation_geometry', footprint=self.profile['planning_footprint'],
                           basket_scale=self.profile.get('planning_basket_scale'))
                camera_correction = {}
                route_key = f"v{command.get('route_version',4)}/{contract['route_id']}"
                entry = self.route_index.get(route_key) or self.route_index.get(contract['route_id'])
                camera_only = entry and all(s.get('camera_guided') for s in entry['segments'])
                if self.profile.get('camera_socket') and not camera_only:
                    camera_correction = self.correct_from_camera(cancelled)
                    record('camera_localization', **camera_correction)
                segments = selected['segments']
                version = command.get('route_version', 4)
                version_key = f"v{version}/{contract['route_id']}"
                routed = (self.route_index[version_key] if version == 3 else
                          self.route_index.get(version_key) or self.route_index.get(contract['route_id']))
                record('route_identity', route_version=version, route_id=contract['route_id'],
                       route_index_file=self.profile.get('route_index_file'),
                       graph_sha256=self.route_graph_hash, source_hash=contract['source_hash'])
                join_pose = None
                if routed and command.get('join_return_from_current'):
                    from robots.pinky.route_graph import return_from_current
                    join_pose = (camera_correction.get('pose') or
                                 self.snapshot(wait_for_tf=True, cancelled=cancelled)['pose'])
                    routed = return_from_current(routed, join_pose)
                    print('현재 위치 → 복귀 경로 합류: '+routed['segments'][0]['name'], flush=True)
                    record('return_join', pose=join_pose, segment=routed['segments'][0]['name'],
                           start_id=routed['segments'][0]['start_id'])
                if routed:
                    from robots.pinky.route_graph import directed_path
                    segments = []
                    for original in routed['segments']:
                        segment = dict(original)
                        if segment['direction'] != 0:
                            request = self.route_type.Goal()
                            request.start_id, request.goal_id = segment['start_id'], segment['goal_id']
                            request.use_poses = False
                            routed_result = self._compute_route(request, cancelled, accepted, record)
                            record('route_result', segment=segment['name'], status=routed_result.status,
                                   error_code=routed_result.result.error_code,
                                   start_id=request.start_id, goal_id=request.goal_id)
                            if routed_result.status != 4 or routed_result.result.error_code:
                                raise RuntimeError(f'Route Server: status={routed_result.status}, code={routed_result.result.error_code}')
                            segment['poses'] = directed_path(routed_result.result.path, segment['direction'],
                                                             original['poses'][-1][2])
                            print(f"Route Server {segment['name']}: {len(segment['poses'])}개 경로점", flush=True)
                        segments.append(segment)
                    if join_pose is not None:
                        from robots.pinky.route_graph import return_join_segments
                        segments = return_join_segments(segments, join_pose)
                elif kind == 'NAVIGATE' and self.profile.get('entry_planner_id'):
                    # Join the fixed final reverse dock from the actual pose.
                    # The Hybrid planner includes the rear basket and both driving directions.
                    target = segments[-1]['poses'][0]
                    request = self.planner_type.Goal()
                    request.goal.header.frame_id = self.profile['frame_id']
                    request.goal.header.stamp = self.node.get_clock().now().to_msg()
                    request.goal.pose.position.x, request.goal.pose.position.y = float(target[0]), float(target[1])
                    request.goal.pose.orientation.z = math.sin(target[2]/2)
                    request.goal.pose.orientation.w = math.cos(target[2]/2)
                    request.planner_id = self.profile['entry_planner_id']
                    request.use_start = False
                    self._wait_server(self.planner_action, cancelled)
                    self.pending_goal = self.planner_action.send_goal_async(request)
                    self.pending_goal.add_done_callback(accepted)
                    self.handle = self._await(self.pending_goal, cancelled)
                    if not self.handle.accepted:
                        raise RuntimeError('Nav2가 현재 위치 진입 경로 계산을 거부했습니다')
                    planned = self._await(self.handle.get_result_async(), cancelled)
                    if cancelled.is_set() or planned.status != 4 or planned.result.error_code:
                        raise RuntimeError(f'현재 위치 진입 경로: status={planned.status}, '
                                           f'code={planned.result.error_code}, {planned.result.error_msg}')
                    poses = [pose_values(p.pose) for p in planned.result.path.poses]
                    segments = [{'name': 'current_to_dock_approach', 'direction': None,
                                 'poses': [[p['x'], p['y'], p['yaw']] for p in poses],
                                 'goal_checker_id': self.profile.get('entry_goal_checker_id', 'general_goal_checker')},
                                {'name': 'align_before_dock', 'direction': 0,
                                 'poses': [target]}] + segments[-1:]
                from robots.pinky.route_graph import observation_heading, path_goal_checker
                if not (routed and routed.get('waiting_slot')):
                    segments = observation_heading(segments)
                camera_segments = [s for s in segments if s.get('camera_guided')]
                segments = [s for s in segments if not s.get('camera_guided')]
                if version == 3 and segments:
                    print('v3 중간 이동: 위치 5cm 도달로 다음 구간 연결, 방향은 경로·회전 구간에서 정렬', flush=True)
                for index, segment in enumerate(segments):
                    if cancelled.is_set():
                        raise RuntimeError('중단된 관제 경로')
                    # Each preceding Nav2 action has finished before this boundary.
                    if index and self.profile.get('camera_socket') and segment['name'] not in ('observation_heading','waiting_entry_heading'):
                        record('camera_localization', **self.correct_from_camera(cancelled))
                    if segment['direction'] == 0:
                        if segment['name'] == 'observation_heading':
                            print('관측 위치 5cm 이내 도착 → 최종 방향 정렬 → 카메라 정밀주차', flush=True)
                        print('회전 전 지도 위치(TF) 수신 대기...', flush=True)
                        spin_origin = self.snapshot(wait_for_tf=True, cancelled=cancelled)['pose']
                        if segment['name'] == 'home_face_aisle' and segments[index+1]['name'] == 'home_to_dock':
                            from robots.pinky.route_graph import departure_path
                            joined = departure_path(segments[index+1]['poses'], spin_origin, align_heading=True)
                            segment = dict(segment, poses=[[spin_origin[k] for k in ('x', 'y', 'yaw')], joined[0]])
                            record('departure_alignment', pose=spin_origin, target_yaw=joined[0][2])
                        request = self.spin_type.Goal()
                        a, b = spin_origin['yaw'], segment['poses'][-1][2]
                        request.target_yaw = math.atan2(math.sin(b-a), math.cos(b-a))
                        request.time_allowance.sec = 0
                        client = self.spin_action
                    else:
                        if segment['name'] == 'home_to_dock':
                            from robots.pinky.route_graph import departure_path
                            # Rotation can update AMCL. Reconnect from the pose after the spin.
                            current = self.snapshot(wait_for_tf=True, cancelled=cancelled, include_odometry=True)
                            segment = dict(segment, poses=departure_path(segment['poses'], current['pose']))
                            record('departure_connection', **current)
                            print('현재 위치에서 후진 연결 → 기존 통로 경로', flush=True)
                        request = self.action_type.Goal()
                        request.path.header.frame_id = self.profile['frame_id']
                        # Keep stamp=0 so goal checking uses the latest map→odom correction, like path tracking.
                        request.controller_id = 'FollowPath'
                        request.goal_checker_id = path_goal_checker(segment, version)
                        request.progress_checker_id = 'progress_checker'
                        for x, y, yaw in segment['poses']:
                            item = PoseStamped()
                            item.header = request.path.header
                            item.pose.position.x, item.pose.position.y = float(x), float(y)
                            item.pose.orientation.z, item.pose.orientation.w = math.sin(yaw/2), math.cos(yaw/2)
                            request.path.poses.append(item)
                        client = self.action
                    record('segment', name=segment['name'], direction=segment['direction'], poses=segment['poses'],
                           goal_checker_id=getattr(request, 'goal_checker_id', None))
                    self._wait_server(client, cancelled)
                    self.pending_goal = client.send_goal_async(request)
                    self.pending_goal.add_done_callback(accepted)
                    self.handle = self._await(self.pending_goal, cancelled)
                    if not self.handle.accepted:
                        raise RuntimeError('Nav2가 관제 경로를 거부했습니다')
                    result = self.handle.get_result_async()
                    last_sample = 0.
                    while not result.done():
                        if cancelled.is_set():
                            raise RuntimeError('Pinky 명령이 취소되었습니다')
                        if trace and time.monotonic()-last_sample >= .2:
                            last_sample = time.monotonic()
                            try:
                                observation = self.snapshot(include_odometry=True)
                                record('pose', segment=segment['name'], **observation)
                            except Exception as exc:
                                record('observation_error', error=str(exc))
                        time.sleep(.03)
                    outcome = result.result()
                    record('segment_result', name=segment['name'], status=outcome.status,
                           error_code=getattr(outcome.result, 'error_code', 0),
                           error_msg=getattr(outcome.result, 'error_msg', ''))
                    if (cancelled.is_set() or outcome.status != 4
                            or getattr(outcome.result, 'error_code', 0) != 0):
                        raise RuntimeError(f"{segment['name']}: status={outcome.status}, "
                                           f"code={getattr(outcome.result, 'error_code', 0)}, "
                                           f"{getattr(outcome.result, 'error_msg', '')}")
                result = {'nav2_completed': True, 'zone_id': command['zone_id'],
                          'route_server_used': bool(routed), 'trace_file': str(trace_file) if trace_file else None,
                          'parking_start': routed.get('parking_start') if routed else None,
                          'pose': None}
                if camera_segments:
                    from .wait_parking import align_wait
                    result['waiting_parking'] = align_wait('P'+self.profile['robot_id'][-1],
                        routed['waiting_slot'], self.profile, cancelled, segments=camera_segments)
                    record('waiting_parking', **result['waiting_parking'])
                try:
                    value = self.snapshot()
                    result['pose'] = value['pose']
                except RuntimeError as exc:
                    result['observation_note'] = str(exc)
                return result
            finally:
                abandon.set()
                if trace:
                    trace.close()
                if self.handle is not None:
                    self._cancel()
                self.handle, self.pending_goal = None, None

    def close(self):
        self._cancel()
        self.executor.shutdown(timeout_sec=2)
        self.thread.join(timeout=2)
        self.node.destroy_node()
        self.context.shutdown()


class PinkyFleet:
    """Lazily create a separate ROS context per configured robot."""
    def __init__(self, profiles, evidence, factory=PinkyMobile):
        self.profiles, self.evidence, self.factory = profiles, evidence, factory
        self.mobiles, self.lock = {}, threading.Lock()

    def mobile(self, robot):
        with self.lock:
            if robot not in self.mobiles:
                self.mobiles[robot] = self.factory(load_profile(self.profiles[robot]), self.evidence)
            return self.mobiles[robot]

    def execute(self, command, cancelled):
        return self.mobile(command['device_id']).execute(command, cancelled)

    def inspect_all(self):
        with self.lock:
            active = list(self.mobiles.items())
        return {robot: mobile.inspect() for robot, mobile in active}

    def close(self):
        for mobile in self.mobiles.values():
            mobile.close()


def create_mobile(config, evidence):
    profiles = config.get('mobile_profiles')
    if not profiles:
        profile = load_profile(config['mobile_config'])
        profiles = {profile['robot_id']: config['mobile_config']}
    return PinkyFleet(profiles, evidence)
