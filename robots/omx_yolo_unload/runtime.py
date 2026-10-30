"""Reuse the A/B capture and motor loop with C-specific pick/drop planning."""
import hashlib
import json
from pathlib import Path
import threading
from datetime import datetime

from robot_gateway.hardware.yolo import YoloArm
from .core import POSES, basket_job, plan


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    temp.replace(path)


class YoloUnloadArm(YoloArm):
    prefetch_target = True

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.run_lock = threading.Lock()

    def execute(self, command, cancelled):
        if command['kind'] != 'HANDOFF':
            raise ValueError('C YOLO 실행에는 HANDOFF 명령이 필요합니다')
        with self.run_lock:
            self.selection_mode = command.get('selection_mode', self.config.get('selection_mode', 'ordered'))
            if self.selection_mode not in ('all', 'ordered'):
                raise ValueError('selection_mode는 all 또는 ordered여야 합니다')
            key = hashlib.sha256(command['id'].encode()).hexdigest()[:24]
            self.journal = Path(self.config['journal_directory']) / (key + '.json')
            identity = {k: command[k] for k in ('id', 'robot_id', 'basket_side', 'items')}
            identity['basket_id'] = command.get('basket_id')
            if self.selection_mode == 'all':
                identity['selection_mode'] = 'all'
            self.history = json.loads(self.journal.read_text()) if self.journal.exists() else {
                'command': identity, 'executed_items': [], 'plans': []}
            if self.history['command'] != identity:
                raise ValueError('같은 하역 ID의 상품·로봇·수령 바구니가 변경됐습니다')
            done = self.history['executed_items']
            pending = [item for item in command['items'] if item not in done]
            self.executed = done.copy()
            if not pending and self.selection_mode == 'ordered':
                return self.result(command)
            self.history.setdefault('attempted_items', [])
            self.history.update(status='running', physical_delivery_confirmed=False,
                                stop_reason=None, empty_scene_candidate=False)
            write_json(self.journal, self.history)
            try:
                super().execute(dict(command, items=pending, selection_mode=self.selection_mode), cancelled)
                self.executed = self.history['executed_items'].copy()
                self.history.update(status=('awaiting_operator_review' if self.selection_mode == 'all'
                                            else 'motions_completed'), error=None)
                return self.result(command)
            except BaseException as exc:
                self.executed = self.history['executed_items'].copy()
                self.history.update(status='interrupted', error=str(exc))
                raise
            finally:
                write_json(self.journal, self.history)

    def prepare_job(self, job, command, profile):
        from omx_pick import legacy, calibration_for
        from pick_core import get_rule, number, validate_gripper
        if command['basket_side'] not in ('left', 'right'):
            raise ValueError('주문 수령 방향이 필요합니다')
        # These are all C-local artifacts; do not fall back to A/B poses.
        recorder = legacy('07_omx_pose_recorder.py', 'unload_pose_recorder')
        self.saved = {name: recorder.load_pose(name, profile)['raw_pulses'] for name in POSES}
        validate_gripper(job)
        for item in (command['items'] if self.selection_mode == 'ordered' else []):
            rule = get_rule(job, self.products[item['sku']]['detector_class'])
            calibration_for(profile, rule, job)
            number(rule.get('pick_z_mm'), '상품 집기 Z')
        return basket_job(job, command['robot_id'])

    def references(self, job, command, profile):
        return {i['sku']: self.saved['pickup_approach'] for i in command['items']}

    def detector_for(self, job, weights):
        from .vision import BasketDetector
        return BasketDetector(job, weights)

    def validate_detector(self, detector, job):
        expected = self.config.get('model_classes')
        if expected is None:
            return super().validate_detector(detector, job)
        known = {p['detector_class'] for p in self.products.values()}
        if (not isinstance(expected, list) or not expected
                or any(not isinstance(name, str) or name not in known or name not in job['classes']
                       for name in expected) or len(set(expected)) != len(expected)):
            raise ValueError('C model_classes에 중복 없는 등록 상품 이름이 필요합니다')
        actual = [detector.model.names[i] for i in sorted(detector.model.names)]
        if actual != expected:
            raise RuntimeError(f'C 모델 라벨 순서 불일치: {actual} / 설정: {expected}')

    def targets(self, job, command, profile, camera, detector, references, cancelled):
        if self.selection_mode == 'ordered':
            yield from super().targets(job, command, profile, camera, detector, references, cancelled)
            return
        from pick_core import get_rule, integer, number
        from omx_pick import calibration_for
        from .vision import eligible
        # A missed grasp must not result in an unbounded motor loop.
        limit = integer(command.get('max_picks', self.config.get('max_picks', 12)), 'max_picks', 1, 100)
        empty_reads, attempts = 0, 0
        while attempts < limit:
            if cancelled.is_set():
                raise RuntimeError('작업 중단')
            frame, _ = camera.read()
            height, width = frame.shape[:2]
            if (width, height) != (profile.width, profile.height):
                raise RuntimeError('카메라·C 설정 해상도 불일치')
            candidates = eligible(detector.predict(frame), job, width, height)
            if not candidates:
                empty_reads += 1
                if empty_reads == 3:
                    self.history.update(stop_reason='no_detections_rechecked', empty_scene_candidate=True)
                    return
                cancelled.wait(.3)
                continue
            empty_reads = 0
            target = candidates[0]
            rule = get_rule(job, target.label)
            number(rule.get('pick_z_mm'), f'{target.label} 집기 Z')
            calibration, _ = calibration_for(profile, rule, job)
            if (width, height) != (calibration['width'], calibration['height']):
                raise RuntimeError('캘리브레이션·카메라 해상도 불일치')
            sequence = len(self.history['attempted_items'])
            item = {'attempt_id': f"{command['id']}-attempt-{sequence}", 'slot': sequence,
                    'observed_class': target.label, 'confidence': target.confidence, 'box': list(target.box)}
            yield item, job, calibration, target, self.saved['pickup_approach']
            attempts += 1
        self.history.update(stop_reason='pick_limit_reached', empty_scene_candidate=False)

    def build_item_plan(self, job, calibration, target, reference, profile, command, item,
                        item_index, fixed_wrist):
        from omx_pick import select_grasp_plan
        return select_grasp_plan(reference, self.saved['pickup_approach'],
            lambda solve: plan(job, calibration, target, self.saved, solve,
                command['robot_id'], command['basket_side']),
            wrist_policy=job.get('wrist_policy', 'fixed'), fixed_wrist_pulse=fixed_wrist)

    def item_done(self, command, item, trajectory):
        key = 'attempted_items' if self.selection_mode == 'all' else 'executed_items'
        self.history[key].append(item.copy())
        self.history['plans'].append({'item': item.copy(), 'trajectory': trajectory,
                                     'completed_at': datetime.now().astimezone().isoformat()})
        write_json(self.journal, self.history)

    def result(self, command):
        result = {'executed_items': self.executed.copy(), 'physical_delivery_confirmed': False,
                'basket_id': command.get('basket_id'), 'basket_side': command['basket_side'],
                'engine': 'yolo_unload', 'operator_review_required': True,
                'result_file': str(self.journal)}
        if self.selection_mode == 'all':
            result.update(executed_items=[], attempted_items=self.history['attempted_items'].copy(),
                selection_mode='all', stop_reason=self.history.get('stop_reason'),
                empty_scene_candidate=self.history.get('empty_scene_candidate', False))
        return result

    def stopped(self, command, cancelled):
        with self.run_lock:
            return {'policy_stopped': True, 'hold_requested': True}


def create_arm(config, evidence, frames):
    if config.get('unload_engine', 'act') == 'yolo':
        from server.catalog import load_products
        return YoloUnloadArm(config['yolo_unload'], evidence, frames, load_products())
    from robot_gateway.hardware.act import ActArm
    return ActArm(config['act'], evidence, frames)
