"""Reference-motion validation for the existing commissioning protocol."""
import math

from robots.pinky.catalog import BACKEND, FRAME, VERSION, bundle, route
from .domain import require, digest

def validate_request(engine, node, params, report):
    require(engine.mode == 'mock' and node == 'gateway-a', '도로 이동 시험은 모의 중계 A에서만 실행합니다')
    require(set(params) == {'route_id', 'robot_id', 'rate'}, '이동 시험 입력 오류', 422)
    require(params['robot_id'] in ('pinky-1', 'pinky-2'), 'Pinky 식별 오류', 422)
    require(type(params['rate']) is int and params['rate'] in (1, 2, 4), '재생 배속은 1·2·4배입니다', 422)
    require(isinstance(params['route_id'], str) and params['route_id'] in bundle()[1], '경로를 선택하세요', 422)
    require(report.get('motion_backend') == BACKEND and report.get('source_hash') == bundle()[3],
            '도로 v3 실행부의 준비 상태·해시가 일치해야 합니다')


def validate_sample(engine, job, value, provider=None):
    from robots.pinky import catalog
    provider = provider or catalog
    require(isinstance(value, dict), '위치 관측이 필요합니다', 422)
    expected = dict(run_id=job['run_id'], command_id=job['id'], task_id=job.get('task_id', job['id']), session_id=job.get('session_id'),
                    robot_id=job['robot_id'], backend=BACKEND, observation_source=BACKEND,
                    route_version=provider.VERSION, source_hash=job['source_hash'], frame_id=provider.FRAME)
    require(all(value.get(k) == v for k, v in expected.items()), '위치 관측 식별자·출처·도로 기준 불일치', 422)
    require(isinstance(value.get('sim_epoch'), str) and 8 <= len(value['sim_epoch']) <= 100,
            '시뮬 실행 식별자가 필요합니다', 422)
    require(type(value.get('sequence')) is int and value['sequence'] > 0, '관측 순번 오류', 422)
    for key in ('sim_time', 'observed_at', 'speed', 'progress'):
        require(type(value.get(key)) in (int, float) and math.isfinite(value[key]), '유효한 관측 수치가 필요합니다', 422)
    require(-1 <= engine.clock() - value['observed_at'] <= 2, '오래됐거나 미래의 위치 관측입니다', 422)
    r = provider.route(job['parameters']['route_id'])
    require(0 <= value['sim_time'] <= r.duration and value['speed'] >= 0, '시뮬 시각·속도 오류', 422)
    require(type(value.get('halted')) is bool and type(value.get('arrived')) is bool, '정지·도착 판정 오류', 422)
    pose = value.get('pose')
    require(isinstance(pose, list) and len(pose) == 3 and
            all(type(v) in (int, float) and math.isfinite(v) for v in pose), '좌표 오류', 422)
    target, speed = r.sample(value['sim_time'])
    require(math.dist(pose, target) < 1e-6 and abs(value['progress'] - value['sim_time'] / r.duration) < 1e-6,
            '위치와 기준 경로 진행 상태가 다릅니다', 422)
    require(value['arrived'] == (value['sim_time'] >= r.duration), '도착 근거 불일치', 422)
    require(abs(value['speed'] - (0 if value['halted'] else speed)) < 1e-6, '정지·속도 근거 불일치', 422)
    old = job.get('telemetry')
    if old:
        require(old['sim_epoch'] == value['sim_epoch'], '실행 중 시뮬 초기화 감지')
        require(value['sequence'] >= old['sequence'] and value['sim_time'] >= old['sim_time'], '역순 위치 관측입니다')
        if value['sequence'] == old['sequence']:
            require(job['telemetry_signature'] == digest(value), '같은 순번의 다른 위치 관측입니다')
            return False
    job['telemetry'] = {**value, 'received_at': engine.clock(), 'received_monotonic': engine.receiver_clock(),
                        'receiver_epoch': engine.receiver_epoch}
    job['telemetry_signature'] = digest(value)
    return True
