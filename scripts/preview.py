"""Owned subprocess supervisor for a loopback-only, in-memory distributed demo."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import urllib.request
import uuid

from prepare_distributed import ROOT, prepare


def read_health(base):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(base + '/api/health', timeout=1) as response:
        return json.load(response)


class PreviewGroup:
    def __init__(self, directory, port=8000, auto=False):
        self.directory, self.port, self.auto = directory, port, auto
        self.base = f'http://127.0.0.1:{port}'
        self.children, self.logs = {}, []
        self.preview_id = str(uuid.uuid4())

    def launch(self, name, args, env):
        log = (self.directory / (name + '.log')).open('ab')
        self.logs.append(log)
        flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        child = subprocess.Popen([sys.executable, *args], cwd=ROOT, env=env,
                                 stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                 creationflags=flags)
        self.children[name] = child
        return child

    def start(self):
        if not (ROOT / 'web' / 'dist' / 'index.html').exists():
            raise RuntimeError('웹 빌드가 필요합니다: web 폴더에서 pnpm run build')
        # Refuse an occupied port; never terminate a pre-existing service.
        with socket.socket() as probe:
            probe.bind(('127.0.0.1', self.port))
        self.credentials = prepare(self.directory, self.base)
        env = os.environ.copy()
        env.update(PYTHONUNBUFFERED='1', PYTHONUTF8='1', SHOP_ADMIN_TOKEN=self.credentials['admin'],
                   SHOP_NODE_TOKENS=json.dumps(self.credentials['nodes']), SHOP_PREVIEW_ID=self.preview_id)
        self.launch('server', ['-m', 'uvicorn', 'server.preview:create_app', '--factory',
                              '--host', '127.0.0.1', '--port', str(self.port), '--log-level', 'warning'], env)
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            if self.children['server'].poll() is not None:
                raise RuntimeError('서버 시작 실패: server.log 확인')
            try:
                if read_health(self.base).get('preview_id') == self.preview_id:
                    break
            except (OSError, ValueError):
                pass
            time.sleep(0.15)
        else:
            raise RuntimeError('서버 시작 시간 초과')
        for node, token in self.credentials['nodes'].items():
            worker_env = os.environ.copy()
            for key in ['SHOP_ADMIN_TOKEN', 'SHOP_NODE_TOKENS', 'SHOP_GATEWAY_TOKEN']:
                worker_env.pop(key, None)
            worker_env.update(SHOP_NODE_TOKEN=token, PYTHONUTF8='1', PYTHONUNBUFFERED='1')
            args = ['-m', 'robot_gateway.runtime', '--node', node, '--server', self.base,
                    '--state', str(self.directory / (node + '-state.json'))]
            if self.auto:
                args.append('--auto')
            self.launch(node, args, worker_env)
        return self

    def close(self):
        for child in reversed(list(self.children.values())):
            if child.poll() is None:
                child.terminate()
                try:
                    child.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait(timeout=5)
        for log in self.logs:
            log.close()

    def __enter__(self):
        try:
            return self.start()
        except BaseException:
            self.close()
            raise

    def __exit__(self, *_):
        self.close()


def main():
    parser = argparse.ArgumentParser(description='Windows/Ubuntu 로컬 화면 미리보기 · 실제 장비 미연결')
    parser.add_argument('action', choices=['start', 'serve', 'stop', 'status'])
    parser.add_argument('--port', type=int, default=8000)
    parser.add_argument('--auto', action='store_true')
    args = parser.parse_args()
    directory = ROOT / 'runtime' / ('preview' if args.port == 8000 else f'preview-{args.port}')
    directory.mkdir(parents=True, exist_ok=True)
    status_file, stop_file = directory / 'status.json', directory / 'stop-request.json'
    previous = json.loads(status_file.read_text(encoding='utf-8')) if status_file.exists() else {}
    if args.action == 'stop':
        stop_file.write_text(json.dumps({'preview_id': previous.get('preview_id')}), encoding='utf-8')
        print('이 미리보기 실행에 종료를 요청했습니다.')
        return
    if args.action == 'status':
        try:
            health = read_health(previous.get('base', f'http://127.0.0.1:{args.port}'))
            print(json.dumps({'running': bool(previous.get('preview_id')) and health.get('preview_id') == previous.get('preview_id'),
                              'base': previous.get('base'), 'mode': health.get('mode')}, ensure_ascii=False))
        except OSError:
            print('미리보기 서버가 실행 중이지 않습니다.')
        return
    if args.action == 'start':
        flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        log = (directory / 'supervisor.log').open('ab')
        command = [sys.executable, str(Path(__file__).resolve()), 'serve', '--port', str(args.port)]
        if args.auto:
            command.append('--auto')
        process = subprocess.Popen(command, cwd=ROOT, stdin=subprocess.DEVNULL, stdout=log,
                                   stderr=subprocess.STDOUT, creationflags=flags)
        log.close()
        deadline = time.monotonic() + 25
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise SystemExit('시작 실패: runtime/preview/supervisor.log 확인')
            if status_file.exists():
                try:
                    current = json.loads(status_file.read_text(encoding='utf-8'))
                    if (current.get('preview_id') != previous.get('preview_id') and
                            read_health(current['base']).get('preview_id') == current.get('preview_id')):
                        print(f'미리보기 준비 완료 · MOCK ONLY\n고객: {current["base"]}/shop\n관리자: {current["base"]}/admin\n종료: python scripts/preview.py stop --port {args.port}')
                        return
                except (OSError, ValueError, KeyError):
                    pass
            time.sleep(0.15)
        raise SystemExit('시작 확인 시간 초과: runtime/preview/supervisor.log 확인')
    with PreviewGroup(directory, args.port, args.auto) as group:
        metadata = {'preview_id': group.preview_id, 'base': group.base,
                    'started_at': datetime.now(timezone.utc).isoformat(), 'mode': 'mock'}
        status_file.write_text(json.dumps(metadata, indent=2), encoding='utf-8')
        print(f'READY · MOCK ONLY · 관리자 토큰은 {directory / "credentials.json"}에서 확인', flush=True)
        while True:
            if stop_file.exists() and json.loads(stop_file.read_text()).get('preview_id') == group.preview_id:
                break
            if any(child.poll() is not None for child in group.children.values()):
                raise RuntimeError('서버 또는 중개 프로세스가 종료됐습니다. 해당 로그를 확인하세요.')
            time.sleep(0.5)


if __name__ == '__main__':
    main()
