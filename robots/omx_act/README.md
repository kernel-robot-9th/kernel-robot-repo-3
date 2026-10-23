# ACT OMX 하역 실행부

`runtime.py`는 중앙 명령에 따라 로컬 정면·그리퍼 카메라로 ACT를 추론하고 팔을 제어한다. 중계 진입점은 저장소 루트에서 `python -m robot_gateway.hardware.worker`다. 실행 옵션·인증·실물 전환은 [FIELD_SETUP](../../FIELD_SETUP.md)을 따른다.

- 왼쪽: ACT v2 50,000 스텝, `n_action_steps=100`, 최대 180초.
- 오른쪽: 30k~70k 평가 후보가 있으나 사용할 체크포인트 미선정. 준비되지 않은 방향의 명령은 거부한다.
- 시간 만료, 빈 카트, CLI 정상 종료만으로 성공 처리하지 않는다. 마지막 물건 담기·카트 비움·대기 자세를 확인한 뒤 정책 종료와 실제 정지·토크 유지 피드백을 구분한다.
- 대기 자세 근접 판정은 `standby_tolerance`, 정책 종료 후 실제 관절 정지 판정은 더 작은 `position_tolerance`를 사용한다. 대기 자세 오차를 넓히더라도 정지 판정은 느슨해지지 않는다.
- 카메라는 현장 실행부에서 한 번 열고 로컬 추론과 관제 전송이 프레임을 공유한다. 관제에서 돌아온 영상을 추론 입력으로 사용하지 않는다.

## 의존성과 모델

LeRobot `8fff0fde7c79f23a93d845d1a50e985de01f8b8a` / 0.4.4와 `patches/omx-wrist-start-position.patch`를 사용한다. 이미 적용한 패치를 중복 적용하지 않는다. `patches/LICENSE.lerobot`에 원본 라이선스를 보존했다. 실제 현장의 Python 3.10·CUDA 환경을 유지하며 중앙 서버 환경과 분리한다.

모델은 [MODEL_ASSETS](../../MODEL_ASSETS.md)의 팀 Release 준비 명령으로 받는다. `/dev/serial/by-id`와 카메라 by-id, 보정, 대기 자세는 현장 값으로 설정한다. 과거 `/dev/omx_follower` 별칭을 그대로 복사하지 않는다.

## 원본 실험 기록

`reference/`는 `rheffi/omx-imitation-project`의 `02aebdd`에서 가져온 기록이다. 당시 모델 평가·녹화·단독 명령을 보존했다. 문서의 과거 경로, v1 데이터, “관제 API 미구현” 표시는 현재 통합 저장소의 실행 지침으로 해석하지 않는다. reference 명령은 각 장치 설정과 환경을 확인한 후 적용한다.

관제 시작·중지·영상 공유 코드와 모의 시험은 있으나, 실제 정책 종료·정지 피드백·자동 완료 관측·카메라 2채널 전송 성능은 현장 통합시험이 필요하다.
