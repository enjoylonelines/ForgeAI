# ForgeAI 단건 분석 화면 1차 디자인 개편 기록

- 작성일: `2026-08-23`
- 대상 화면: `dashboard/pages/01_single.py`
- 작업 브랜치: `codex/refactor-production-evidence-loop`
- 확인 기준 HEAD: `6740009`
- 작업 성격: Streamlit 단건 분석 화면의 정보 구조와 시각 표현 개편

## 목표

기존 단건 분석 화면을 일반적인 Streamlit 분석 페이지가 아니라, 제조 현장에서 설비 이상 여부와 정비 판단을 빠르게 확인하는 **설비 이상 대응 콘솔**로 재구성했다.

방향은 과장된 SCADA/HMI 모사나 미래형 관제 화면이 아니라, 현재 ForgeAI 백엔드가 반환하는 이상 탐지, SOP 검색, 조치 계획, 검증 결과를 현장 의사결정 순서로 전달하는 차분한 산업용 화면이다.

## 변경한 화면 구조

1. 설비 컨텍스트 바
   - 화면명: `설비 이상 대응 콘솔`
   - 설비 ID, 기종, 분석 시각, API 연결 상태, 처리 상태를 상단에 고정된 문맥으로 배치했다.
   - 처리 상태는 `분석 전`, `분석 중`, `결과 완료`, `API 실패`로 구분한다.

2. 최우선 판단 영역
   - 이상 감지 여부, 심각도, 이상 항목 수, 검증 결과, 근거 점수, 에스컬레이션/라우팅을 먼저 보여준다.
   - 사용자가 먼저 읽어야 하는 문장은 `정상인가`, `이상인가`, `검토가 필요한가`에 맞췄다.
   - 기존의 동일한 크기 KPI 카드 나열은 제거했다.

3. 설비 상태 영역
   - API 요청에 실제로 포함되는 5개 센서 값을 표시한다.
   - 공기 온도, 공정 온도, 회전 속도, 토크, 공구 마모를 값과 단위로만 보여준다.
   - 응답에 없는 시계열, 추세선, 정상 범위 그래프는 만들지 않았다.

4. 이상 근거 영역
   - `sensor_id`, 관측값, 정상 범위, 심각도, 이상 설명을 표로 표시한다.
   - 이상 항목이 없을 때는 빈 경고 패널 대신 정상 상태 문구를 표시한다.

5. 참조 SOP 문서 영역
   - 검색 쿼리, 문서명, 검색 관련도, chunk id, 원문 일부를 확인할 수 있게 했다.
   - SOP가 없으면 조치 근거 확인이 필요하다는 상태로 보여준다.

6. 조치 계획 영역
   - P1/P2/P3 우선순위, 단계 번호, 예상 시간, 담당 역할, 조치 내용을 세로 작업 지시 형태로 배치했다.
   - 에스컬레이션 사유는 조치 목록보다 위에 먼저 표시한다.

7. 근거와 검증 영역
   - 검증 결과, 근거 점수, 근거 부족 단계, 검증 방식, 모순 검출 수, correlation ID를 표시한다.
   - 원문 응답과 추적 정보는 접힘 영역으로 제공하되 존재를 숨기지 않았다.

## 시각 설계

- 기본 배경은 저채도 차콜 계열로 변경했다.
- 텍스트는 흰색/회색 고대비 조합을 사용했다.
- 상태 색상은 의미가 있는 경우에만 사용했다.
  - 정상: muted green
  - 주의/검토: amber
  - 위험: restrained red
  - 분석/선택 강조: steel blue
- 보라색, 네온, 글로우, 그라데이션, 유리 효과, 과도한 그림자는 사용하지 않았다.
- 모서리 반경은 4px 이하로 제한했다.
- 공장 사진, 가짜 설비 도면, 가짜 실시간 파형은 추가하지 않았다.

## 유지한 API와 데이터 계약

이번 작업은 화면 표시 계층만 바꿨다.

수정하지 않은 범위:

- FastAPI 백엔드
- 모델/평가 로직
- API 요청/응답 계약
- 데이터셋
- LLM 실행 경로
- SOP 검색/검증 로직

화면은 기존 응답 필드만 소비한다.

- `risk_assessment`
- `anomaly_report`
- `sop_context`
- `action_plan`
- `validation_result`
- `routing_decision`
- `metrics`
- `correlation_id`

## 상태 처리

| 상태 | 표시 방식 |
|---|---|
| 분석 전 | 입력 폼, 실행 버튼, 분석 대기 판단 영역 표시 |
| 분석 중 | 처리 상태를 `분석 중`으로 표시하고 LLM API 호출, SOP 검색, 검증 대기 가능성을 설명 |
| 결과 완료 | 최우선 판단, 설비 상태, 이상 근거, SOP, 조치 계획, 검증 결과 표시 |
| API 실패 | API 연결 상태를 오프라인으로 표시하고 오류 원인과 재시도 필요 상태 표시 |
| 근거 부족 | `0.00`만 보여주지 않고 `근거 확인 필요` 의미를 함께 표시 |

## 검증 결과

실행한 검증:

- `uv run --frozen python -m py_compile dashboard/pages/01_single.py`
  - 결과: 통과
- `python3 -m py_compile dashboard/pages/01_single.py`
  - 결과: 통과
- Streamlit `AppTest`로 `dashboard/pages/01_single.py` 초기 렌더 확인
  - 결과: 예외 0개
- `uv run --frozen pytest tests/test_dashboard_hybrid_results.py`
  - 결과: 5 passed

기본 `python3 -m pytest tests/test_dashboard_hybrid_results.py`는 로컬 기본 파이썬에 `langchain_ollama`가 없어 실패했다. 저장소 의존성 실행 경로인 `uv run --frozen`으로 재검증했다.

## 브라우저 검증

검증 환경:

- 백엔드: `127.0.0.1:8001`
- Streamlit: `127.0.0.1:8501/single`
- 실행 모드: `LLM_MODE=api`
- Ollama: 사용하지 않음

확인한 내용:

- 백엔드 health 응답 정상
  - `llm_provider=api`
  - `llm=ok`
  - `ollama=not_required`
  - `chromadb=ok`
  - SOP chunk 수 37개
- 분석 전 상태 표시 확인
- 분석 중 상태 표시 확인
- 실제 API 이상 결과 표시 확인
  - `tool_wear_min` 이상
  - 검증 결과 `REVIEW`
  - SOP 관련도 표시
  - P1/P2/P3 조치 계획 표시
  - correlation ID 표시
- API 실패 상태 표시 확인
  - 오프라인 API 주소에서 `ConnectionError`와 재시도 필요 상태 표시
- 1280px 폭에서 가로 스크롤 없음
- 1440px 폭에서 가로 스크롤 없음
- 브라우저 콘솔 오류 출력 없음
- raw HTML 노출 없음

정상 결과는 별도 라이브 브라우저 검증 완료로 주장하지 않는다. 브라우저 자동화에서 입력 변경이 Streamlit 위젯에 안정적으로 반영되지 않아, 실제 정상 결과 검증은 완료하지 못했다.

## 캡처 파일

최종 캡처:

- `/Users/hb/.codex/visualizations/2026/08/23/01a02d43-e9f1-7642-bce4-8d59827bfee7/forgeai-final-01-context-judgment.png`
- `/Users/hb/.codex/visualizations/2026/08/23/01a02d43-e9f1-7642-bce4-8d59827bfee7/forgeai-final-02-evidence-sop.png`
- `/Users/hb/.codex/visualizations/2026/08/23/01a02d43-e9f1-7642-bce4-8d59827bfee7/forgeai-final-03-action-validation.png`

## 포트폴리오에서 말할 수 있는 것

- 단건 분석 화면을 설비 이상 대응 콘솔 구조로 재설계했다.
- 백엔드가 반환하는 이상 탐지, SOP 검색, 조치 계획, 검증 결과를 현장 의사결정 순서로 재배치했다.
- API 계약을 바꾸지 않고 기존 응답 필드를 소비하는 표시 계층을 개선했다.
- 실제 API 이상 결과와 API 실패 상태를 로컬 브라우저에서 확인했다.
- 근거 점수, 근거 부족 단계, SOP 관련도, correlation ID를 화면에서 추적 가능하게 했다.

## 포트폴리오에서 주장하면 안 되는 것

- 실제 공장 배포 완료
- 실시간 센서 스트림 구현
- SCADA/HMI 표준 준수 또는 인증
- 모델 성능 개선
- 정비 비용 절감 실증
- SLA 또는 p95/p99 지연 시간 검증
- 정상 결과 라이브 브라우저 검증 완료
- 자동 조치 또는 실제 설비 제어 수행
