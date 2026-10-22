"""Create commissioning files once. Preserve existing credentials and field edits."""
import argparse
import json
import os
from pathlib import Path
import secrets
import shlex
from urllib.parse import urlparse

from server.distributed import profiles

ROOT = Path(__file__).resolve().parents[1]


def prepare(directory, server):
    parsed = urlparse(server)
    if (parsed.scheme not in {'http', 'https'} or not parsed.hostname or
            parsed.username or parsed.password or parsed.query or parsed.fragment or
            parsed.path not in {'', '/'} or any(c in server for c in "\n\r'\" ")):
        raise ValueError('중앙 서버의 http(s) 주소와 포트만 입력하세요')
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    private = directory / 'credentials.json'
    credentials = json.loads(private.read_text(encoding='utf-8')) if private.exists() else {
        'admin': secrets.token_urlsafe(32),
        'nodes': {node: secrets.token_urlsafe(32) for node in profiles()},
    }
    tokens = [credentials['admin'], *credentials['nodes'].values()]
    if (set(credentials['nodes']) != set(profiles()) or
            any(not isinstance(t, str) or len(t) < 16 for t in tokens) or len(set(tokens)) != len(tokens)):
        raise ValueError('기존 인증 파일을 확인하세요. 자동 교체하지 않습니다.')
    # A missing credentials file with existing env files needs manual recovery;
    # generating new secrets would silently leave the four PCs unable to connect.
    if not private.exists() and any(directory.glob('*.env')):
        raise ValueError('기존 env의 인증 원본이 없습니다. credentials.json을 복구하세요.')
    contents = {'credentials.json': json.dumps(credentials, indent=2) + '\n'}
    central = {
        'SHOP_ADMIN_TOKEN': credentials['admin'], 'SHOP_NODE_TOKENS': json.dumps(credentials['nodes']),
        'SHOP_GATEWAY_MODE': 'distributed', 'SHOP_DEVICE_MODE': 'hardware', 'SHOP_TEST_ONLY': '1',
        'SHOP_MOTION_BACKEND': '', 'SHOP_HARDWARE_READINESS': '',
        'SHOP_DB': 'runtime/field/shopping.db', 'SHOP_VIDEO_CONFIG': 'config/video-field.json',
    }
    contents['central.env'] = ''.join(f'{key}={shlex.quote(value)}\n' for key, value in central.items())
    for node, token in credentials['nodes'].items():
        config_name = f'{node}.hardware.json'
        values = {'SHOP_NODE_ID': node, 'SHOP_NODE_TOKEN': token, 'SHOP_SERVER_URL': server.rstrip('/'),
                  'SHOP_DEVICE_MODE': 'hardware', 'SHOP_HARDWARE_CONFIG': f'runtime/field/{config_name}'}
        contents[f'{node}.env'] = ''.join(f'{key}={shlex.quote(value)}\n' for key, value in values.items())
        template = 'hardware.example.json' if node == 'gateway-c' else 'hardware-yolo.example.json'
        config = json.loads((ROOT / 'config' / template).read_text(encoding='utf-8'))
        config.update(node_id=node, armed=False)
        contents[config_name] = json.dumps(config, ensure_ascii=False, indent=2) + '\n'
    created = []
    for name, content in contents.items():
        path = directory / name
        if path.exists():
            continue
        with path.open('x', encoding='utf-8', newline='\n') as stream:
            stream.write(content)
        if os.name != 'nt':
            path.chmod(0o600)
        created.append(name)
    return created


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='현장 설정 파일 생성 · 기존 파일 보존 · 장비 실행 없음')
    parser.add_argument('--server', required=True, help='관제 PC의 실제 LAN 주소, 예: http://192.168.0.20:8000')
    args = parser.parse_args()
    created = prepare(ROOT / 'runtime' / 'field', args.server)
    print(f'runtime/field: {len(created)}개 생성. 기존 파일과 DB는 유지했습니다.')
    print('각 중계에는 자기 gateway-*.env와 gateway-*.hardware.json만 전달하세요.')
    print('서버 주소 변경 시 기존 gateway-*.env의 SHOP_SERVER_URL을 직접 수정하세요.')
