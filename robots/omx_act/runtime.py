"""ACT control loop for the audited LeRobot 8fff0fde interface, not lerobot-record CLI."""
from pathlib import Path
import threading
import time


class ActArm:
    def __init__(self, config, evidence, frames):
        self.config, self.evidence, self.frames = config, evidence, frames
        self.robot, self.policy, self.active = None, None, None
        self.lock = threading.Lock()

    def connect(self):
        if self.robot:
            return
        from lerobot.cameras.opencv.configuration_opencv import OpenCVCameraConfig
        from lerobot.robots.omx_follower.config_omx_follower import OmxFollowerConfig
        from lerobot.robots.omx_follower.omx_follower import OmxFollower
        import inspect
        if 'wrist_position' not in inspect.getsource(OmxFollower.configure):
            raise RuntimeError('고정 LeRobot 소스의 손목 초기 위치 패치를 먼저 적용하세요')
        cfg = self.config
        cameras = {name: OpenCVCameraConfig(index_or_path=Path(cfg[name + '_by_id']),
                    width=640, height=480, fps=30, fourcc='MJPG') for name in ('front', 'wrist')}
        robot = OmxFollower(OmxFollowerConfig(port=cfg['serial_by_id'], id=cfg['robot_id'],
            calibration_dir=Path(cfg['calibration_dir']).expanduser(), cameras=cameras,
            disable_torque_on_disconnect=False, max_relative_target=cfg['max_relative_target']))
        if not robot.calibration:
            raise RuntimeError('팔로워 캘리브레이션 파일이 없습니다')
        robot.connect(calibrate=False)
        self.robot = robot

    def load_policy(self, command):
        model = self.config['models'].get(command['basket_side'])
        if not model or model['id'] != command['model_id']:
            raise RuntimeError('선택한 방향의 모델이 없습니다. 다른 방향 모델을 대체 실행하지 않습니다')
        from lerobot.policies.act.modeling_act import ACTPolicy
        from lerobot.policies.factory import make_pre_post_processors
        path = str(Path(model['path']).expanduser().resolve(strict=True))
        self.policy = ACTPolicy.from_pretrained(path, local_files_only=True)
        if self.policy.config.n_action_steps != 100 or self.policy.config.chunk_size != 100:
            raise RuntimeError('검증된 ACT chunk/n_action_steps=100 설정과 다릅니다')
        self.policy.eval(); self.policy.reset()
        self.pre, self.post = make_pre_post_processors(self.policy.config, pretrained_path=path,
            preprocessor_overrides={'device_processor': {'device': self.policy.config.device},
                                    'rename_observations_processor': {'rename_map': {}}})
        self.pre.reset(); self.post.reset()

    def _pose(self):
        return self.robot.bus.sync_read('Present_Position')

    def hold(self):
        if self.robot:
            self.robot.send_action({k + '.pos': v for k, v in self._pose().items()})

    def at_standby(self, observation):
        target = self.config['standby_pose']
        tolerance = self.config['standby_tolerance']
        return all(abs(observation[key + '.pos'] - value) <= tolerance for key, value in target.items())

    def execute(self, command, cancelled):
        with self.lock:
            self.load_policy(command)  # Missing right checkpoint fails before device connection.
            if cancelled.is_set():
                raise RuntimeError('모델 준비 중 중단되어 장비를 연결하지 않습니다')
            self.connect()
            import numpy as np
            import torch
            from lerobot.utils.control_utils import predict_action
            names = list(self.robot.action_features)
            self.active = command['id']
            began = time.monotonic()
            try:
                while time.monotonic() - began < 180:
                    cycle = time.monotonic()
                    if cancelled.is_set():
                        raise RuntimeError('ACT 중단 또는 중앙 통신 만료')
                    obs = self.robot.get_observation()
                    for name in ('front', 'wrist'):
                        self.frames.offer('handoff-' + name, obs[name], 'RGB')
                    proof = self.evidence.read(command, 'handoff')
                    if proof and all(proof.get(k) is True for k in ('cart_visible', 'cart_empty', 'last_item_placed', 'standby_reached')):
                        if self.at_standby(obs):
                            if proof.get('confirmed_items') == command['items'] and proof.get('basket_id') == command['basket_id']:
                                self.hold()
                                return proof
                    observation = {'observation.state': np.asarray([obs[k] for k in names], dtype=np.float32),
                        **{'observation.images.' + n: obs[n] for n in ('front', 'wrist')}}
                    values = predict_action(observation, self.policy, torch.device(self.policy.config.device),
                        self.pre, self.post, self.policy.config.use_amp, task='Unload into the assigned basket', robot_type=self.robot.robot_type)
                    if cancelled.is_set():
                        raise RuntimeError('ACT 출력 전 중단 확인')
                    self.robot.send_action(dict(zip(names, values.squeeze(0).cpu().tolist())))
                    cancelled.wait(max(0, 1 / 30 - (time.monotonic() - cycle)))
                raise RuntimeError('ACT 180초 제한: 성공으로 처리하지 않습니다')
            finally:
                try:
                    self.hold()
                finally:
                    self.active = None
                    self.policy.reset()

    def stopped(self, command, cancelled):
        # A request is not a stop confirmation. Wait for execute() to release its lock.
        with self.lock:
            if self.robot is None or self.active is not None:
                raise RuntimeError('ACT 출력 중지 미확인')
            self.hold()
            before = self._pose()
            deadline = time.monotonic() + .5
            while time.monotonic() < deadline:
                time.sleep(.05)
                after = self._pose()
                if any(abs(after[k] - before[k]) > self.config['position_tolerance'] for k in before):
                    raise RuntimeError('관절 피드백에서 정지 미확인')
            torque = self.robot.bus.sync_read('Torque_Enable', normalize=False)
            if not torque or not all(v == 1 for v in torque.values()):
                raise RuntimeError('토크 유지 미확인')
            return {'policy_stopped': True, 'motion_stopped': True, 'hold_confirmed': True, 'torque_enabled': True}

    def stop(self, command, cancelled):
        self.stopped(command, cancelled)
        return {'stopped': True}
