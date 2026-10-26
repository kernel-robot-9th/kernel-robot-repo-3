import json
import shutil
import subprocess
import threading
import time

import pytest

from robot_gateway.recording import RecordingPublisher, VideoRecorder


class Frame:
    shape = (48, 64, 3)

    def __init__(self, value=40):
        self.value = value

    def copy(self):
        return Frame(self.value)

    def tobytes(self):
        return bytes([self.value]) * (48 * 64 * 3)


@pytest.mark.skipif(not shutil.which('ffmpeg') or not shutil.which('ffprobe'), reason='FFmpeg required')
def test_shared_frames_produce_playable_mp4_and_explicit_nonphysical_metadata(tmp_path):
    recorder = VideoRecorder(tmp_path, fps=10)
    try:
        recorder.offer('load-a', Frame())
        recorder.wait_ready()
        recorder.offer('load-a', Frame(100))
        time.sleep(.25)
    finally:
        result = recorder.close()
    assert result['status'] == 'RECORDED' and result['frames'] >= 2
    assert result['physical_success_verified'] is False
    probe = json.loads(subprocess.check_output(['ffprobe', '-v', 'error', '-show_streams',
        '-show_format', '-of', 'json', str(recorder.path)]))
    assert (probe['streams'][0]['width'], probe['streams'][0]['height']) == (64, 48)
    assert float(probe['format']['duration']) > 0
    assert json.loads(recorder.path.with_suffix('.json').read_text())['status'] == 'RECORDED'


def test_encoder_failure_is_reported_before_robot_can_be_enabled(tmp_path):
    recorder = VideoRecorder(tmp_path, encoder=str(tmp_path / 'missing-encoder'))
    try:
        recorder.offer('load-a', Frame())
        with pytest.raises(RuntimeError, match='FileNotFoundError'):
            recorder.wait_ready()
    finally:
        result = recorder.close()
    assert result['status'] == 'FAILED'
    assert result['physical_success_verified'] is False


def test_recording_tee_preserves_preview_without_another_capture():
    calls = []
    class Sink:
        def __init__(self, name):
            self.name = name
        def offer(self, channel, frame, color):
            calls.append((self.name, channel, frame, color))
    frame = Frame()
    RecordingPublisher(Sink('preview'), Sink('recording')).offer('load-a', frame)
    assert calls == [('recording', 'load-a', frame, 'BGR'), ('preview', 'load-a', frame, 'BGR')]


def test_invalid_recording_rate_is_rejected_without_starting_encoder(tmp_path):
    with pytest.raises(ValueError):
        VideoRecorder(tmp_path, fps=0)


def test_slow_encoder_does_not_block_camera_or_control_offers(tmp_path, monkeypatch):
    entered, release = threading.Event(), threading.Event()
    class Pipe:
        def write(self, _):
            entered.set()
            assert release.wait(3)
        def flush(self):
            pass
        def close(self):
            pass
    class Encoder:
        stdin = Pipe()
        def poll(self):
            return None
        def wait(self, timeout):
            return 0
        def kill(self):
            release.set()
    monkeypatch.setattr('robot_gateway.recording.subprocess.Popen', lambda *a, **k: Encoder())
    recorder = VideoRecorder(tmp_path)
    try:
        recorder.offer('load-a', Frame())
        assert entered.wait(1)
        began = time.monotonic()
        for _ in range(200):
            recorder.offer('load-a', Frame())
        assert time.monotonic() - began < .25
    finally:
        release.set()
        recorder.close()
