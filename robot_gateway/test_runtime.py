"""Dedicated commissioning worker: no Pinky commands, diagnostics by default."""
import argparse
import json
import os
from pathlib import Path
import time
import urllib.error
import uuid

from .mock import Client
from .test_agent import TestAgent, HardwareTrials


def main():
    parser = argparse.ArgumentParser(description='OMX 시험 중계. 실물은 --execute 없으면 통신·설정 검사만 수행')
    parser.add_argument('--node', required=True, choices=['gateway-a', 'gateway-b', 'gateway-c'])
    parser.add_argument('--server', default=os.getenv('SHOP_SERVER_URL', 'http://127.0.0.1:8000'))
    parser.add_argument('--mode', choices=['mock', 'hardware'], default='mock')
    parser.add_argument('--config')
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    token = os.getenv('SHOP_NODE_TOKEN', '')
    if len(token) < 16:
        parser.error('해당 중계 SHOP_NODE_TOKEN 필요')
    if args.execute and (args.mode != 'hardware' or os.name != 'posix' or not args.config):
        parser.error('실물 동작은 Ubuntu·hardware 모드·현장 설정이 필요합니다')
    instance = str(uuid.uuid4())
    identity = {'node_id': args.node, 'instance_id': instance, 'mode': args.mode, 'role': 'test'}
    config = json.loads(Path(args.config).read_text(encoding='utf-8')) if args.config else {'node_id': args.node}
    if config.get('node_id') != args.node:
        parser.error('설정과 중계 이름이 다릅니다')
    client = Client(args.server, token)
    lockfile = None
    frames = sender = None
    try:
        if args.mode == 'hardware':
            if os.name != 'posix':
                parser.error('실물 환경 검사는 Ubuntu에서 실행하세요')
            import fcntl
            path = Path('runtime/hardware') / args.node / 'outbox.lock'
            path.parent.mkdir(parents=True, exist_ok=True)
            lockfile = path.open('a+')
            fcntl.flock(lockfile, fcntl.LOCK_EX | fcntl.LOCK_NB)
        client.call('/api/nodes/heartbeat', identity)
        hardware = None
        if args.mode == 'hardware':
            from .frames import JpegSender, LatestFramePublisher, RtspSender
            video = config.get('video') or {}
            sender = RtspSender(video['rtsp_urls'], video.get('fps', 5)) if args.execute and video.get('transport') == 'rtsp' else JpegSender(args.server, token, instance)
            frames = LatestFramePublisher(sender, video.get('fps', 5))
            hardware = HardwareTrials(config, frames, execute=args.execute)
        agent = TestAgent(client, identity, Path('runtime/device-tests') / args.node / (args.mode + '.json'), hardware)
        print(f'{args.node} · {args.mode.upper()} · ' + ('실물 시험 허용 조건 검사' if args.execute else '통신·설정 검사 전용 · 장비 동작 없음' if args.mode == 'hardware' else 'MOCK 모의 동작'), flush=True)
        try:
            while True:
                try:
                    client.call('/api/nodes/heartbeat', identity)
                    agent.tick()
                except urllib.error.HTTPError:
                    raise
                except (urllib.error.URLError, TimeoutError, ConnectionError):
                    pass  # Watchdog cancels outputs; durable outbox is retained.
                time.sleep(.15)
        finally:
            agent.close()
    finally:
        if frames:
            frames.close()
        if sender and hasattr(sender, 'close'):
            sender.close()
        if lockfile:
            lockfile.close()


if __name__ == '__main__':
    main()
