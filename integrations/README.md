# 장비 코드 통합 기준

팀 배포 기준은 `kernel-robot-9th/kernel-robot-repo-3`이다. 한 번 clone하면 중앙·중계·장비 소스를 함께 받는다. 하위 폴더는 일반 소스이며 submodule이나 별도 `.git`이 없다.

| 역할 | 코드 위치 | 가져온 기준 |
|---|---|---|
| 중앙 주문·재고·작업 순서 | `server/` | 기존 관제 개발 이력 유지 |
| 고객·관제 화면 | `web/` | 기존 관제 개발 이력 유지 |
| 중계 명령·영상·증거 전달 | `robot_gateway/` | 중앙과 같은 커밋으로 배포 |
| YOLO OMX | [robots/omx_yolo](../robots/omx_yolo/README.md) | `rheffi/omxtest`의 `a187404` |
| ACT OMX | [robots/omx_act](../robots/omx_act/README.md) | 문서·패치 `02aebdd`, 기존 관제 실행부 이동 |
| Pinky | [robots/pinky](../robots/pinky/README.md) | 실제 주행 코드 인수 대기 |

원본 커밋·LeRobot 버전·모델 해시는 [sources.json](sources.json)에 기록한다. 실험 저장소의 변경은 자동 동기화하지 않는다. 실험 → 변경 검토 → 필요한 소스 복사 → 출처 갱신 → 자동시험 → 실물 통합시험 순서로 반영한다. 원본의 `.git`, 가상환경, 녹화 데이터, 장치 설정은 복사하지 않는다.

YOLO의 최신 집기 방향 기록과 손목 짧은 회전 로직을 관제 연결부에도 적용했다. 단독 CLI의 `--park-after`는 최종 토크 OFF까지 수행하지만, 관제 연결부는 작업 후 hold를 유지한다. 단독 CLI 종료·토크 해제를 관제의 적재 확인·팔 이탈·출발 허가로 간주하지 않는다. 실제 적재는 별도 관측으로 확인한다.

ACT 실행 코드는 `robots/omx_act/runtime.py`에 한 번만 둔다. 기존 `robot_gateway.hardware.act`는 호환 import다. LeRobot 자체는 고정 커밋의 외부 의존성이며 라이선스와 로컬 패치를 포함한다. `reference/`는 당시 단독 실행·학습 기록이고, 현재 관제 구현 상태는 루트 README와 FIELD_SETUP을 기준으로 본다.

YOLO와 ACT 가중치는 **팀 저장소 Releases**에서 받는다. 원본 개인 저장소가 없어도 팀 코드와 지정된 Release로 준비할 수 있다. 모델·실물 성공률·카메라 정합은 별도 검증 대상이다.
