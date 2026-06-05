# SOP-MNT-001: Tool Wear Failure (TWF) Response Procedure
<!-- 공구 마모 고장 대응 절차 -->

**Document No:** SOP-MNT-001
**Version:** 1.0
**Applicable Equipment:** All CNC Machining Centers
**Trigger Condition:** Tool wear > 200 min OR TWF flag raised
<!-- 트리거 조건: 공구 마모량 200분 초과 또는 TWF 플래그 발생 -->

---

## 1. Purpose
<!-- 목적 -->

Define an immediate response procedure to prevent machining defects and equipment damage caused by excessive tool wear.
<!-- 공구 마모로 인한 가공 불량 및 설비 손상을 예방하기 위한 즉각 대응 절차를 정의한다. -->

## 2. Scope
<!-- 적용 범위 -->

Applies to all CNC equipment where the tool wear sensor value exceeds 200 min or where the TWF (Tool Wear Failure) flag is triggered by the automated diagnostic system.
<!-- 공구 마모 센서 값이 200분을 초과하거나 자동 진단 시스템에서 TWF 플래그가 발생한 모든 CNC 설비에 적용한다. -->

## 3. Roles and Responsibilities
<!-- 책임과 역할 -->

- **Operator:** Immediately stop the equipment and call the maintenance technician.
<!-- 작업자: 즉각 설비 정지 및 담당 기술자 호출 -->
- **Maintenance Technician:** Perform tool replacement and inspection.
<!-- 유지보수 기술자: 공구 교체 및 검사 수행 -->
- **Quality Engineer:** Conduct sample inspection of recently produced parts.
<!-- 품질 담당자: 직전 생산 부품 샘플 검사 실시 -->

## 4. Response Procedure
<!-- 대응 절차 -->

### 4.1 Immediate Action (within 5 minutes)
<!-- 즉각 조치 (5분 이내) -->

1. **Stop Equipment:** Wait for the current machining cycle to complete, then stop the CNC equipment immediately. Do not use the emergency stop button; wait for the normal cycle to finish.
<!-- 설비 정지: 현재 가공 사이클 완료 후 즉시 CNC 설비를 정지한다. 비상 정지 버튼 사용 금지. -->
2. **Isolate Work Area:** Cordon off the area within 2m of the equipment with safety tape and attach a "Work in Progress" sign.
<!-- 작업 구역 격리: 설비 주변 2m 이내를 안전 테이프로 격리하고 작업 중 표지판을 부착한다. -->
3. **Notify Technician:** Immediately notify the maintenance technician and shift supervisor.
<!-- 기술자 호출: 유지보수 기술자 및 교대 감독자에게 즉시 통보한다. -->

### 4.2 Tool Condition Inspection (within 15 minutes)
<!-- 공구 상태 점검 (15분 이내) -->

4. **Visual Tool Inspection:** Remove the tool from the spindle and visually check for wear, breakage, or chipping.
<!-- 공구 육안 검사: 스핀들에서 공구를 탈착하여 마모, 파손, 치핑 여부를 확인한다. -->
5. **Tool Measurement:** Use a tool presetter to measure actual wear and record it. Discard immediately if wear exceeds the specification (ISO 3685: VB = 0.3 mm).
<!-- 공구 측정: 공구 길이 측정기로 실제 마모량을 측정하고 기록한다. 규격치(ISO 3685 VB=0.3mm) 초과 시 즉시 폐기한다. -->
6. **Spindle Inspection:** Check the tool holder and taper surface for debris, wear, or damage.
<!-- 스핀들 검사: 공구 홀더 및 테이퍼면의 이물질, 마모, 손상을 점검한다. -->

### 4.3 Tool Replacement
<!-- 공구 교체 -->

7. **Install New Tool:** Mount a clean new tool conforming to specifications. Tighten with a torque wrench to the specified torque (refer to machine-specific manual).
<!-- 신규 공구 장착: 규격에 맞는 신규 공구를 청결한 상태로 장착한다. 토크 렌치로 규정 토크 체결. -->
8. **Reset Tool Length Offset:** Re-measure and update the tool length compensation value (Tool Length Offset) in the CNC controller.
<!-- 공구 옵셋 재설정: CNC 제어기에서 공구 길이 보정값을 재측정하여 업데이트한다. -->
9. **Reset Tool Life Counter:** Initialize the tool life management data in the controller.
<!-- 공구 수명 카운터 리셋: 제어기의 공구 수명 관리 데이터를 초기화한다. -->

### 4.4 Trial Run and Resumption
<!-- 시운전 및 복귀 -->

10. **Trial Machining:** Perform one trial cut on scrap material and verify dimensions and surface condition.
<!-- 시운전 가공: 스크랩 소재로 1회 시운전 가공을 실시하여 치수 및 표면 상태를 확인한다. -->
11. **Quality Check:** Sample-inspect at least 3 previously produced parts to determine conformity. If defects are found, perform 100% inspection of the relevant lot.
<!-- 품질 확인: 직전 생산 부품 최소 3개를 샘플 검사한다. 불량 발견 시 해당 로트 전수 검사 실시. -->
12. **Resume Production:** Resume production after supervisor approval.
<!-- 생산 재개: 감독자 승인 후 생산을 재개한다. -->

## 5. Records and Reporting
<!-- 기록 및 보고 -->

- Record the date, equipment number, tool number, wear amount, and replacement reason in the tool replacement logbook.
<!-- 공구 교체 이력 대장에 날짜, 설비 번호, 공구 번호, 마모량, 교체 사유를 기록한다. -->
- Include TWF occurrences in the daily production report submitted to the Production Management team.
<!-- TWF 발생 건은 당일 생산 일보에 포함하여 생산 관리팀에 보고한다. -->
- If TWF occurs 2 or more times per month on the same tool, request a process parameter review.
<!-- 동일 공구에서 월 2회 이상 TWF 발생 시 공정 파라미터 검토를 요청한다. -->

## 6. Escalation Criteria
<!-- 에스컬레이션 기준 -->

Report immediately to the engineering team in the following cases:
<!-- 다음 경우 엔지니어링 팀에 즉시 보고한다. -->
- Suspected internal spindle damage due to tool breakage.
<!-- 공구 파손으로 스핀들 내부 손상이 의심되는 경우 -->
- Dimensional defects persist after trial machining.
<!-- 시운전 가공 후에도 치수 불량이 지속되는 경우 -->
- TWF occurs 3 or more times per week on the same equipment.
<!-- 동일 설비에서 주 3회 이상 TWF 발생 시 -->

---

**Last Revised:** 2026-06-03
**Approved By:** Head of Production Engineering
<!-- 승인자: 생산기술팀장 -->
