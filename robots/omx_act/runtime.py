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
        if not model:
            raise RuntimeError('선택한 방향의 모델이 없습니다. 다른 방향 모델을 대체 실행하지 않습니다')
        from lerobot.policies.act.modeling_act import ACTPolicy
        from lerobot.policies.factory import make_pre_post_processors
        path = str(Path(model['path']).expanduser().resolve(strict=True))
        self.policy = ACTPolicy.from_pretrained(path, local_files_only=True)
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
            try:
                while not cancelled.is_set():
                    cycle = time.monotonic()
                    obs = self.robot.get_observation()
                    for name in ('front', 'wrist'):
                        self.frames.offer('handoff-' + name, obs[name], 'RGB')
                    finish = self.evidence.read(command, 'finish') or self.evidence.read(command, 'handoff')
                    if finish:
                        return {'executed_items': command['items'], 'physical_delivery_confirmed': False,
                                'model_id': self.config['models'][command['basket_side']]['id']}
                    observation = {'observation.state': np.asarray([obs[k] for k in names], dtype=np.float32),
                        **{'observation.images.' + n: obs[n] for n in ('front', 'wrist')}}
                    values = predict_action(observation, self.policy, torch.device(self.policy.config.device),
                        self.pre, self.post, self.policy.config.use_amp, task='Unload into the assigned basket', robot_type=self.robot.robot_type)
                    if cancelled.is_set():
                        raise RuntimeError('ACT 출력 전 중단 확인')
                    self.robot.send_action(dict(zip(names, values.squeeze(0).cpu().tolist())))
                    cancelled.wait(max(0, 1 / 30 - (time.monotonic() - cycle)))
                raise RuntimeError('ACT 실행 취소')
            finally:
                try:
                    self.hold()
                finally:
                    self.active = None
                    self.policy.reset()

    def stopped(self, command, cancelled):
        with self.lock:
            self.policy = None
            self.hold()
            return {'policy_stopped': True, 'hold_requested': self.robot is not None}

    def stop(self, command, cancelled):
        return self.stopped(command, cancelled)
