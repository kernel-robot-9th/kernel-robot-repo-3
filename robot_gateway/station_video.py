"""Share station preview frames and yield the camera to terminal/remote jobs."""
from contextlib import contextmanager
import fcntl
import os
from pathlib import Path
import time

ROOT = Path('runtime/field/station-video')
_last = {}


def cache_frame(channel, frame, color='BGR'):
    if not (ROOT/'enabled').exists() or time.monotonic()-_last.get(channel, 0) < .2:
        return
    import cv2
    if color == 'RGB':
        frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
    height, width = frame.shape[:2]
    image = cv2.resize(frame, (960, round(height*960/width)))
    temporary = ROOT/f'{channel}.{os.getpid()}.jpg'
    if cv2.imwrite(str(temporary), image):
        temporary.replace(ROOT/f'{channel}.jpg')
        _last[channel] = time.monotonic()


@contextmanager
def camera_job():
    if not (ROOT/'enabled').exists():
        yield
        return
    request = ROOT/f'request-{os.getpid()}'
    request.touch()
    try:
        with (ROOT/'camera.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            yield
    finally:
        request.unlink(missing_ok=True)


def job_requested():
    active = False
    for path in ROOT.glob('request-*'):
        if Path('/proc', path.name.split('-')[-1]).exists():
            active = True
        else:
            path.unlink(missing_ok=True)
    return active
