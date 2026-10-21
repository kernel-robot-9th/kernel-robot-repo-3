from contextlib import contextmanager
from copy import deepcopy
import hashlib
import io
import json
from pathlib import Path
import urllib.request
import zipfile

import pytest

from scripts import model_assets as assets


@pytest.fixture
def packaged(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    cfg = {"type": "act", "chunk_size": 100, "n_action_steps": 100,
           "input_features": {"observation.state": {"shape": [6]},
                              "observation.images.front": {"shape": [3, 480, 640]},
                              "observation.images.wrist": {"shape": [3, 480, 640]}},
           "output_features": {"action": {"shape": [6]}}}
    for name in assets.MODEL_FILES:
        data = json.dumps(cfg if name == "config.json" else {}).encode() if name.endswith(".json") else b"test-weight-data"
        (source / name).write_bytes(data)
    archive, record = assets.package_model(source, tmp_path / "release", "act-left-v2-050000",
                                           "left", 50000, "models-left-v1")
    entry = json.loads(record.read_text())["act-left-v2-050000"]
    manifest = {"schema_version": 1, "repository": "rheffi/cartrina-control", "models": {
        "act-left-v2-050000": entry,
        "act-right-v2": {"selection_status": "pending", "direction": "right"}}}
    return source, archive, entry, manifest


def test_install_all_seven_files_and_repeat_without_overwrite(packaged, tmp_path):
    source, archive, entry, manifest = packaged
    assets.selected(manifest, "act-left-v2-050000")
    target = assets.install_archive(archive, tmp_path / "models", entry)
    assert target == tmp_path / "models/omx_left_act_v2/050000/pretrained_model"
    assert {p.name for p in target.iterdir()} == set(assets.MODEL_FILES)
    assert (target / "model.safetensors").read_bytes() == (source / "model.safetensors").read_bytes()
    timestamps = {p.name: p.stat().st_mtime_ns for p in target.iterdir()}
    assert assets.install_archive(archive, tmp_path / "models", entry) == target
    assert timestamps == {p.name: p.stat().st_mtime_ns for p in target.iterdir()}


def test_wrong_checksum_and_incomplete_download_never_install(packaged, tmp_path):
    _, archive, entry, _ = packaged
    archive.write_bytes(archive.read_bytes()[:-5])
    with pytest.raises(assets.AssetError, match="ZIP"):
        assets.install_archive(archive, tmp_path / "models", entry)
    assert not (tmp_path / "models").exists()


def test_corrupt_existing_installation_is_preserved(packaged, tmp_path):
    _, archive, entry, _ = packaged
    target = assets.install_archive(archive, tmp_path / "models", entry)
    sentinel = target / "model.safetensors"
    sentinel.write_bytes(b"different checkpoint: do not replace")
    with pytest.raises(assets.AssetError, match="model.safetensors"):
        assets.install_archive(archive, tmp_path / "models", entry)
    assert sentinel.read_bytes() == b"different checkpoint: do not replace"


@pytest.mark.parametrize("filename", ["../escape.txt", "pretrained_model/../../escape.txt", "/escape.txt"])
def test_zip_paths_cannot_escape_installation(packaged, tmp_path, filename):
    _, _, entry, _ = packaged
    archive = tmp_path / "malformed.zip"
    with zipfile.ZipFile(archive, "w") as zipped:
        zipped.writestr(filename, b"escape")
    entry = deepcopy(entry)
    entry["release"].update(size=archive.stat().st_size, sha256=assets.sha256(archive))
    with pytest.raises(assets.AssetError, match="7개"):
        assets.install_archive(archive, tmp_path / "models", entry)
    assert not (tmp_path / "escape.txt").exists()
    assert not (tmp_path / "models").exists()


def test_file_checksum_is_checked_even_if_zip_checksum_matches(packaged, tmp_path):
    source, _, entry, _ = packaged
    archive = tmp_path / "tampered.zip"
    with zipfile.ZipFile(archive, "w") as zipped:
        for name in assets.MODEL_FILES:
            data = (source / name).read_bytes()
            if name == "model.safetensors":
                data = b"x" * len(data)
            zipped.writestr("pretrained_model/" + name, data)
    entry = deepcopy(entry)
    entry["release"].update(size=archive.stat().st_size, sha256=assets.sha256(archive))
    with pytest.raises(assets.AssetError, match="model.safetensors"):
        assets.install_archive(archive, tmp_path / "models", entry)
    assert not assets.target_directory(tmp_path / "models", entry).exists()


def test_unselected_right_model_cannot_install(packaged):
    with pytest.raises(assets.AssetError, match="선정 전"):
        assets.selected(packaged[3], "act-right-v2")


def test_model_root_traversal_is_rejected(packaged, tmp_path):
    entry = deepcopy(packaged[2])
    entry["install_subdir"] = "../outside/pretrained_model"
    with pytest.raises(assets.AssetError, match="상대 경로"):
        assets.target_directory(tmp_path / "models", entry)


def test_secrets_block_public_packaging(packaged, tmp_path):
    source = packaged[0]
    (source / "train_config.json").write_text(json.dumps({"wandb": {"api_key": "private"}}))
    with pytest.raises(assets.AssetError, match="비밀"):
        assets.package_model(source, tmp_path / "secret-release", "act-left-v2-050000", "left", 50000, "v2")
    assert not (tmp_path / "secret-release").exists()


def test_download_uses_release_identity_and_checked_cache(packaged, tmp_path, monkeypatch):
    _, archive, entry, manifest = packaged
    calls = []
    release = {"tag_name": entry["release"]["tag"], "draft": False,
               "assets": [{"id": 123, "name": archive.name, "size": archive.stat().st_size}]}

    @contextmanager
    def request(url, accept="application/vnd.github+json"):
        calls.append((url, accept))
        payload = json.dumps(release).encode() if len(calls) == 1 else archive.read_bytes()
        yield io.BytesIO(payload)

    monkeypatch.setattr(assets, "request", request)
    cached = assets.download_archive(manifest, entry, tmp_path / "cache")
    assert cached.read_bytes() == archive.read_bytes()
    assert calls[-1][0] == "https://api.github.com/repos/rheffi/cartrina-control/releases/assets/123"
    assert calls[-1][1] == "application/octet-stream"
    assert assets.download_archive(manifest, entry, tmp_path / "cache") == cached
    assert len(calls) == 2


def test_partial_network_download_is_not_left_as_a_valid_archive(packaged, tmp_path, monkeypatch):
    _, archive, entry, manifest = packaged
    calls = []

    @contextmanager
    def request(url, accept="application/vnd.github+json"):
        calls.append(url)
        release = {"tag_name": entry["release"]["tag"], "draft": False,
                   "assets": [{"id": 123, "name": archive.name, "size": archive.stat().st_size}]}
        yield io.BytesIO(json.dumps(release).encode() if len(calls) == 1 else b"truncated")

    monkeypatch.setattr(assets, "request", request)
    with pytest.raises(assets.AssetError, match="ZIP"):
        assets.download_archive(manifest, entry, tmp_path / "cache")
    assert list((tmp_path / "cache").iterdir()) == []


def test_redirect_strips_github_token_before_asset_host():
    req = urllib.request.Request("https://api.github.com/repos/rheffi/cartrina-control/releases/assets/123",
                                 headers={"Authorization": "Bearer do-not-leak"})
    redirected = assets.SafeRedirect().redirect_request(
        req, None, 302, "Found", {}, "https://release-assets.githubusercontent.com/file")
    assert redirected.get_header("Authorization") is None
    with pytest.raises(assets.AssetError, match="HTTPS"):
        assets.SafeRedirect().redirect_request(req, None, 302, "Found", {}, "http://example.com/file")
