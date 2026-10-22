# YOLO·ACT 모델 배포·준비

실행 코드와 모델 버전 목록은 이 저장소에서, 가중치는 [팀 저장소 Releases](https://github.com/kernel-robot-9th/kernel-robot-repo-3/releases)에서 배포한다. 일반 Git에 가중치·녹화 데이터·학습 재개 상태를 커밋하지 않는다. 개인 실험 저장소를 추가로 clone할 필요가 없다.

## YOLO 준비

`models-yolo-shopping-v1` Release의 `yolo-shopping-best.pt`를 크기·SHA-256으로 검증하고 `robots/omx_yolo/weights/best.pt`에 설치한다. 출처·해시·10개 라벨 기준은 `integrations/sources.json`, `robots/omx_yolo/weights/classes.txt`다.

```bash
python3 scripts/prepare_yolo_model.py
# 인터넷이 없는 현장: Release에서 받은 파일을 USB로 옮긴 뒤
python3 scripts/prepare_yolo_model.py --archive /media/USB/yolo-shopping-best.pt
```

이미 정상 파일이 있으면 검증만 한다. 기존 파일이 다른 모델이면 덮어쓰지 않는다. YOLO도 새 모델을 선정하면 새 태그와 해시를 등록하고 테스트한다.

## 현재 등록

| ID | 상태 | 배포 |
| --- | --- | --- |
| `act-left-v2-050000` | 왼쪽 v2 5만, 사용자 선택 모델 | `models-act-left-v2-s050000-v1` Release |
| `act-right-v2` | 체크포인트 선정 전 | 다운로드·실행 대상으로 제공하지 않음 |

목록: [`config/model_assets.json`](config/model_assets.json). 왼쪽 실행용 파일 7개는 약 197MiB다. `n_action_steps=100`, `chunk_size=100`, `front`·`wrist` 각각 RGB 640×480을 유지한다. 이 준비 도구는 로봇을 실행하지 않으며 실제 성공률·중지 동작을 검증하지 않는다.

## Ubuntu에서 받기

이 저장소를 받은 폴더에서 실행한다. 다운로드 도구는 Python 3.10 이상 표준 라이브러리만 사용하므로 LeRobot·ROS 가상환경을 바꾸거나 학습 패키지를 설치할 필요가 없다. 실제 추론에는 별도로 확인한 LeRobot·CUDA 환경과 보정·카메라 설정이 필요하다.

```bash
python3 scripts/prepare_models.py list
python3 scripts/prepare_models.py download --model act-left-v2-050000 --root ~/omx_models
python3 scripts/prepare_models.py verify --model act-left-v2-050000 --root ~/omx_models
```

`/home/team2` 사용자라면 최종 모델 위치는 다음과 같다.

```text
/home/team2/omx_models/omx_left_act_v2/050000/pretrained_model/
```

`--root`를 생략하면 저장소의 `runtime/models/`에 설치한다. 다운로드 ZIP 캐시는 `runtime/model-cache/`다. 두 폴더는 Git에서 제외된다. 같은 모델이 이미 정상 설치됐으면 검증만 하며, 내용이 다르면 덮어쓰지 않고 실패한다.

성공 출력은 `status=files_verified`, `robot_started=false`, `physical_hardware_verified=false`다. 이 출력은 파일 준비 결과이며 하역 성공·로봇 연결 결과가 아니다.

공개 Release 다운로드는 GitHub 로그인이 필요 없다. API 사용량 제한에 걸리거나 저장소를 비공개로 바꿨다면 접근 권한이 있는 `GH_TOKEN` 또는 `GITHUB_TOKEN` 환경변수를 사용할 수 있다. 토큰을 명령 인자·URL·Git 파일에 넣지 않는다.

## 인터넷 없는 현장에 USB로 전달

Release의 `act-left-v2-050000.zip`과 최신 코드를 인터넷이 되는 곳에서 받은 뒤 옮긴다. 아래 `/media/...`는 실제 USB 경로로 바꾼다.

```bash
python3 scripts/prepare_models.py download --model act-left-v2-050000 --archive /media/USB/act-left-v2-050000.zip --root ~/omx_models
python3 scripts/prepare_models.py verify --model act-left-v2-050000 --root ~/omx_models
```

ZIP 전체와 내부 파일 7개의 크기·SHA-256을 확인한 뒤 임시 폴더에서 검증하고 최종 위치로 옮긴다. 불완전한 다운로드·잘못된 ZIP 경로·파일 손상은 정상 설치로 취급하지 않는다. 목록의 SHA-256을 지워서 우회하지 말고, 올바른 패키지와 코드 버전을 다시 확인한다.

## 선정한 모델을 새로 배포할 때

개별 실물 시험 → 사용할 체크포인트 선정 → 패키지·파일 검증 → 같은 저장소의 새 Release → 통합 시험 순서다. 자동으로 가장 높은 스텝이나 최신 모델을 선택하지 않는다.

현재 v2 모델의 예시다. `--source`는 해당 PC의 실제 폴더로 바꾼다. 생성 위치가 이미 있으면 덮어쓰지 않는다.

```bash
python3 scripts/package_model.py \
  --source /path/to/selected/pretrained_model \
  --model act-left-v2-050000 \
  --direction left \
  --steps 50000 \
  --tag models-act-left-v2-s050000-v1
```

1. `runtime/model-releases/`의 ZIP과 `.entry.json`을 확인한다. 이 명령은 업로드하지 않는다.
2. `.entry.json`의 항목을 `config/model_assets.json`에 반영하고 원본 커밋·모델 선택 근거를 기록한다. 현재 모델과 다른 내용이면 새 모델 ID·태그·설치 경로를 사용한다.
3. 로컬 ZIP을 `--archive`로 설치·검증한다. 모델 7개만 포함하며 학습 재개용 optimizer·녹화 데이터는 배포하지 않는다.
4. GitHub Release에 ZIP을 첨부하고 공개한 뒤 새 폴더로 실제 다운로드·검증한다. 가중치를 일반 Git에 넣지 않는다.
5. 코드 커밋과 Release 태그·모델 SHA-256을 묶어서 통합 시험 결과를 남긴다. 오른쪽도 선정 후 같은 절차를 적용한다.

필수 파일:

```text
pretrained_model/
├── config.json
├── model.safetensors
├── train_config.json
├── policy_preprocessor.json
├── policy_postprocessor.json
├── policy_preprocessor_step_3_normalizer_processor.safetensors
└── policy_postprocessor_step_0_unnormalizer_processor.safetensors
```

기준 왼쪽 가중치 SHA-256:

```text
b62259fd5c1871f53779fec98ec18e700d69e4c0cd6065697a1326284df8e8c5
```

출력·캐시·모델 폴더는 Git에서 제외한다. 새 모델을 추가할 때도 상대 경로를 검토하고 현장 보정·토큰·로컬 기록을 패키지에 넣지 않는다.
