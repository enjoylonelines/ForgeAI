# SOP-MNT-002: Heat Dissipation Failure (HDF) Response Procedure
<!-- 방열 불량 대응 절차 -->

**Document No:** SOP-MNT-002
**Version:** 1.0
**Applicable Equipment:** All CNC Machining Centers
**Trigger Condition:** (Air Temperature - Process Temperature) < 8.6 K AND Rotational Speed < 1380 rpm, OR HDF flag raised
<!-- 트리거 조건: 공기 온도와 공정 온도 차이 < 8.6 K AND 회전 속도 < 1380 rpm, 또는 HDF 플래그 발생 -->

---

## 1. Purpose
<!-- 목적 -->

Define a response procedure to prevent spindle overheating, motor damage, and reduced machining accuracy caused by heat dissipation failure.
<!-- 방열 불량으로 인한 스핀들 과열, 모터 손상 및 가공 정밀도 저하를 예방하기 위한 대응 절차를 정의한다. -->

## 2. Trigger Conditions
<!-- 트리거 조건 -->

HDF is diagnosed when both of the following conditions are met simultaneously:
<!-- 다음 두 조건이 동시에 충족될 때 HDF로 판정한다. -->
- The difference between Air Temperature and Process Temperature is less than 8.6 K.
<!-- 공기 온도와 공정 온도의 차이가 8.6 K 미만 -->
- Rotational Speed is less than 1380 rpm.
<!-- 회전 속도가 1380 rpm 미만 -->

These conditions indicate reduced cooling system efficiency or insufficient coolant.
<!-- 이 조건은 냉각 시스템 효율 저하 또는 냉각재 부족을 나타낸다. -->

## 3. Immediate Action (within 10 minutes)
<!-- 즉각 조치 (10분 이내) -->

1. **Reduce Rotational Speed:** Immediately reduce spindle rotational speed to 70% of the current value using the CNC override function.
<!-- 회전 속도 감소: 스핀들 회전 속도를 현재 값의 70%로 즉시 감소시킨다 (CNC 오버라이드 기능 사용). -->
2. **Check Coolant Supply:** Verify the direction and flow rate of the coolant nozzle. If flow is insufficient, inspect the pump settings.
<!-- 절삭유 공급 확인: 절삭유 공급 노즐 방향과 유량을 확인한다. 유량 부족 시 펌프 설정을 점검한다. -->
3. **Increase Temperature Monitoring:** Monitor the temperature display on the control panel at 5-minute intervals.
<!-- 온도 모니터링 강화: 제어반의 온도 디스플레이를 5분 간격으로 모니터링한다. -->

## 4. Cooling System Inspection
<!-- 냉각 시스템 점검 -->

4. **Inspect Coolant Tank:** Check the coolant tank level; replenish immediately if below MIN level. Measure coolant concentration with a refractometer and verify it is within the specified range (5–8%).
<!-- 절삭유 탱크 점검: 레벨 확인, MIN 이하 시 보충. 농도 굴절계로 5~8% 확인. -->
5. **Inspect Coolant Filter:** Check the coolant filter for blockage. Replace if pressure differential exceeds the specification (≥ 0.5 bar).
<!-- 냉각수 필터 점검: 필터 압력 차이가 0.5 bar 이상이면 교체한다. -->
6. **Inspect Cooling Pump:** Check the cooling pump for proper operation, abnormal noise, and vibration.
<!-- 냉각 펌프 점검: 작동 상태, 이상 소음, 진동을 점검한다. -->
7. **Clean Coolant Nozzles:** Use an air gun to clean coolant nozzles blocked by chips or debris.
<!-- 냉각 노즐 청소: 칩과 이물질로 막힌 냉각 노즐을 에어건으로 청소한다. -->

## 5. Spindle Thermal Management Inspection
<!-- 스핀들 열관리 점검 -->

8. **Measure Spindle Temperature:** Use an infrared thermometer to measure the spindle housing temperature. If it exceeds 65°C, stop machining immediately and allow cooling before restarting.
<!-- 스핀들 온도 측정: 적외선 온도계로 측정. 65°C 초과 시 즉시 가공 중단. -->
9. **Inspect Spindle Chiller:** Compare the set temperature and actual output temperature of the spindle cooling unit. If the deviation exceeds 5°C, request chiller service.
<!-- 스핀들 냉각 유닛 점검: 설정 온도와 실제 출력 온도 편차 5°C 초과 시 서비스 요청. -->
10. **Check Ambient Temperature:** Verify that the shop floor temperature is within the equipment specification range (15–30°C).
<!-- 환경 온도 확인: 작업장 온도가 설비 사양 범위(15~30°C) 내인지 확인한다. -->

## 6. Return to Operation Procedure
<!-- 복귀 절차 -->

11. **Restart After Cooling Confirmed:** Once all temperature values have returned to normal range, gradually restore rotational speed to the original value (increase by 10% every 10 minutes).
<!-- 냉각 확인 후 재가동: 회전 속도를 10분에 걸쳐 10%씩 단계적으로 복귀시킨다. -->
12. **30-Minute Monitoring:** Closely monitor temperature changes for 30 minutes after restarting.
<!-- 30분 모니터링: 재가동 후 30분간 온도 변화를 집중 모니터링한다. -->

## 7. Escalation Criteria
<!-- 에스컬레이션 기준 -->

- Spindle temperature continuously exceeds 70°C — stop equipment immediately and call an engineer.
<!-- 스핀들 온도 70°C 초과 지속 시 즉시 설비 정지 및 엔지니어 호출 -->
- HDF flag recurs within 30 minutes after cooling system action.
<!-- 냉각 시스템 조치 후에도 HDF 플래그가 30분 내 재발하는 경우 -->
- Cooling pump failure assessed as non-repairable on-site.
<!-- 냉각 펌프 고장으로 자체 수리 불가 판정 시 -->

---

**Last Revised:** 2026-06-03
**Approved By:** Head of Facility Maintenance
<!-- 승인자: 설비보전팀장 -->
