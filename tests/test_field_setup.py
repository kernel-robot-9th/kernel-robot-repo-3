"""Commissioning starts without virtual devices, orders, or synthetic frames."""
from copy import deepcopy
import json

import pytest
from fastapi.testclient import TestClient

from scripts.prepare_field import prepare
from server.api import create_app
from server.distributed import DistributedEngine
from server.video import VideoRegistry
from test_api import bearer
from test_distributed import ADMIN, TOKENS


@pytest.fixture
def field(monkeypatch):
    monkeypatch.delenv('SHOP_VIDEO_CONFIG', raising=False)
    engine = DistributedEngine(mode='hardware', test_only=True)
    try:
        with TestClient(create_app(engine, ADMIN, node_tokens=TOKENS)) as client:
            yield engine, client
    finally:
        engine.store.close()


def test_field_starts_empty_and_keeps_actual_catalog(field):
    engine, client = field
    state = client.get('/api/admin/state', headers=bearer(ADMIN)).json()
    for key in ['sessions', 'orders', 'tasks', 'commands']:
        assert not state[key]
    assert not any(n['connected'] for n in state['gateways'].values())
    assert not any(n['connected'] for n in state['devices'].values())
    assert len(state['products']) == 10
    assert sum(p['stock']['on_hand'] for p in state['products']) == 17
    assert sum(p['stock']['reserved'] for p in state['products']) == 0
    health = client.get('/api/health').json()
    assert health['mode'] == 'hardware' and health['setup_only']
    assert not health['physical_hardware_verified']
    assert health['motion_backend'] == 'external_adapter'
    assert not client.get('/api/products').json()['accepting_sessions']
    assert client.post('/api/sessions', json={'label': '고객'}).status_code == 409
    assert not engine.state['sessions']


def test_field_never_substitutes_synthetic_camera_frames(field):
    _, client = field
    feeds = client.get('/api/admin/video', headers=bearer(ADMIN)).json()['items']
    assert len(feeds) == 5
    for feed in feeds:
        assert feed['transport'] == 'jpeg' and feed['received_at'] is None
        url = '/api/admin/video/' + feed['id']
        assert client.get(url + '/frame', headers=bearer(ADMIN)).status_code == 503
        assert client.post(url + '/mock-fault', headers=bearer(ADMIN), json={'kind': 'none'}).status_code == 409


def test_explicit_mock_video_rejected_for_hardware(field):
    engine, _ = field
    with pytest.raises(RuntimeError, match='가상 영상'):
        create_app(engine, ADMIN, node_tokens=TOKENS, video=VideoRegistry())


def test_diagnostic_connection_is_not_a_live_robot_connection(field):
    engine, client = field
    stock = deepcopy(engine.state['stock'])
    body = {'node_id': 'gateway-a', 'instance_id': 'commissioning-worker-1', 'role': 'test'}
    auth = bearer(TOKENS['gateway-a'])
    assert client.post('/api/nodes/heartbeat', headers=auth, json={**body, 'mode': 'mock'}).status_code == 409
    assert client.post('/api/nodes/heartbeat', headers=auth, json={**body, 'mode': 'hardware'}).status_code == 200
    state = client.get('/api/admin/state', headers=bearer(ADMIN)).json()
    assert state['gateways']['gateway-a']['connected']
    assert state['gateways']['gateway-a']['role'] == 'test'
    assert not any(device['connected'] for device in state['devices'].values())
    assert not state['commands'] and engine.state['stock'] == stock


def test_prepare_field_preserves_secrets_device_edits_and_database(tmp_path):
    assert len(prepare(tmp_path, 'http://192.168.0.20:8000')) == 8
    credentials = (tmp_path / 'credentials.json').read_bytes()
    central = (tmp_path / 'central.env').read_text()
    assert 'SHOP_DEVICE_MODE=hardware' in central and 'SHOP_TEST_ONLY=1' in central
    assert 'runtime/field/shopping.db' in central and 'config/video-field.json' in central
    for node in TOKENS:
        env = (tmp_path / f'{node}.env').read_text()
        config = json.loads((tmp_path / f'{node}.hardware.json').read_text(encoding='utf-8'))
        assert 'SHOP_ADMIN_TOKEN' not in env and 'SHOP_NODE_TOKENS' not in env
        assert f'SHOP_NODE_ID={node}' in env and f'runtime/field/{node}.hardware.json' in env
        assert config['node_id'] == node and not config['armed']
    path = tmp_path / 'gateway-a.hardware.json'
    edited = path.read_text(encoding='utf-8').replace('"calibration_file": null', '"calibration_file": "/actual/calibration.json"')
    path.write_text(edited, encoding='utf-8')
    env_path = tmp_path / 'gateway-a.env'
    env_path.write_text(env_path.read_text().replace('192.168.0.20', '192.168.0.30'))
    (tmp_path / 'shopping.db').write_bytes(b'existing-database')
    assert prepare(tmp_path, 'http://192.168.0.40:8000') == []
    assert path.read_text(encoding='utf-8') == edited
    assert '192.168.0.30' in env_path.read_text()
    assert (tmp_path / 'credentials.json').read_bytes() == credentials
    assert (tmp_path / 'shopping.db').read_bytes() == b'existing-database'


def test_lost_credentials_do_not_regenerate_incompatible_gateway_tokens(tmp_path):
    (tmp_path / 'gateway-a.env').write_text('existing configuration')
    with pytest.raises(ValueError, match='복구'):
        prepare(tmp_path, 'http://192.168.0.20:8000')
    assert not (tmp_path / 'credentials.json').exists()
    assert (tmp_path / 'gateway-a.env').read_text() == 'existing configuration'
