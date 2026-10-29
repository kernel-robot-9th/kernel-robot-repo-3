import json
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from server.api import create_app
from server.video import VideoRegistry, VIDEO_PATH
from tests.test_api import ADMIN, GATEWAY, bearer


def test_admin_video_upload_does_not_change_jobs(rig, tmp_path):
    engine, _, _ = rig
    from copy import deepcopy
    before = deepcopy(engine.state)
    config = json.loads(VIDEO_PATH.read_text())
    for feed in config.values(): feed['transport'] = 'jpeg'
    path = tmp_path/'video.json'; path.write_text(json.dumps(config))
    with TestClient(create_app(engine, ADMIN, GATEWAY, video=VideoRegistry(path))) as client:
        for channel in config:
            url = f'/api/admin/video/{channel}/frame?instance_id=preview-test&sequence=1'
            assert client.post(url, content=b'\xff\xd8test\xff\xd9').status_code == 401
            assert client.post(url, content=b'\xff\xd8test\xff\xd9', headers=bearer(ADMIN)).status_code == 200
            assert client.get('/api/admin/video/'+channel+'/frame', headers=bearer(ADMIN)).content == b'\xff\xd8test\xff\xd9'
    assert engine.state == before


def test_job_releases_camera_on_failure(tmp_path, monkeypatch):
    import fcntl
    from robot_gateway import station_video as video
    monkeypatch.setattr(video, 'ROOT', tmp_path)
    (tmp_path/'enabled').touch()
    with pytest.raises(RuntimeError):
        with video.camera_job():
            assert video.job_requested()
            with (tmp_path/'camera.lock').open('a') as lock:
                with pytest.raises(BlockingIOError): fcntl.flock(lock, fcntl.LOCK_EX|fcntl.LOCK_NB)
            raise RuntimeError('job failed')
    assert not video.job_requested()
    with (tmp_path/'camera.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX|fcntl.LOCK_NB)
