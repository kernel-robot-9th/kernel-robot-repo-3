# 카트리나 · 주문과 로봇 작업 관제

커널아카데미 로보틱스 심화 캠프 9기 3팀 저장소.

고객 2명의 주문·Pinky 배정·OMX 작업·공유 구역·실제 결과 기록을 연결한다. 웹은 Vue 3·TypeScript·Vite, 서버는 FastAPI·SQLite다.

**현장 구성: 관제 PC 1대 + 중계 PC 3대, Pinky 2대, OMX 3대, 카메라 5대.** 기본 모드는 MOCK이다. 실물 어댑터 코드는 준비했지만 현장 장치·좌표·Pinky 주행 연결·완료 관측과 실제 성능 검증은 남아 있다.

- [현장 설치·네트워크·4대 실행·영상·실물 전환 안내](FIELD_SETUP.md)
- [모델 다운로드·검증·새 모델 등록](MODEL_ASSETS.md)
- [YOLO/ACT 코드 통합 기준과 출처](integrations/README.md)

설계·요구사항·회의 자료는 Confluence/Jira에서 관리한다. Git에는 실행 코드와 실행에 필요한 안내를 둔다. 모의 검증 결과를 실제 로봇 동작 성공으로 표시하지 않는다.

## 실행 범위

| 구분 | 현재 구현 |
|---|---|
| 상품 | YOLO 라벨과 일치하는 10종. A 9종 각 1개, B 라이스칩 8개 |
| 주문 | 상품 클릭으로 1개 추가, ×2/×3 표시, 품절·예약 제한, 주문당 최대 6개 |
| 재고 | 접수 시 전체 예약, 확인된 적재만 차감. 서버 재시작으로 초기화하지 않음 |
| 운반 | 고객별 Pinky 1대 유지, 한 차수 최대 3개. 4~6개는 여러 차수로 운반 |
| 취소 | 해당 주문의 장비 명령이 하나라도 전송되기 전만 예약 자동 복구 |
| 하역 | 담기·빈 카트·복귀 확인 → 정책 중지 → 실제 정지·토크 유지 → 팔 이탈 → 출발 |
| 영상 | 전경·적재 A/B·인계 정면/그리퍼 5채널. 가상 프레임, JPEG, 선택적 WebRTC |
| 장비 | 명시적인 MOCK/HARDWARE 분리, 실제 실행은 검증 설정과 실행 옵션 필요 |
| 장비 테스트 | 중계별 응답·설정 검사, OMX 단독 적재/하역 요청·중지·운영자 결과 확인·로그 다운로드 |

추가 주문을 포함한 쇼핑 전체에 별도 6개 제한을 두지는 않는다. 남은 재고 안에서 주문할 수 있으며 같은 로봇이 3개씩 운반한다. 첫 차수 적재 후 고객이 주문을 마감하면 인계와 나머지 차수의 왕복을 진행한다. 각 인계 차수에서 해당 고객 장바구니 준비를 확인한다.

`config/products.json`의 초기 수량은 새 시나리오 기준이다. 현재 재고는 DB의 선반 수량과 예약 수량으로 관리한다. 실물 지원 여부는 별도 검증 목록으로 제한한다. 로봇 인계 완료와 고객 수령 확인은 다른 사실이며 고객 수령 확인 UI/API는 이번 범위에 포함하지 않았다.

## Ubuntu 준비

이 데스크톱은 코드 작성·모의 검사에 사용한다. 현장 실행은 Ubuntu에서 한다. 중앙은 Python 3.11~3.13, Node.js 24.12 이상 24.x, pnpm 11이 필요하다. 모의 중계에는 Python만 필요하다. ACT는 기존 Python 3.10·LeRobot·CUDA 환경을 별도로 유지한다.

```bash
# 처음 받는 PC. 이미 있다면 기존 폴더에서 상태 확인 후 git pull --ff-only
mkdir -p ~/projects
cd ~/projects
git clone https://github.com/kernel-robot-9th/kernel-robot-repo-3.git
cd kernel-robot-repo-3
git status --short
git rev-parse --short HEAD
```

원격에 반영되지 않은 로컬 변경은 pull로 받을 수 없다. 4대 모두 같은 브랜치·커밋을 사용하고, 현장 수정 파일이 있으면 강제로 덮어쓰지 않는다.

필요한 기본 도구는 `git`, `python3-venv`, `python3-pip`이다. Node/pnpm이 이미 호환 버전이면 재설치하지 않는다. Node 버전 관리 도구를 쓰는 경우 [nvm 공식 안내](https://github.com/nvm-sh/nvm#installing-and-updating)를 따른다. ROS에 맞춰 설치된 시스템 Python을 교체하지 않는다.

```bash
# 중앙 PC
bash scripts/setup_ubuntu.sh
bash scripts/verify_ubuntu.sh

# 중계 A/B/C에서 각각 — MOCK 준비
bash scripts/setup_gateway.sh
```

검증은 단위시험·웹 빌드·별도 프로세스 HTTP 모의 실행을 수행한다. 결과는 `reports/verification.json`과 같은 디렉터리 로그에 남는다. 실제 4대 LAN 통신이나 물리 장비 시험을 대신하지 않는다.

중앙 인증 파일 생성, 공유기 연결, 중계별 실행 명령은 [FIELD_SETUP.md](FIELD_SETUP.md)의 순서로 진행한다. 고객 화면은 `http://중앙LAN주소:8000/shop`, 관제는 `/admin`이다. 테스트용 자동 실행과 수동 한 단계 실행을 구분한다. 인증 파일·장치 설정·모델 파일은 Git에 올리지 않는다.

## 모델과 실물 연결

```bash
python scripts/prepare_yolo_model.py
python scripts/prepare_models.py download --model act-left-v2-050000 --root ~/omx_models
python scripts/prepare_models.py verify --model act-left-v2-050000 --root ~/omx_models
```

다운로드는 로봇을 실행하지 않는다. 왼쪽 ACT는 v2 5만 스텝·n_action_steps 100·최대 180초다. 오른쪽은 선정 전이므로 준비되지 않은 방향 요청을 거부한다. 180초 경과나 프로세스 종료만으로 성공을 기록하지 않는다.

실물 중계는 `robot_gateway/hardware/`, ACT 실행부는 `robots/omx_act/runtime.py`, YOLO 도구는 `robots/omx_yolo/`에 있다. A/B는 YOLO 인식과 보정된 집기·놓기 궤적, C는 로컬 정면·그리퍼 프레임으로 ACT 추론을 수행한다. 같은 프레임을 별도 전송 스레드에 공유한다. YOLO를 동작 생성 정책으로 취급하지 않는다.

실제 Pinky 어댑터와 적재·담기·비움·팔 이탈 관측 생성부는 현장 코드로 연결해야 한다. 확인하지 않은 ROS 토픽·서비스·액션 이름을 가정하지 않았다. 팔 정지 피드백과 카메라/관절 기준도 현장에서 검증해야 한다. 전체 맵 카메라 기반 위치 추정·디지털 트윈 정합은 후속 작업이다.

## 개발 검증 기록 — 2026-10-22

- Python 관제·모델 준비 자동시험 121개 통과. 장비 테스트의 인증·중복 방지·주문 격리·중지·복구 검증을 포함한다. 최신 결과는 `scripts/verify_ubuntu.sh`로 확인한다.
- YOLO 오프라인 회귀시험 30개 통과. 가짜 모터로 손목 짧은 회전·복귀·관제 취소와 실제 계획 계산을 확인했다.
- TypeScript 검사와 Vite 빌드 통과.
- 중앙 + 중계 3개를 별도 프로세스로 띄운 HTTP 모의 시험: 두 고객 각각 4개(3+1) 인계, 집기 실패, 통신 끊김 통과.
- 장비 테스트 HTTP 모의 통합 8개 항목 통과: 중계 3개 응답, 설정 검사, 적재 확인·해제, 하역 관측·정지, 중지 수신 구분, 실패, 연결 끊김, 주문 재고 보존.
- YOLO 모델 SHA-256 및 중계 모듈의 Python 3.10 문법 검사 통과.
- 실제 OMX/Pinky, Ubuntu 4대 LAN, 카메라 5개 동시 전송, ACT 추론 성능, 브라우저 영상 재생은 미검증.

관제의 **장비 테스트** 탭은 주문을 만들지 않고 중계 명령·응답을 확인한다. 일반 모의 중계에서도 사용할 수 있다. 실물은 [현장 안내 8번](FIELD_SETUP.md#8-장비-테스트-탭으로-omx-단독-연결)의 시험 전용 실행부를 사용한다. Pinky 없이 시작할 수 있지만 실제 바구니 고정과 OMX 설정은 필요하다. 운영자 확인은 자동 비전 판정과 구별해서 저장한다. `python scripts/demo_device_tests.py`는 중앙+중계 3개의 HTTP 모의 통합 시험을 수행한다.

이 수치는 개발 PC의 코드·모의 검증 결과다. 현장에서는 사용한 코드·모델·배치와 실제 성공/실패 결과를 별도로 남긴다.

## 팀 저장소 통합 이후

최종 배포는 `kernel-robot-9th/kernel-robot-repo-3`의 `main`과 같은 저장소의 모델 Releases를 기준으로 한다. 기존 개인 `rheffi/cartrina-control`, `rheffi/omxtest`, `rheffi/omx-imitation-project`는 실험 이력을 보존하며 변경을 자동 반영하지 않는다. [폴더별 출처와 반영 절차](integrations/README.md)를 따른다.

Pinky 실제 주행 코드는 아직 없으며 [연결 대기 항목](robots/pinky/README.md)을 확인한다. 개인 Isaac 프로젝트와 초기 기획·회의 문서는 이 저장소에 포함하지 않는다.

YOLO 도구를 수정했다면 NumPy가 있는 개발 환경에서 저장소 루트 기준으로 다음 검사도 실행한다. 카메라·모터·모델 파일은 사용하지 않는다.

```bash
python -B -m unittest discover -s robots/omx_yolo/tests
```
