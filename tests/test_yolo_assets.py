import hashlib
import io

import pytest

from scripts.prepare_yolo_model import prepare


def metadata(data):
    return {'model_size': len(data), 'model_sha256': hashlib.sha256(data).hexdigest(),
            'release': {'repository': 'kernel-robot-9th/kernel-robot-repo-3',
                        'tag': 'models-yolo-shopping-v1', 'asset': 'yolo-shopping-best.pt'}}


def test_team_release_download_and_cached_verification(monkeypatch, tmp_path):
    data, requests = b'fake-weight', []
    def fetch(request, timeout):
        requests.append(request.full_url)
        return io.BytesIO(data)
    monkeypatch.setattr('urllib.request.urlopen', fetch)
    path = tmp_path / 'weights/best.pt'
    assert prepare(metadata(data), path) == path
    assert path.read_bytes() == data
    assert requests == ['https://github.com/kernel-robot-9th/kernel-robot-repo-3/releases/download/'
                        'models-yolo-shopping-v1/yolo-shopping-best.pt']
    prepare(metadata(data), path)
    assert len(requests) == 1


def test_bad_download_never_becomes_an_installed_model(monkeypatch, tmp_path):
    monkeypatch.setattr('urllib.request.urlopen', lambda *_args, **_kw: io.BytesIO(b'corrupt'))
    target = tmp_path / 'best.pt'
    with pytest.raises(ValueError, match='SHA-256'):
        prepare(metadata(b'valid'), target)
    assert not target.exists()


def test_offline_install_and_existing_wrong_model_not_overwritten(tmp_path):
    archive, target = tmp_path / 'usb.pt', tmp_path / 'weights/best.pt'
    archive.write_bytes(b'valid')
    prepare(metadata(b'valid'), target, archive)
    assert target.read_bytes() == b'valid'
    target.write_bytes(b'other')
    with pytest.raises(ValueError, match='SHA-256'):
        prepare(metadata(b'valid'), target, archive)
    assert target.read_bytes() == b'other'
