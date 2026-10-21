"""Bounded preview frames. Video observations never advance robot tasks."""
from copy import deepcopy
from html import escape
import json
from pathlib import Path
import threading
import time

from .domain import require

VIDEO_PATH = Path(__file__).resolve().parents[1] / 'config' / 'video.json'
OWNERS = {'overview': 'central', 'load-a': 'gateway-a', 'load-b': 'gateway-b',
          'handoff-front': 'gateway-c', 'handoff-wrist': 'gateway-c'}


class VideoRegistry:
    max_bytes = 512 * 1024
    stale_seconds = 3

    def __init__(self, path=VIDEO_PATH, clock=time.time):
        self.feeds = json.loads(Path(path).read_text(encoding='utf-8'))
        if set(self.feeds) != set(OWNERS):
            raise ValueError('영상 5개 설정을 확인하세요')
        for key, feed in self.feeds.items():
            if feed['owner'] != OWNERS[key] or feed['transport'] not in {'mock', 'jpeg', 'webrtc'}:
                raise ValueError('영상 담당 PC·전송 방식 오류')
            if feed['transport'] == 'webrtc' and not feed.get('whep_url', '').startswith(('http://', 'https://')):
                raise ValueError('WebRTC WHEP URL이 필요합니다')
        self.clock, self.lock, self.frames, self.faults = clock, threading.Lock(), {}, {}

    def describe(self):
        with self.lock:
            return [{**deepcopy(feed), 'id': key, 'mock_fault': self.faults.get(key),
                     'received_at': self.frames.get(key, {}).get('at'),
                     'stale_seconds': self.stale_seconds} for key, feed in self.feeds.items()]

    def _feed(self, key):
        require(key in self.feeds, '영상 채널을 찾을 수 없습니다', 404)
        return self.feeds[key]

    def publish(self, key, owner, instance, sequence, content):
        with self.lock:
            feed = self._feed(key)
            require(feed['owner'] == owner, '다른 PC의 영상 채널입니다', 403)
            require(feed['transport'] == 'jpeg', 'JPEG 수신으로 설정된 채널이 아닙니다')
            require(4 <= len(content) <= self.max_bytes and content.startswith(b'\xff\xd8') and content.endswith(b'\xff\xd9'),
                    'JPEG 형식 또는 크기 제한 오류', 422)
            require(type(sequence) is int and sequence >= 0, '영상 순번 오류', 422)
            previous = self.frames.get(key)
            require(not previous or previous['instance'] != instance or sequence > previous['sequence'], '오래된 프레임입니다')
            self.frames[key] = {'data': content, 'at': self.clock(), 'instance': instance, 'sequence': sequence}

    def fault(self, key, kind):
        with self.lock:
            require(self._feed(key)['transport'] == 'mock', '가상 영상에만 오류 주입 가능')
            require(kind in {'none', 'freeze', 'offline'}, '영상 오류 종류를 확인하세요', 422)
            if kind == 'freeze' and key not in self.frames:
                self._mock_frame(key)
            self.faults[key] = kind

    def _mock_frame(self, key):
        now = self.clock()
        x = 50 + int(now * 50) % 530
        svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="640" height="360" viewBox="0 0 640 360">
          <rect width="640" height="360" fill="#152f35"/><rect x="20" y="70" width="600" height="240" rx="12" fill="#264a50"/>
          <text x="24" y="38" fill="#f3dd9e" font-size="22">MOCK · {escape(self.feeds[key]['label'])}</text>
          <circle cx="{x}" cy="180" r="24" fill="#f1afab"/><text x="24" y="338" fill="white" font-size="16">Synthetic frame · {now:.2f}</text></svg>'''
        self.frames[key] = {'data': svg.encode(), 'at': now, 'instance': 'mock', 'sequence': int(now * 1000)}

    def frame(self, key):
        with self.lock:
            feed = self._feed(key)
            require(self.faults.get(key) != 'offline', '가상 영상 연결 끊김', 503)
            if feed['transport'] == 'mock' and self.faults.get(key) != 'freeze':
                self._mock_frame(key)
            frame = self.frames.get(key)
            require(frame is not None, '수신된 프레임이 없습니다', 503)
            return frame['data'], 'image/svg+xml' if feed['transport'] == 'mock' else 'image/jpeg', {
                'Cache-Control': 'no-store', 'X-Frame-Age': str(max(0, self.clock() - frame['at'])),
                'X-Frame-Sequence': str(frame['sequence']), 'X-Video-Mode': feed['transport']}
