"""Generate private MediaMTX credentials/config; does not install/start a service."""
import argparse
import ipaddress
import json
import os
from pathlib import Path
import secrets

ROOT = Path(__file__).resolve().parents[1]


def prepare(directory, host, web_port=8000):
    ipaddress.IPv4Address(host)
    if not 1 <= web_port <= 65535:
        raise ValueError('웹 포트 범위 오류')
    if directory.exists():
        raise FileExistsError('기존 미디어 인증 설정은 덮어쓰지 않습니다')
    directory.mkdir(parents=True, mode=0o700)
    feeds = json.loads((ROOT / 'config/video.json').read_text(encoding='utf-8'))
    reader = secrets.token_urlsafe(32)
    users = [{'user': 'viewer', 'pass': reader, 'permissions': [{'action': 'read', 'path': key} for key in feeds]}]
    publishers = {}
    for owner in sorted({f['owner'] for f in feeds.values()}):
        password = secrets.token_urlsafe(32)
        channels = [key for key, feed in feeds.items() if feed['owner'] == owner]
        users.append({'user': owner, 'pass': password, 'permissions': [{'action': 'publish', 'path': key} for key in channels]})
        publishers[owner] = {'transport': 'rtsp', 'fps': 15, 'rtsp_urls': {
            key: f'rtsp://{owner}:{password}@{host}:8554/{key}' for key in channels}}
    config = {'logLevel': 'warn', 'authMethod': 'internal', 'authInternalUsers': users,
        'rtsp': True, 'rtspTransports': ['tcp'], 'rtspAddress': ':8554',
        'rtmp': False, 'hls': False, 'srt': False, 'api': False, 'metrics': False,
        'webrtc': True, 'webrtcAddress': ':8889', 'webrtcAllowOrigins': [f'http://{host}:{web_port}'],
        'webrtcLocalUDPAddress': ':8189', 'webrtcAdditionalHosts': [host], 'paths': {key: {} for key in feeds}}
    for key, feed in feeds.items():
        feed.update(transport='webrtc', whep_url=f'http://{host}:8889/{key}/whep', read_user='viewer', read_password=reader)
    files = {'mediamtx.yml': config, 'video.json': feeds, **{owner + '.json': cfg for owner, cfg in publishers.items()}}
    for name, value in files.items():
        path = directory / name
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')  # JSON is valid YAML.
        if os.name != 'nt':
            path.chmod(0o600)
    return len(feeds)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='중앙 PC의 실제 LAN IP로 미디어 설정 생성')
    parser.add_argument('--host', required=True)
    parser.add_argument('--web-port', type=int, default=8000)
    parser.add_argument('--output', type=Path, default=ROOT / 'runtime/media')
    args = parser.parse_args()
    print('채널 설정 생성:', prepare(args.output, args.host, args.web_port), '· 비밀값은 출력하지 않습니다')
