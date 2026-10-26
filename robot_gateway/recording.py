"""Record shared camera frames without opening another capture or blocking control."""
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import threading
import time
import uuid


class VideoRecorder:
    def __init__(self, directory, *, fps=10, prefix='capture', encoder='ffmpeg'):
        if type(fps) is not int or not 1 <= fps <= 30:
            raise ValueError('recording fps must be an integer from 1 to 30')
        directory = Path(directory).expanduser().resolve()
        directory.mkdir(parents=True, exist_ok=True)
        prefix = ''.join(c for c in prefix if c.isalnum() or c in '-_')[:80] or 'capture'
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        self.path = directory / f'{prefix}-{stamp}-{uuid.uuid4().hex[:8]}.mp4'
        self.fps, self.encoder = fps, encoder
        self.lock, self.wakeup = threading.Lock(), threading.Event()
        self.closed, self.ready = threading.Event(), threading.Event()
        self.latest, self.error, self.process = None, None, None
        self.frames, self.offered, self.replaced = 0, 0, 0
        self.last_offer = float('-inf')
        self.shape, self.color = None, None
        self.started = time.monotonic()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def offer(self, channel, frame, color='BGR'):
        now = time.monotonic()
        with self.lock:
            if self.closed.is_set() or self.error or now - self.last_offer < 1 / self.fps:
                return
            if self.latest is not None:
                self.replaced += 1
            self.latest = (frame.copy(), color, now)
            self.last_offer = now
            self.offered += 1
        self.wakeup.set()

    def _run(self):
        log = None
        try:
            while not self.closed.is_set():
                self.wakeup.wait(.2)
                with self.lock:
                    sample = self.latest
                if sample is None:
                    continue
                frame, color, captured = sample
                if time.monotonic() - captured > 2:
                    raise RuntimeError('recording camera frames expired')
                if len(frame.shape) != 3 or frame.shape[2] != 3 or color not in {'BGR', 'RGB'}:
                    raise ValueError('recording requires three-channel BGR or RGB frames')
                if self.process is None:
                    self.shape, self.color = tuple(frame.shape), color
                    height, width, _ = self.shape
                    if width % 2 or height % 2:
                        raise ValueError('recording dimensions must be even')
                    log = self.path.with_suffix('.encoder.log').open('wb')
                    self.process = subprocess.Popen([
                        self.encoder, '-nostdin', '-hide_banner', '-loglevel', 'error', '-n',
                        '-f', 'rawvideo', '-pixel_format', color.lower() + '24',
                        '-video_size', f'{width}x{height}', '-framerate', str(self.fps),
                        '-i', 'pipe:0', '-an', '-c:v', 'libx264', '-preset', 'ultrafast',
                        '-crf', '20', '-pix_fmt', 'yuv420p', '-movflags', '+faststart', str(self.path),
                    ], stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=log)
                if tuple(frame.shape) != self.shape or color != self.color:
                    raise ValueError('camera dimensions or color order changed during recording')
                if self.process.poll() is not None:
                    raise RuntimeError('recording encoder exited early')
                began = time.monotonic()
                self.process.stdin.write(frame.tobytes())
                self.process.stdin.flush()
                self.frames += 1
                self.ready.set()
                self.closed.wait(max(0, 1 / self.fps - (time.monotonic() - began)))
        except Exception as exc:
            self.error = type(exc).__name__ + ': ' + str(exc)
            self.ready.set()
        finally:
            if self.process is not None:
                try:
                    self.process.stdin.close()
                except (OSError, ValueError):
                    pass
                try:
                    code = self.process.wait(timeout=8)
                    if code and not self.error:
                        self.error = f'encoder exited with code {code}'
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait()
                    self.error = 'encoder shutdown timed out'
            if log:
                log.close()

    def wait_ready(self, timeout=5):
        if not self.ready.wait(timeout) or self.error or self.frames == 0:
            raise RuntimeError(self.error or 'recording did not receive a frame')

    def close(self):
        self.closed.set()
        self.wakeup.set()
        self.thread.join(timeout=10)
        if self.thread.is_alive():
            if self.process is not None:
                self.process.kill()
            self.thread.join(timeout=2)
            self.error = self.error or 'recording writer shutdown timed out'
        report = {'path': str(self.path), 'fps': self.fps, 'frames': self.frames,
                  'offered': self.offered, 'replaced': self.replaced, 'shape': self.shape,
                  'elapsed_seconds': round(time.monotonic() - self.started, 3),
                  'status': 'FAILED' if self.error or not self.frames else 'RECORDED',
                  'error': self.error, 'physical_success_verified': False}
        self.path.with_suffix('.json').write_text(json.dumps(report, indent=2) + '\n')
        return report

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


class RecordingPublisher:
    def __init__(self, publisher, recorder):
        self.publisher, self.recorder = publisher, recorder

    def offer(self, channel, frame, color='BGR'):
        self.recorder.offer(channel, frame, color)
        self.publisher.offer(channel, frame, color)


def main():
    """Camera-only recording check. Never import or connect a motor driver."""
    import argparse
    parser = argparse.ArgumentParser(description='Camera-only recording check; no robot connection')
    parser.add_argument('--config', required=True, type=Path)
    parser.add_argument('--directory', required=True, type=Path)
    parser.add_argument('--seconds', type=float, default=5)
    parser.add_argument('--fps', type=int, default=10)
    args = parser.parse_args()
    if not 0 < args.seconds <= 60:
        parser.error('camera check duration must be between 0 and 60 seconds')
    config = json.loads(args.config.read_text())['yolo']
    device = config['camera_by_id']
    if not device.startswith('/dev/v4l/by-id/') or not Path(device).exists():
        parser.error('an existing camera by-id path is required')
    import cv2
    camera = cv2.VideoCapture(device, cv2.CAP_V4L2)
    recorder = None
    try:
        if not camera.isOpened():
            raise RuntimeError('camera open failed')
        camera.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
        camera.set(cv2.CAP_PROP_FRAME_WIDTH, config['width'])
        camera.set(cv2.CAP_PROP_FRAME_HEIGHT, config['height'])
        camera.set(cv2.CAP_PROP_FPS, config['fps'])
        recorder = VideoRecorder(args.directory, fps=args.fps, prefix='camera-check')
        end = time.monotonic() + args.seconds
        while time.monotonic() < end:
            ok, frame = camera.read()
            if not ok:
                raise RuntimeError('camera frame read failed')
            if frame.shape[:2] != (config['height'], config['width']):
                raise RuntimeError('camera and calibration dimensions differ')
            recorder.offer('load-a', frame)
        recorder.wait_ready()
    finally:
        camera.release()
        if recorder is not None:
            result = recorder.close()
    if result['status'] != 'RECORDED':
        raise RuntimeError(result['error'] or 'recording failed')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
