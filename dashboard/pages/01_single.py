from __future__ import annotations

import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import streamlit as st

from dashboard import api_client

st.set_page_config(page_title="단건 분석 | ForgeAI", page_icon="🔍", layout="wide")
st.title("🔍 단건 이상 탐지 분석")

SEVERITY_ICON = {"CRITICAL": "🔴", "HIGH": "🟠", "MEDIUM": "🟡", "LOW": "🟢"}
PRIORITY_COLOR = {"P1": "error", "P2": "warning", "P3": "success"}

with st.form("analyze_form"):
    st.subheader("설비 정보")
    col1, col2, col3 = st.columns(3)
    with col1:
        equipment_id = st.text_input("설비 ID", value="M-12345")
    with col2:
        machine_type = st.selectbox("기종", ["L", "M", "H"])
    with col3:
        log_level = st.selectbox("로그 레벨", ["ERROR", "WARNING", "INFO"])

    st.subheader("센서 값")
    c1, c2, c3, c4, c5 = st.columns(5)
    with c1:
        air_temp = st.number_input("공기 온도 (K)", value=298.1, format="%.1f")
    with c2:
        proc_temp = st.number_input("프로세스 온도 (K)", value=308.6, format="%.1f")
    with c3:
        rpm = st.number_input("회전 속도 (rpm)", value=1251.0, format="%.0f")
    with c4:
        torque = st.number_input("토크 (Nm)", value=42.8, format="%.1f")
    with c5:
        tool_wear = st.number_input("공구 마모 (min)", value=216.0, format="%.0f")

    failure_types = st.multiselect(
        "고장 유형 태그 (알고 있는 경우)", ["TWF", "HDF", "PWF", "OSF", "RNF"]
    )
    message = st.text_input("메시지", value="Machine failure detected")

    submitted = st.form_submit_button("분석 실행", type="primary", use_container_width=True)

if submitted:
    log_dict = {
        "equipment_id": equipment_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "log_level": log_level,
        "readings": [
            {"sensor_id": "air_temperature_k", "unit": "K", "value": air_temp},
            {"sensor_id": "process_temperature_k", "unit": "K", "value": proc_temp},
            {"sensor_id": "rotational_speed_rpm", "unit": "rpm", "value": rpm},
            {"sensor_id": "torque_nm", "unit": "Nm", "value": torque},
            {"sensor_id": "tool_wear_min", "unit": "min", "value": tool_wear},
        ],
        "message": message,
        "tags": {
            "machine_type": machine_type,
            "failure_types": ",".join(failure_types) if failure_types else "",
        },
    }

    with st.spinner("파이프라인 실행 중... (LLM 호출로 1~2분 소요될 수 있습니다)"):
        try:
            result = api_client.analyze(log_dict)
        except Exception as e:
            st.error(f"API 호출 실패: {e}")
            st.stop()

    correlation_id = result.get("correlation_id", "")
    anomaly = result.get("anomaly_report", {})
    sop = result.get("sop_context", {})
    plan = result.get("action_plan", {})
    validation = result.get("validation_result", {})

    st.divider()

    # 상단 요약 메트릭
    m1, m2, m3, m4 = st.columns(4)
    has_anomaly = anomaly.get("has_anomaly", False)
    m1.metric("이상 감지", "탐지됨" if has_anomaly else "정상", delta=None)
    m2.metric("이상 항목 수", len(anomaly.get("anomalies", [])))
    grounding = validation.get("overall_grounding_score", 0.0)
    m3.metric("근거 점수", f"{grounding:.2f}")
    recommendation = validation.get("recommendation", "-")
    m4.metric("검증 결과", recommendation)

    st.divider()
    left, right = st.columns(2)

    # 좌측: 이상 탐지 결과
    with left:
        st.subheader("이상 탐지 결과")
        if has_anomaly:
            st.error(anomaly.get("summary", ""))
            for a in anomaly.get("anomalies", []):
                icon = SEVERITY_ICON.get(a.get("severity", "LOW"), "⚪")
                with st.expander(f"{icon} {a.get('sensor_id')} — {a.get('severity')}"):
                    st.write(f"**관측값**: {a.get('observed_value')}")
                    er = a.get("expected_range")
                    if er:
                        st.write(f"**정상 범위**: {er[0]} ~ {er[1]}")
                    st.write(f"**설명**: {a.get('description')}")
        else:
            st.success("이상 없음 — 모든 센서 정상 범위")

        st.subheader("참조 SOP 문서")
        chunks = sop.get("chunks", [])
        if chunks:
            st.caption(f"검색 쿼리: `{sop.get('query_used', '')}`")
            for chunk in chunks:
                score = chunk.get("relevance_score", 0)
                with st.expander(
                    f"📄 {chunk.get('document_name')} — 관련도 {score:.2f}"
                ):
                    st.text(chunk.get("text", "")[:400] + "...")
        else:
            st.info("검색된 SOP 없음")

    # 우측: 조치 계획 + 검증
    with right:
        st.subheader("조치 계획")
        steps = plan.get("steps", [])
        if steps:
            if plan.get("escalation_required"):
                st.warning(f"⚠️ 에스컬레이션 필요: {plan.get('escalation_reason', '')}")
            for step in steps:
                priority = step.get("priority", "P3")
                color_fn = getattr(st, PRIORITY_COLOR.get(priority, "info"))
                duration = step.get("estimated_duration_minutes")
                dur_str = f" ({duration}분)" if duration else ""
                color_fn(
                    f"**[{priority}] Step {step.get('step_number')}**{dur_str}  \n"
                    f"{step.get('action')}  \n"
                    f"담당: `{step.get('responsible_role')}`"
                )
        else:
            st.info("조치 계획 없음")

        st.subheader("검증 결과")
        st.progress(min(grounding, 1.0), text=f"근거 점수: {grounding:.2f}")

        if recommendation == "APPROVE":
            st.success("✅ APPROVE — SOP 근거 충분")
        elif recommendation == "REVIEW":
            st.warning("⚠️ REVIEW — 사람 검토 권장")
        else:
            st.error("❌ REJECT — SOP 근거 부족")

        ungrounded = validation.get("ungrounded_steps", [])
        if ungrounded:
            st.caption(f"근거 부족 단계: {ungrounded}")

        if validation.get("explanation"):
            with st.expander("검증 설명"):
                st.write(validation["explanation"])

    # Langfuse 링크
    if correlation_id:
        langfuse_host = os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com")
        langfuse_enabled = os.getenv("LANGFUSE_ENABLED", "false").lower() == "true"
        st.divider()
        st.caption(f"Correlation ID: `{correlation_id}`")
        if langfuse_enabled:
            st.markdown(
                f"[🔗 Langfuse에서 LLM Trace 보기]({langfuse_host}/trace/{correlation_id})"
            )
