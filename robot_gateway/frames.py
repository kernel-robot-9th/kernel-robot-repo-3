"""Share already-captured frames; never open a camera in a video transmitter."""
import json
import queue
import subprocess
import threading
import time
import urllib.parse
import urllib.request


class SharedCamera:
    """One capture thread, with the same latest frame offered to vision and preview."""
    def __init__(self, camera, publisher, channel):
        self.camera, self.publisher, self.channel = camera, publisher, channel
        self.closed, self.ready, self.lock = threading.Event(), threading.Event(), threading.Lock()
        self.latest, self.error = None, None
        self.thread = threading.Thread(target=self._read, daemon=True)
        self.thread.start()

    def _read(self):
        try:
            while not self.closed.is_set():
                frame, captured = self.camera.read()
                with self.lock:
                    self.latest = (frame, captured)
                self.publisher.offer(self.channel, frame)
                self.ready.set()
        except Exception as exc:
            self.error = exc
            self.ready.set()

    def read(self):
        if not self.ready.wait(3) or self.error:
            raise RuntimeError('작업대 카메라 수신 실패') from self.error
        with self.lock:
            if not self.latest or time.monotonic() - self.latest[1] > 1:
                raise RuntimeError('작업대 카메라 프레임 만료')
            return self.latest[0].copy(), self.latest[1]

    def close(self):
        self.closed.set()
        self.thread.join(timeout=3)


class LatestFramePublisher:
    """One waiting frame per channel. Encoding and I/O stay off the robot loop."""
    def __init__(self, send, fps=5):
        self.send, self.interval = send, 1 / fps
        self.pending, self.lock = {}, threading.Lock()
        self.closed, self.wakeup = threading.Event(), threading.Event()
        self.dropped, self.sent, self.error = 0, 0, None
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def offer(self, channel, frame, color='BGR'):
        with self.lock:
            if channel in self.pending:
                self.dropped += 1
            self.pending[channel] = (frame.copy(), color, time.monotonic())
        self.wakeup.set()

    def _run(self):
        while not self.closed.is_set():
            self.wakeup.wait(.2)
            self.wakeup.clear()
            with self.lock:
                batch, self.pending = self.pending, {}
            for channel, (frame, color, captured) in batch.items():
                if self.closed.is_set() or time.monotonic() - captured > 1:
                    continue
                try:
                    self.send(channel, frame, color)
                    self.sent += 1
                    self.error = None
                except Exception as exc:
                    self.error = type(exc).__name__  # Do not expose URLs containing publish credentials.
            self.closed.wait(self.interval)

    def close(self):
        self.closed.set(); self.wakeup.set()
        self.thread.join(timeout=4)


class JpegSender:
    def __init__(self, base, token, instance, overview=False):
        self.base, self.token, self.instance, self.overview = base.rstrip('/'), token, instance, overview
        self.sequence = 0
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def __call__(self, channel, frame, color):
        import cv2
        if color == 'RGB':
            frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
        height, width = frame.shape[:2]
        if width > 640:
            frame = cv2.resize(frame, (640, round(height * 640 / width)))
        ok, encoded = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 65])
        if not ok or len(encoded) > 512 * 1024:
            raise ValueError('preview encoding failed')
        self.sequence += 1
        route = '/api/video/overview/frame' if self.overview else f'/api/nodes/video/{channel}/frame'
        params = urllib.parse.urlencode({'instance_id': self.instance, 'sequence': self.sequence})
        request = urllib.request.Request(self.base + route + '?' + params, data=encoded.tobytes(),
            headers={'Authorization': 'Bearer ' + self.token, 'Content-Type': 'image/jpeg'})
        with self.opener.open(request, timeout=2) as response:
            response.read(1024)


class RtspSender:
    """Optional FFmpeg H.264 publishing. Called only from LatestFramePublisher."""
    def __init__(self, urls, fps=15):
        self.urls, self.fps, self.processes = urls, fps, {}

    def __call__(self, channel, frame, color):
        import cv2
        if channel not in self.urls:
            raise ValueError('video channel has no RTSP URL')
        if color == 'RGB':
            frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
        frame = cv2.resize(frame, (640, 480))
        process = self.processes.get(channel)
        if process is None:
            process = subprocess.Popen(['ffmpeg', '-nostdin', '-hide_banner', '-loglevel', 'error',
                '-f', 'rawvideo', '-pixel_format', 'bgr24', '-video_size', '640x480', '-framerate', str(self.fps),
                '-i', 'pipe:0', '-an', '-c:v', 'libx264', '-preset', 'ultrafast', '-tune', 'zerolatency',
                '-pix_fmt', 'yuv420p', '-profile:v', 'baseline', '-bf', '0', '-g', str(self.fps),
                '-b:v', '1500k', '-f', 'rtsp', '-rtsp_transport', 'tcp', self.urls[channel]],
                stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self.processes[channel] = process
        if process.poll() is not None:
            raise RuntimeError('video encoder stopped; restart video publisher')
        process.stdin.write(frame.tobytes()); process.stdin.flush()

    def close(self):
        for process in self.processes.values():
            process.terminate()
        for process in self.processes.values():
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
            if process.stdin:
                process.stdin.close()
