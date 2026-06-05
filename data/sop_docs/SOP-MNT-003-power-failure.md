# SOP-MNT-003: Power Failure (PWF) Response Procedure
<!-- 전력 고장 대응 절차 -->

**Document No:** SOP-MNT-003
**Version:** 1.0
**Applicable Equipment:** All CNC Machining Centers
**Trigger Condition:** Spindle power consumption (Torque × Rotational Speed) outside allowable range (3,500–9,000 W), OR PWF flag raised
<!-- 트리거 조건: 스핀들 소비 전력(토크 × 회전수)이 허용 범위(3,500~9,000 W) 초과, 또는 PWF 플래그 발생 -->

---

## 1. Purpose
<!-- 목적 -->

Prevent motor burnout, drive damage, and production stoppage caused by spindle motor overload or abnormal power consumption.
<!-- 스핀들 모터 과부하 또는 전력 이상으로 인한 모터 소손, 드라이브 손상 및 생산 중단을 예방한다. -->

## 2. Power Abnormality Criteria
<!-- 전력 이상 판정 기준 -->

Spindle power consumption P = Torque (Nm) × Rotational Speed (rad/s):
<!-- 스핀들 소비 전력 P = 토크(Nm) × 회전수(rad/s) -->
- **Normal range:** 3,500 W ≤ P ≤ 9,000 W
<!-- 정상 범위 -->
- **Low power anomaly (< 3,500 W):** Broken tool, missing workpiece, or incorrect cutting conditions
<!-- 저전력 이상: 공구 파손, 소재 누락, 절삭 조건 오류 -->
- **Overload (> 9,000 W):** Excessive cutting load, tool collision, or excessive feed rate
<!-- 과부하: 과도한 절삭 부하, 공구 충돌, 이송 속도 과다 -->

## 3. Immediate Action
<!-- 즉각 조치 -->

1. **Reduce Feed Rate:** Immediately reduce the feed override to 50%.
<!-- 이송 속도 감소: 이송 오버라이드를 즉시 50%로 감소시킨다. -->
2. **Check Spindle Speed:** Compare current spindle RPM against the commanded value. If the deviation exceeds 10%, temporarily stop the equipment.
<!-- 스핀들 속도 확인: 현재 RPM과 지령값을 비교. 편차 10% 초과 시 설비 일시 정지. -->
3. **Check Current Reading:** Read the real-time spindle current value from the control panel display.
<!-- 전류값 확인: 제어반의 스핀들 전류 디스플레이에서 실시간 전류값을 확인한다. -->

## 4. Root Cause Analysis and Corrective Action
<!-- 원인 분석 및 조치 -->

### 4.1 Overload Response (P > 9,000 W)
<!-- 과부하 대응 -->

4. **Review Cutting Conditions:** Compare the feed rate, depth of cut, and width of cut in the current machining program against design specifications.
<!-- 절삭 조건 검토: 이송 속도, 절입 깊이, 절입 폭을 설계 기준과 비교한다. -->
5. **Inspect Tool Condition:** Check for tool wear or breakage (refer to SOP-MNT-001).
<!-- 공구 상태 점검: 공구 마모 또는 파손 여부를 점검한다 (SOP-MNT-001 참조). -->
6. **Verify Workpiece Hardness:** Confirm that the input material hardness is within the specified range.
<!-- 소재 경도 확인: 투입 소재의 경도가 규격 범위 내인지 확인한다. -->
7. **Optimize Cutting Conditions:** Reduce feed rate by 20% or decrease depth of cut to lower the load.
<!-- 절삭 조건 최적화: 이송 속도를 20% 감소하거나 절입 깊이를 줄여 부하를 낮춘다. -->

### 4.2 Low Power Anomaly Response (P < 3,500 W)
<!-- 저전력 이상 대응 -->

8. **Check Workpiece Clamping:** Verify that the workpiece is properly clamped.
<!-- 소재 클램핑 확인: 소재가 정상적으로 클램핑되어 있는지 확인한다. -->
9. **Inspect Tool Holder:** Check the tool holder for secure seating and absence of looseness.
<!-- 공구 홀더 점검: 공구 홀더의 체결 상태를 확인하고 풀림이 없는지 점검한다. -->
10. **Inspect Spindle Drive:** Check and record the error code on the servo drive.
<!-- 스핀들 드라이브 점검: 서보 드라이브의 에러 코드를 확인하고 기록한다. -->

## 5. Servo Drive Inspection
<!-- 서보 드라이브 점검 -->

11. **Check Error Code:** Read the error code from the spindle drive panel and refer to the manufacturer's manual.
<!-- 에러 코드 확인: 스핀들 드라이브 패널에서 에러 코드를 확인하고 제조사 매뉴얼을 참조한다. -->
12. **Inspect Drive Cooling Fan:** Verify that the drive cooling fan is operating. If the fan is stopped, replace it immediately to prevent drive overheating.
<!-- 드라이브 냉각팬 점검: 팬 정지 시 과열 위험이 있으므로 즉시 교체한다. -->
13. **Verify Parameters:** Confirm that the maximum current limit parameter is set correctly.
<!-- 파라미터 확인: 최대 전류 리밋 파라미터가 올바르게 설정되어 있는지 확인한다. -->

## 6. Return to Operation Procedure
<!-- 복귀 절차 -->

14. **Trial Machining:** Perform one trial cut on scrap material before resuming normal operation.
<!-- 시운전 가공: 정상 복귀 전 스크랩 소재로 1회 시운전 가공을 실시한다. -->
15. **Power Monitoring:** Monitor the power consumption trend for 20 minutes after restarting.
<!-- 전력 모니터링: 재가동 후 20분간 소비 전력 트렌드를 모니터링한다. -->

## 7. Escalation Criteria
<!-- 에스컬레이션 기준 -->

- Spindle drive error cannot be reset.
<!-- 스핀들 드라이브 에러가 리셋되지 않는 경우 -->
- Power consumption exceeds 12,000 W (stop equipment immediately).
<!-- 소비 전력이 12,000 W 초과한 경우 즉시 설비 정지 -->
- Drive replacement or motor insulation resistance measurement is required.
<!-- 드라이브 교체 또는 모터 절연 저항 측정이 필요한 경우 -->

---

**Last Revised:** 2026-06-03
**Approved By:** Head of Electrical Facilities
<!-- 승인자: 전기설비팀장 -->
