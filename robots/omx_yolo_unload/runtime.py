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
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.run_lock = threading.Lock()

    def execute(self, command, cancelled):
        if command['kind'] != 'HANDOFF':
            raise ValueError('C YOLO 실행에는 HANDOFF 명령이 필요합니다')
        with self.run_lock:
            key = hashlib.sha256(command['id'].encode()).hexdigest()[:24]
            self.journal = Path(self.config['journal_directory']) / (key + '.json')
            identity = {k: command[k] for k in ('id', 'robot_id', 'basket_side', 'items')}
            identity['basket_id'] = command.get('basket_id')
            self.history = json.loads(self.journal.read_text()) if self.journal.exists() else {
                'command': identity, 'executed_items': [], 'plans': []}
            if self.history['command'] != identity:
                raise ValueError('같은 하역 ID의 상품·로봇·수령 바구니가 변경됐습니다')
            done = self.history['executed_items']
            pending = [item for item in command['items'] if item not in done]
            self.executed = done.copy()
            if not pending:
                return self.result(command)
            self.history.update(status='running', physical_delivery_confirmed=False)
            write_json(self.journal, self.history)
            try:
                super().execute(dict(command, items=pending), cancelled)
                self.executed = self.history['executed_items'].copy()
                self.history.update(status='motions_completed', error=None)
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
        for item in command['items']:
            rule = get_rule(job, self.products[item['sku']]['detector_class'])
            calibration_for(profile, rule, job)
            number(rule.get('pick_z_mm'), '상품 집기 Z')
        return basket_job(job, command['robot_id'])

    def references(self, job, command, profile):
        return {i['sku']: self.saved['pickup_approach'] for i in command['items']}

    def build_item_plan(self, job, calibration, target, reference, profile, command, item,
                        item_index, fixed_wrist):
        from omx_pick import select_grasp_plan
        return select_grasp_plan(reference, self.saved['pickup_approach'],
            lambda solve: plan(job, calibration, target, self.saved, solve,
                command['robot_id'], command['basket_side']),
            wrist_policy=job.get('wrist_policy', 'fixed'), fixed_wrist_pulse=fixed_wrist)

    def item_done(self, command, item, trajectory):
        self.history['executed_items'].append(item.copy())
        self.history['plans'].append({'item': item.copy(), 'trajectory': trajectory,
                                     'completed_at': datetime.now().astimezone().isoformat()})
        write_json(self.journal, self.history)

    def result(self, command):
        return {'executed_items': self.executed.copy(), 'physical_delivery_confirmed': False,
                'basket_id': command.get('basket_id'), 'basket_side': command['basket_side'],
                'engine': 'yolo_unload', 'operator_review_required': True,
                'result_file': str(self.journal)}

    def stopped(self, command, cancelled):
        with self.run_lock:
            return {'policy_stopped': True, 'hold_requested': True}


def create_arm(config, evidence, frames):
    if config.get('unload_engine', 'act') == 'yolo':
        from server.catalog import load_products
        return YoloUnloadArm(config['yolo_unload'], evidence, frames, load_products())
    from robot_gateway.hardware.act import ActArm
    return ActArm(config['act'], evidence, frames)
