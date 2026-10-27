"""Read-only preflight. No imports that connect robots, cameras, or CUDA."""
import json
from pathlib import Path



def validate(config, *, check_files=True, require_mobile=True, check_slots=True):
    errors = []
    if config.get('armed') is not True:
        errors.append('armed=false: 실물 실행 승인 설정 전')
    node = config.get('node_id')
    if node not in {'gateway-a', 'gateway-b', 'gateway-c'}:
        errors.append('node_id 확인 필요')
    if not config.get('evidence_directory'):
        errors.append('현장 관측 전달 디렉터리 필요')
    video = config.get('video', {})
    if video.get('transport') not in {'jpeg', 'rtsp'}:
        errors.append('video.transport: jpeg 또는 rtsp 필요')
    if type(video.get('fps')) is not int or not 1 <= video['fps'] <= 30:
        errors.append('video.fps: 1~30 정수 필요')
    if video.get('transport') == 'rtsp' and not video.get('rtsp_urls'):
        errors.append('video.rtsp_urls: 담당 채널 게시 주소 필요')
    if require_mobile and node == 'gateway-a' and not config.get('mobile_factory'):
        errors.append('Pinky 주행·정차·이탈·중단 어댑터 미연결 (ROS 이름을 추정하지 않음)')
    if config.get('mobile_factory') == 'robot_gateway.hardware.pinky:create_mobile':
        try:
            from .pinky import load_profile
            paths = config.get('mobile_profiles') or {'default': config.get('mobile_config', '')}
            for robot, location in paths.items():
                profile = load_profile(location)
                if robot != 'default' and profile['robot_id'] != robot:
                    errors.append('Pinky 프로필과 로봇 ID 불일치: ' + robot)
        except (OSError, ValueError, KeyError) as exc:
            errors.append('Pinky 현장 설정: ' + str(exc)[:150])
    arm = config.get('act') if node == 'gateway-c' else config.get('yolo')
    if not isinstance(arm, dict):
        return errors + ['담당 로봇팔 설정 필요']
    def path(key, prefix=None):
        value = arm.get(key)
        if not isinstance(value, str) or (prefix and not value.startswith(prefix)):
            errors.append(key + ': 명시적인 장치/파일 경로 필요')
        elif check_files and not Path(value).expanduser().exists():
            errors.append(key + ': 현장 파일/장치 없음')
    path('serial_by_id', '/dev/serial/by-id/')
    if node == 'gateway-c':
        for name in ('front_by_id', 'wrist_by_id'):
            path(name, '/dev/v4l/by-id/')
        path('calibration_dir')
        if arm.get('front_by_id') == arm.get('wrist_by_id'):
            errors.append('front/wrist는 다른 장치여야 함')
        models = arm.get('models', {})
        if not models.get('left'):
            errors.append('왼쪽 모델 설정 필요')
        for side, model in models.items():
            if model is None:
                continue  # Missing right is an explicit unsupported direction, never a left fallback.
            location = Path(model.get('path', '')).expanduser()
            if check_files:
                if not (location / 'config.json').is_file():
                    errors.append(side + ': 모델 파일 없음')
                    continue
    else:
        path('camera_by_id', '/dev/v4l/by-id/')
        for name in ('pick_config', 'calibration_file', 'poses_file'):
            path(name)
        for robot in (('pinky-1', 'pinky-2') if check_slots else ()):
            slots = arm.get('drop_slots', {}).get(robot, {})
            if set(slots) != {'0', '1', '2'} or any(not isinstance(p, dict) or not p.get('approach') or not p.get('release') for p in slots.values()):
                errors.append(robot + ': 적재 위치 3곳의 접근·놓기 자세 이름 필요')
            elif len({p['release'] for p in slots.values()}) != 3:
                errors.append(robot + ': 동일 놓기 자세를 세 위치에 재사용할 수 없음')
    return errors


def main():
    import argparse
    parser = argparse.ArgumentParser(description='실물 실행 없이 현장 연결 설정을 검사합니다')
    parser.add_argument('--config', required=True)
    args = parser.parse_args()
    problems = validate(json.loads(Path(args.config).read_text(encoding='utf-8')))
    print(json.dumps({'ready': not problems, 'hardware_executed': False, 'issues': problems}, ensure_ascii=False, indent=2))
    return 2 if problems else 0


if __name__ == '__main__':
    raise SystemExit(main())
