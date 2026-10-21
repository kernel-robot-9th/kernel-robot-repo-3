"""Three calibrated Pinky drop slots over the imported YOLO pick planner."""
from contextlib import ExitStack
from pathlib import Path
import sys
import threading
import time
from robot_gateway.frames import SharedCamera

ROOT = Path(__file__).resolve().parents[2] / 'integrations' / 'omx_yolo'


class YoloArm:
    def __init__(self, config, evidence, frames, products):
        self.config, self.evidence, self.frames, self.products = config, evidence, frames, products
        self.lock = threading.Lock()
        self.confirmed = []

    def execute(self, command, cancelled):
        with self.lock, ExitStack() as stack:
            self.confirmed = []
            sys.path.insert(0, str(ROOT / 'tools' / 'picking'))
            from pick_core import build_plan, choose, execute, get_rule, load_config
            from omx_pick import calibration_for, solver_for, legacy, require_job_arm
            from omx_arm_config import ArmProfile
            from pick_robot import DynamixelBus, MotionController
            from pick_vision import Camera, Detector
            cfg = self.config
            profile = ArmProfile(cfg['arm_name'], Path(cfg['serial_by_id']), cfg['camera_by_id'],
                cfg['width'], cfg['height'], cfg['fps'], Path('unused'), Path(cfg['calibration_file']), Path(cfg['poses_file']))
            job = load_config(Path(cfg['pick_config']))
            require_job_arm(job, profile)
            detector = Detector(job, str(ROOT / 'weights' / 'best.pt'))
            if [detector.model.names[i] for i in sorted(detector.model.names)] != [p['detector_class'] for p in self.products.values()]:
                raise RuntimeError('YOLO 모델과 상품 기준 라벨이 다릅니다')
            camera = SharedCamera(stack.enter_context(Camera(profile)), self.frames, command['zone_id'])
            stack.callback(camera.close)
            if cancelled.is_set():
                raise RuntimeError('준비 중 작업 중단')
            bus = stack.enter_context(DynamixelBus(profile.port))
            recorder = legacy('07_omx_pose_recorder.py', 'cartrina_pose_recorder')

            class CancellableMotion(MotionController):
                def ramp(inner, targets, seconds=None):
                    import math
                    start = {i: bus.read(i, 132, 4) for i in targets}
                    duration = job['stage_seconds'] if seconds is None else seconds
                    steps = max(1, math.ceil(duration / .05))
                    for step in range(1, steps + 1):
                        if cancelled.is_set():
                            raise RuntimeError('YOLO 중단 또는 중앙 통신 만료')
                        t = step / steps
                        for motor, target in targets.items():
                            bus.write(motor, 116, 4, round(start[motor] + t * t * (3 - 2 * t) * (target - start[motor])))
                        cancelled.wait(duration / steps)
                    cancelled.wait(job.get('stage_pause_seconds', .5))

                def gripper(inner, name, target):
                    if 16 not in inner.ids or not 0 <= target <= 4095:
                        raise ValueError('그리퍼 실행 상태/목표 오류')
                    inner.ramp({16: target}, job.get('gripper_seconds', job['stage_seconds']))
                    if name not in ('OPEN', 'RELEASE'):
                        cancelled.wait(job['gripper']['settle_s'])
                    if cancelled.is_set():
                        raise RuntimeError('그리퍼 동작 중 중단 확인')

            driver = CancellableMotion(bus, job)
            driver.prepare()
            if cancelled.is_set():
                raise RuntimeError('모터 준비 중 작업 중단')
            driver.enable()
            self.confirmed = []
            try:
                for item in command['items']:
                    if cancelled.is_set():
                        raise RuntimeError('작업 중단')
                    label = self.products[item['sku']]['detector_class']
                    calibration, _ = calibration_for(profile, get_rule(job, label), job)
                    if job.get('regions_source') == 'calibration':
                        job = dict(job, regions_uv=calibration['regions_uv'])
                    frame, _ = camera.read()
                    height, width = frame.shape[:2]
                    if (width, height) != (calibration['width'], calibration['height']):
                        raise RuntimeError('캘리브레이션·카메라 해상도 불일치')
                    target = choose(detector.predict(frame), job, label, width, height)
                    names = cfg['drop_slots'][command['robot_id']][str(item['slot'])]
                    saved = {key: recorder.load_pose(name, profile)['raw_pulses'] for key, name in {
                        'hover_high': 'hover_high', 'drop_approach': names['approach'], 'drop_release': names['release']}.items()}
                    plan = build_plan(job, calibration, target, saved, solver_for())
                    execute(plan, driver)
                    proof = self.evidence.wait(command, 'pick-' + str(item['slot']), cancelled)
                    if proof.get('confirmed_items') != [item]:
                        raise RuntimeError('실제 적재 상품·위치 확인 불일치')
                    self.confirmed.append(item.copy())
                return {'confirmed_items': self.confirmed.copy()}
            finally:
                driver.hold()

    def stop(self, command, cancelled):
        # The running trajectory checks cancellation between motor setpoints.
        with self.lock:
            proof = self.evidence.wait(command, 'stop', threading.Event())
            if proof.get('stopped') is not True:
                raise RuntimeError('실제 OMX 정지 확인 필요')
            return proof
