# SOP-MNT-005: Random Failure (RNF) Response Procedure
<!-- 랜덤 고장 대응 절차 -->

**Document No:** SOP-MNT-005
**Version:** 1.0
**Applicable Equipment:** All CNC Machining Centers
**Trigger Condition:** Machine failure not classified as TWF/HDF/PWF/OSF, OR RNF flag raised
<!-- 트리거 조건: TWF/HDF/PWF/OSF로 분류되지 않는 머신 고장, 또는 RNF 플래그 발생 -->

---

## 1. Purpose
<!-- 목적 -->

Define a safe and systematic response procedure for unexpected failures that cannot be classified into a specific pattern. RNF originates from probabilistic failures such as component end-of-life, electrical noise, or external impact.
<!-- 특정 패턴으로 분류되지 않는 돌발 고장 발생 시 안전하고 체계적인 대응 절차를 정의한다. RNF는 부품 수명 만료, 전기적 노이즈, 외부 충격 등에 기인한다. -->

## 2. Characteristics and Occurrence Conditions
<!-- 특성 및 발생 조건 -->

RNF (Random Failure) has the following characteristics:
<!-- RNF의 특성 -->
- Occurrence rate: approximately 0.1% of all failures (based on AI4I 2020 dataset)
<!-- 발생 확률: 전체 고장의 약 0.1% (AI4I 2020 기준) -->
- Can occur without specific sensor anomalies
<!-- 특정 센서 이상값 없이 발생 가능 -->
- Root cause analysis is difficult and preventive measures are limited
<!-- 원인 분석이 어려우며 예방 조치가 제한적 -->
- End-of-life of electrical/electronic components is the primary cause
<!-- 전기적/전자적 부품 수명 만료가 주요 원인 -->

## 3. Immediate Action
<!-- 즉각 조치 -->

1. **Stop Equipment:** Immediately stop the equipment and cut the main power supply.
<!-- 설비 정지: 즉시 설비를 정지시키고 주전원을 차단한다. -->
2. **Safety Check:** Confirm operator safety, then isolate the area around the equipment.
<!-- 안전 확인: 작업자 안전 확인 후 설비 주변을 격리한다. -->
3. **Collect Error Codes:** Record all alarms and error codes displayed on the controller.
<!-- 에러 코드 수집: 제어기에 표시된 모든 알람 및 에러 코드를 기록한다. -->
4. **Report Status:** Immediately notify the shift supervisor and Facility Maintenance team.
<!-- 상황 보고: 교대 감독자와 설비보전팀에 즉시 보고한다. -->

## 4. Initial Diagnosis
<!-- 초기 진단 -->

5. **Review Controller Log:** Collect all alarms that occurred within the last 24 hours from the CNC controller alarm history.
<!-- 제어기 로그 확인: CNC 제어기의 알람 이력에서 최근 24시간 이내 발생한 모든 알람을 수집한다. -->
6. **Inspect Power System:** Verify that the input AC voltage and DC bus voltage are within the specified range.
<!-- 전원 계통 점검: 입력 전원 전압(AC)과 DC 버스 전압이 규정 범위 내인지 확인한다. -->
7. **Check Interface Signals:** Inspect PLC I/O signals for any abnormal signals.
<!-- 인터페이스 신호 점검: PLC 입출력 신호에서 이상 신호 유무를 확인한다. -->
8. **Inspect Cable Connections:** Visually inspect major cable connectors for looseness, damage, or broken wires.
<!-- 케이블 연결 상태 점검: 주요 케이블 커넥터의 이완, 손상, 단선 여부를 육안 점검한다. -->

## 5. Component-Level Inspection
<!-- 부품별 점검 -->

9. **Servo Drive Self-Diagnosis:** Run the self-diagnosis function on each axis servo drive and record the results.
<!-- 서보 드라이브 자기진단: 각 축 서보 드라이브의 자기진단 기능을 실행하고 결과를 기록한다. -->
10. **Check Battery Voltage:** Measure the memory backup battery voltage. Replace immediately if below 3V (risk of parameter loss).
<!-- 배터리 전압 확인: 메모리 백업 배터리 전압 측정. 3V 미만 시 즉시 교체 (파라미터 손실 위험). -->
11. **Inspect Fan Motors:** Verify that the control panel cooling fan and drive cooling fans are operating.
<!-- 팬 모터 점검: 제어반 내부 냉각팬, 드라이브 냉각팬의 작동 여부를 확인한다. -->
12. **Inspect I/O Cards:** Check the LED status of input/output expansion cards and record any anomalies.
<!-- I/O 카드 점검: 입출력 확장 카드의 LED 상태를 확인하고 이상 여부를 기록한다. -->

## 6. Reset and Recovery Attempt
<!-- 리셋 및 복귀 시도 -->

13. **Back Up Parameters:** Back up current parameters via USB or RS232 before resetting.
<!-- 파라미터 백업: 리셋 전 현재 파라미터를 USB 또는 RS232로 백업한다. -->
14. **Power Reset:** Turn off main power, wait 5 minutes for capacitor discharge, then re-energize.
<!-- 전원 리셋: 주전원을 OFF 후 5분 대기(콘덴서 방전), 재투입한다. -->
15. **Alarm Reset:** Reset controller alarms, then move each axis slowly in JOG mode to verify normal operation.
<!-- 알람 리셋: 제어기 알람 리셋 후 수동 운전 모드(JOG)로 각 축을 천천히 이동시켜 이상 여부를 확인한다. -->
16. **Trial Run:** If assessed as normal, perform a low-speed trial run and monitor for 30 minutes.
<!-- 시운전: 정상으로 판단되면 저속 시운전을 실시하고 30분간 모니터링한다. -->

## 7. Escalation Criteria
<!-- 에스컬레이션 기준 -->

Request professional service if the failure recurs after reset or in the following situations:
<!-- 리셋 후에도 고장이 재현되거나 다음 상황 발생 시 전문 서비스 요청 -->
- Controller screen does not boot normally.
<!-- 제어기 화면이 정상 부팅되지 않는 경우 -->
- Servo drive errors occur repeatedly.
<!-- 서보 드라이브 에러가 반복적으로 발생하는 경우 -->
- Circuit breaker trips when power is applied.
<!-- 전원 투입 시 차단기가 트립되는 경우 -->
- Failure of unknown cause cannot be resolved in-house.
<!-- 원인 불명 고장으로 자체 해결이 불가능한 경우 -->

## 8. Preventive Maintenance
<!-- 예방 관리 -->

Preventive maintenance to reduce RNF frequency:
<!-- RNF 빈도를 줄이기 위한 예방 관리 -->
- Control panel filter cleaning: monthly
<!-- 제어반 필터 청소: 월 1회 -->
- Battery replacement: every 3 years or when voltage falls below 4V
<!-- 배터리 교체: 3년 주기 또는 전압 4V 미만 시 -->
- Connector seating check: every 6 months
<!-- 커넥터 체결 상태 확인: 6개월 주기 -->
- Controller software update: per manufacturer recommendation
<!-- 제어기 소프트웨어 업데이트: 제조사 권고 시 -->

---

**Last Revised:** 2026-06-03
**Approved By:** Head of Facility Maintenance
<!-- 승인자: 설비보전팀장 -->
