"""Versioned ACT assets. Standard library only; never imports a robot driver."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = ROOT / "config" / "model_assets.json"
MODEL_FILES = (
    "config.json", "model.safetensors", "train_config.json",
    "policy_preprocessor.json", "policy_postprocessor.json",
    "policy_preprocessor_step_3_normalizer_processor.safetensors",
    "policy_postprocessor_step_0_unnormalizer_processor.safetensors",
)
BLOCK = 1024 * 1024


class AssetError(ValueError):
    pass


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(BLOCK), b""):
            digest.update(block)
    return digest.hexdigest()


def relative(value):
    if (not isinstance(value, str) or not value or "\\" in value or ":" in value
            or value.startswith("/") or any(p in {"", ".", ".."} for p in value.split("/"))):
        raise AssetError("모델 상대 경로가 올바르지 않습니다")
    return PurePosixPath(value)


def check_digest(value):
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise AssetError("SHA-256 형식이 올바르지 않습니다")


def selected(manifest, model_id):
    if manifest.get("schema_version") != 1:
        raise AssetError("지원하지 않는 모델 목록 버전입니다")
    if re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", manifest.get("repository", "")) is None:
        raise AssetError("GitHub 저장소 지정이 올바르지 않습니다")
    entry = manifest.get("models", {}).get(model_id)
    if not isinstance(entry, dict):
        raise AssetError(f"모델이 목록에 없습니다: {model_id}")
    if entry.get("selection_status") != "selected":
        raise AssetError(f"선정 전 모델입니다: {model_id}. 오른쪽 체크포인트를 먼저 검증·선정하세요")
    relative(entry["install_subdir"])
    files = entry.get("files", [])
    if len(files) != len(MODEL_FILES) or {f.get("name") for f in files} != set(MODEL_FILES):
        raise AssetError("실행용 모델 파일 7개의 목록이 필요합니다")
    for info in files:
        check_digest(info.get("sha256"))
        if type(info.get("size")) is not int or info["size"] <= 0:
            raise AssetError("모델 파일 크기가 올바르지 않습니다")
    release = entry.get("release", {})
    if not isinstance(release.get("tag"), str) or not release["tag"]:
        raise AssetError("Release 태그가 필요합니다")
    if "/" in str(release.get("asset", "")) or "\\" in str(release.get("asset", "")):
        raise AssetError("Release 파일 이름이 올바르지 않습니다")
    if not release.get("asset"):
        raise AssetError("Release 파일 이름이 필요합니다")
    check_digest(release.get("sha256"))
    if type(release.get("size")) is not int or release["size"] <= 0:
        raise AssetError("Release 파일 크기가 올바르지 않습니다")
    return entry


def policy_info(directory):
    cfg = read_json(Path(directory) / "config.json")
    views = cfg.get("input_features", {})
    expected = {f"observation.images.{view}": [3, 480, 640] for view in ("front", "wrist")}
    if (cfg.get("type") != "act" or cfg.get("n_action_steps") != 100
            or cfg.get("chunk_size") != 100
            or any(views.get(key, {}).get("shape") != shape for key, shape in expected.items())
            or {k for k in views if k.startswith("observation.images.")} != set(expected)
            or views.get("observation.state", {}).get("shape") != [6]
            or cfg.get("output_features", {}).get("action", {}).get("shape") != [6]):
        raise AssetError("현재 ACT 설정(동작 100개·front/wrist·관절 6개)과 다릅니다")
    return {"type": "act", "chunk_size": 100, "n_action_steps": 100,
            "camera_shapes": {"front": [3, 480, 640], "wrist": [3, 480, 640]}}


def verify_files(directory, entry):
    directory = Path(directory).expanduser().resolve()
    for info in entry["files"]:
        path = directory / info["name"]
        if (path.is_symlink() or not path.is_file() or path.resolve().parent != directory
                or path.stat().st_size != info["size"] or sha256(path) != info["sha256"]):
            raise AssetError(f"모델 파일이 없거나 검증에 실패했습니다: {info['name']}")
    if policy_info(directory) != entry["policy"]:
        raise AssetError("모델 설정과 등록된 설정이 다릅니다")
    return directory


def target_directory(root, entry):
    root = Path(root).expanduser().resolve()
    target = root.joinpath(*relative(entry["install_subdir"]).parts)
    if not target.resolve().is_relative_to(root):
        raise AssetError("모델 경로가 설치 루트 밖을 가리킵니다")
    return target


def verify_archive(path, entry):
    path = Path(path)
    release = entry["release"]
    if (not path.is_file() or path.stat().st_size != release["size"]
            or sha256(path) != release["sha256"]):
        raise AssetError("배포 ZIP의 크기 또는 SHA-256이 다릅니다")


def install_archive(path, root, entry):
    verify_archive(path, entry)
    target = target_directory(root, entry)
    if target.exists():
        return verify_files(target, entry)  # Never overwrite an unverified installation.
    expected = {"pretrained_model/" + f["name"]: f for f in entry["files"]}
    with zipfile.ZipFile(path) as archive:
        infos = archive.infolist()
        if len(infos) != len(expected) or {i.filename for i in infos} != set(expected):
            raise AssetError("ZIP에는 pretrained_model의 지정된 7개 파일만 있어야 합니다")
        for info in infos:
            if (stat.S_ISLNK(info.external_attr >> 16) or info.is_dir() or info.flag_bits & 1
                    or info.file_size != expected[info.filename]["size"]):
                raise AssetError("ZIP 파일 형식·크기가 올바르지 않습니다")
        target.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=".model-stage-", dir=target.parent) as temporary:
            stage = Path(temporary).resolve()
            if stage.parent != target.parent.resolve():
                raise AssetError("임시 설치 경로가 올바르지 않습니다")
            unpacked = stage / "pretrained_model"
            unpacked.mkdir()
            for info in infos:
                destination = unpacked / expected[info.filename]["name"]
                with archive.open(info) as source, destination.open("xb") as output:
                    shutil.copyfileobj(source, output, BLOCK)
            verify_files(unpacked, entry)
            if target.exists():
                verify_files(target, entry)
            else:
                unpacked.rename(target)
    return verify_files(target, entry)


class SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        old = urllib.parse.urlparse(req.full_url)
        new = urllib.parse.urlparse(newurl)
        if new.scheme != "https":
            raise AssetError("HTTPS 이외의 다운로드 리디렉션을 거부했습니다")
        redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
        if redirected is not None and (old.hostname, old.port) != (new.hostname, new.port):
            redirected.remove_header("Authorization")
        return redirected


def request(url, accept="application/vnd.github+json"):
    if urllib.parse.urlparse(url).scheme != "https":
        raise AssetError("다운로드에는 HTTPS가 필요합니다")
    headers = {"Accept": accept, "User-Agent": "cartrina-model-preparation"}
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if token and urllib.parse.urlparse(url).hostname == "api.github.com":
        headers["Authorization"] = "Bearer " + token
    req = urllib.request.Request(url, headers=headers)
    return urllib.request.build_opener(SafeRedirect()).open(req, timeout=60)


def download_archive(manifest, entry, cache):
    cache = Path(cache).expanduser().resolve()
    path = cache / entry["release"]["asset"]
    if path.exists():
        verify_archive(path, entry)
        return path
    tag = urllib.parse.quote(entry["release"]["tag"], safe="")
    with request(f"https://api.github.com/repos/{manifest['repository']}/releases/tags/{tag}") as response:
        release = json.load(response)
    if release.get("draft") or release.get("tag_name") != entry["release"]["tag"]:
        raise AssetError("공개된 지정 Release가 아닙니다")
    assets = [a for a in release.get("assets", []) if a.get("name") == path.name]
    if len(assets) != 1 or assets[0].get("size") != entry["release"]["size"]:
        raise AssetError("Release에 해당 모델 파일이 없거나 크기가 다릅니다")
    asset_id = assets[0].get("id")
    if type(asset_id) is not int:
        raise AssetError("Release 파일 ID가 올바르지 않습니다")
    cache.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".model-download-", dir=cache)
    partial = Path(temporary)
    try:
        with os.fdopen(fd, "wb") as output:
            url = f"https://api.github.com/repos/{manifest['repository']}/releases/assets/{asset_id}"
            with request(url, "application/octet-stream") as response:
                received = 0
                while block := response.read(BLOCK):
                    received += len(block)
                    if received > entry["release"]["size"]:
                        raise AssetError("다운로드 크기가 등록된 크기를 초과했습니다")
                    output.write(block)
        verify_archive(partial, entry)
        if path.exists():
            verify_archive(path, entry)
        else:
            partial.rename(path)
        return path
    finally:
        partial.unlink(missing_ok=True)


def reject_secrets(value):
    if isinstance(value, dict):
        for key, child in value.items():
            if key.lower() in {"token", "access_token", "api_key", "password", "secret"} and child:
                raise AssetError("설정에 비밀 값이 있어 공개 패키지를 만들지 않았습니다")
            reject_secrets(child)
    elif isinstance(value, list):
        for child in value:
            reject_secrets(child)


def package_model(source, output, model_id, direction, steps, tag):
    if (re.fullmatch(r"[a-z0-9][a-z0-9-]*", model_id) is None
            or direction not in {"left", "right"} or type(steps) is not int or steps <= 0
            or not tag or "/" in tag or "\\" in tag):
        raise AssetError("모델 ID·방향·스텝·태그를 확인하세요")
    source = Path(source).expanduser().resolve()
    policy = policy_info(source)
    files = []
    for name in MODEL_FILES:
        path = source / name
        if not path.is_file() or path.is_symlink():
            raise AssetError(f"모델 파일이 없습니다: {name}")
        if name.endswith(".json"):
            reject_secrets(read_json(path))
        files.append({"name": name, "size": path.stat().st_size, "sha256": sha256(path)})
    output = Path(output).expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    archive_path = output / (model_id + ".zip")
    entry_path = output / (model_id + ".entry.json")
    if archive_path.exists() or entry_path.exists():
        raise AssetError("출력 파일이 이미 있습니다. 다른 출력 폴더 또는 모델 버전을 지정하세요")
    with zipfile.ZipFile(archive_path, "x", compression=zipfile.ZIP_STORED) as archive:
        for spec in files:
            info = zipfile.ZipInfo("pretrained_model/" + spec["name"], date_time=(1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            with (source / spec["name"]).open("rb") as input_file, archive.open(info, "w") as zipped:
                shutil.copyfileobj(input_file, zipped, BLOCK)
    entry = {"selection_status": "selected", "direction": direction, "policy": policy,
             "checkpoint_steps": steps,
             "install_subdir": f"omx_{direction}_act_v2/{steps:06d}/pretrained_model",
             "release": {"tag": tag, "asset": archive_path.name,
                         "size": archive_path.stat().st_size, "sha256": sha256(archive_path)},
             "files": files}
    verify_files(source, entry)
    entry_path.write_text(json.dumps({model_id: entry}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return archive_path, entry_path
