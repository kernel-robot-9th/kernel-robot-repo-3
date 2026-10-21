# 장비 코드 통합 기준

- YOLO: `omx_yolo/tools`는 사용자 실험 저장소 `rheffi/omxtest`의 `667a5af` 소스 사본이다. 중앙 저장소에서 바로 사용하며 원본 저장소의 최신 변경을 자동으로 따라가지 않는다. 실험 변경은 검증한 뒤 이 사본과 `sources.json`을 함께 갱신한다.
- 통합 실행부: `robot_gateway/hardware/yolo.py`가 한 카메라를 공유하고 Pinky별 적재 위치 0·1·2의 저장 자세를 선택한다. 원본 CLI의 단일 drop 동작은 참고·단독 점검용이다. 실제 적재는 명령 전송 뒤 별도 관측을 받아 확인한다.
- ACT: LeRobot은 외부 라이브러리로 설치한다. `sources.json`의 고정 커밋과 `act/omx-wrist-start-position.patch`를 사용한다. 우리 시작·중지·영상 공유 코드는 `robot_gateway/hardware/act.py`에 있으므로 별도 모방학습 문서 저장소를 clone할 필요가 없다.
- 원본 코드 사본에 학습 데이터·캘리·USB 장치 설정을 포함하지 않았다. 모델 `.pt`·`.safetensors`도 Git에서 제외한다. YOLO는 `python scripts/prepare_yolo_model.py`, ACT는 `python scripts/prepare_models.py`로 준비한다.
- 현재 YOLO 모델은 원본 공개 저장소의 고정 커밋에서 내려받는다. 원본 저장소를 폐기하기 전 최종 저장소 Release로 모델을 옮기고 다운로드 주소·해시를 갱신해야 한다. ACT 왼쪽 모델은 이미 최종 저장소 Release에서 받는다.
- **통합 코드의 모의·정적 검증과 실제 팔 검증은 별개다.** 현장 조건과 미구현 관측 항목은 [현장 연결 안내](../FIELD_SETUP.md)에 기록한다.
