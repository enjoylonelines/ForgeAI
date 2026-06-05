# SOP-MNT-004: Overstrain Failure (OSF) Response Procedure
<!-- 오버스트레인 고장 대응 절차 -->

**Document No:** SOP-MNT-004
**Version:** 1.0
**Applicable Equipment:** All CNC Machining Centers (threshold values differ by machine type L/M/H)
**Trigger Condition:** Tool wear × Torque exceeds machine-type threshold, OR OSF flag raised
<!-- 트리거 조건: 공구 마모량 × 토크가 설비 타입별 임계값 초과, 또는 OSF 플래그 발생 -->

---

## 1. Purpose
<!-- 목적 -->

Prevent overstrain failures caused by the combined effect of tool wear and excessive cutting torque, and avoid structural damage to the equipment and tooling.
<!-- 공구 마모와 과도한 절삭 토크의 복합 작용으로 발생하는 오버스트레인 고장을 예방하고 설비와 공구의 구조적 손상을 방지한다. -->

## 2. OSF Threshold Values by Machine Type
<!-- 설비 타입별 OSF 임계값 -->

| Machine Type | Tool Wear × Torque Threshold |
|--------------|------------------------------|
| L (Light)    | Exceeds 11,000 min·Nm        |
| M (Medium)   | Exceeds 12,000 min·Nm        |
| H (Heavy)    | Exceeds 13,000 min·Nm        |

<!-- L: 11,000 min·Nm 초과 / M: 12,000 min·Nm 초과 / H: 13,000 min·Nm 초과 -->

## 3. Immediate Action
<!-- 즉각 조치 -->

1. **Immediate Feed Hold:** Stop axis feed immediately using the Feed Hold button. Keep the spindle rotating and move the tool to a safe position.
<!-- 즉각 이송 정지: Feed Hold 버튼으로 축 이송을 즉시 정지한다. 스핀들은 회전 유지하며 안전 위치로 이동. -->
2. **Operator Safety:** After spindle stop, close the equipment safety door and move to the control panel position.
<!-- 안전 대피: 스핀들 정지 후 안전 도어를 닫고 제어반 위치로 이동한다. -->
3. **Stop Spindle:** Stop the spindle after confirming the tool is in a safe position.
<!-- 스핀들 정지: 안전 위치 이동 확인 후 스핀들을 정지시킨다. -->

## 4. Damage Inspection
<!-- 손상 점검 -->

4. **Check Tool Breakage:** Remove the tool and visually inspect for breakage. If the tool is broken, discard the workpiece as fragments may be embedded inside.
<!-- 공구 파손 여부 확인: 공구를 탈착하여 육안 검사. 파손 시 소재 내부에 파편 가능성이 있으므로 소재를 폐기한다. -->
5. **Inspect Spindle Torque Sensor:** Check the torque sensor for anomalies. In case of over-torque, measure spindle runout considering possible bearing damage.
<!-- 스핀들 토크 센서 점검: 과토크 발생 시 베어링 손상 가능성을 고려하여 스핀들 런아웃을 측정한다. -->
6. **Check Workpiece Clamp:** Verify that overstrain has not caused clamp loosening.
<!-- 가공물 클램프 점검: 오버스트레인으로 인해 클램프 이완이 발생했는지 확인한다. -->
7. **Inspect Machine Structure:** Check for abnormal play or vibration in the feed axes (X/Y/Z) and ballscrews.
<!-- 설비 구조 점검: 이송 축 및 볼스크류에 비정상적인 유격이나 진동이 발생하는지 점검한다. -->

## 5. Cutting Condition Review
<!-- 절삭 조건 재검토 -->

8. **Review Machining Program:** Examine the cutting conditions (F, S, depth of cut) at the relevant section in the NC program and compare against the standard condition table.
<!-- 가공 프로그램 검토: NC 프로그램 해당 구간의 절삭 조건을 표준 조건표와 비교한다. -->
9. **Reset Tool Life:** Review whether the current tool life setting is appropriate for the actual operating environment and shorten it by 20% if necessary.
<!-- 공구 수명 재설정: 현재 공구 수명 설정값이 실제 사용 환경에 적합한지 검토하고 필요시 20% 단축한다. -->
10. **Optimize Cutting Conditions:** In high-torque sections, reduce feed rate by 15–25% or consider separating roughing and finishing operations.
<!-- 절삭 조건 최적화: 토크가 높은 구간에서는 이송 속도를 15~25% 줄이거나 황삭/정삭 분리를 검토한다. -->

## 6. Return to Operation Procedure
<!-- 복귀 절차 -->

11. **Install New Tool and Set Offset:** Replace the tool and reset the offset per SOP-MNT-001 Section 4.3.
<!-- 신규 공구 장착 및 옵셋 설정: SOP-MNT-001의 4.3항에 따라 공구를 교체하고 옵셋을 재설정한다. -->
12. **Dry Run:** Verify the program path with a dry run (no workpiece).
<!-- 시운전 가공(공절삭): 소재 없이 공절삭으로 프로그램 경로를 확인한다. -->
13. **Low-Speed Trial Run:** Perform a trial cut at 30% feed override, then gradually return to normal speed.
<!-- 저속 시운전: 이송 오버라이드 30%로 시운전 가공 후 정상 속도로 단계적 복귀한다. -->

## 7. Escalation Criteria
<!-- 에스컬레이션 기준 -->

- Spindle runout exceeds 0.01 mm — request spindle service immediately.
<!-- 스핀들 런아웃 0.01mm 초과 측정 시 즉시 스핀들 서비스 요청 -->
- Ballscrew backlash exceeds allowable value — request replacement.
<!-- 볼스크류 백래시가 허용값 초과 시 교체 요청 -->
- OSF occurs 2 or more times per week in the same process — initiate full review of process standards.
<!-- 동일 공정에서 주 2회 이상 OSF 발생 시 공정 표준 전면 재검토 -->

---

**Last Revised:** 2026-06-03
**Approved By:** Head of Production Engineering
<!-- 승인자: 생산기술팀장 -->
