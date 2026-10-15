"""Generate local credentials. Copy only each gateway's own env file to it."""
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
    if parsed.scheme not in {'http', 'https'} or not parsed.hostname or any(c in server for c in "\n\r'\" "):
        raise ValueError('서버 주소는 http(s) URL이어야 합니다')
    directory.mkdir(parents=True, exist_ok=True)
    private = directory / 'credentials.json'
    if private.exists():
        credentials = json.loads(private.read_text(encoding='utf-8'))
    else:
        credentials = {'admin': secrets.token_urlsafe(32), 'nodes': {n: secrets.token_urlsafe(32) for n in profiles()}}
        private.write_text(json.dumps(credentials, indent=2), encoding='utf-8')
    tokens = [credentials['admin'], *credentials['nodes'].values()]
    if (set(credentials['nodes']) != set(profiles()) or
            any(not isinstance(t, str) or len(t) < 16 for t in tokens) or len(set(tokens)) != len(tokens)):
        raise ValueError('기존 인증 파일의 중개 목록과 토큰을 확인하세요. 자동 교체하지 않습니다.')
    paths = [private]
    central = directory / 'central.env'
    central.write_text('SHOP_ADMIN_TOKEN=' + shlex.quote(credentials['admin']) + '\nSHOP_GATEWAY_MODE=distributed\n'
                       + 'SHOP_NODE_TOKENS=' + shlex.quote(json.dumps(credentials['nodes'])) + '\n'
                       + 'SHOP_DB=runtime/distributed/shopping.db\n', encoding='utf-8')
    paths.append(central)
    for node, token in credentials['nodes'].items():
        path = directory / (node + '.env')
        path.write_text(f'SHOP_NODE_ID={shlex.quote(node)}\nSHOP_NODE_TOKEN={shlex.quote(token)}\nSHOP_SERVER_URL={shlex.quote(server)}\n', encoding='utf-8')
        paths.append(path)
    if os.name != 'nt':
        for path in paths:
            path.chmod(0o600)
    return credentials


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='로컬 개발용 중개별 인증 파일 생성 · Git 업로드 금지')
    parser.add_argument('--server', default='http://127.0.0.1:8000')
    args = parser.parse_args()
    target = ROOT / 'runtime' / 'distributed'
    prepare(target, args.server)
    print(f'생성 위치: {target}\n중앙 서버에는 central.env, 각 중개에는 자신의 gateway-*.env만 전달하세요.')
