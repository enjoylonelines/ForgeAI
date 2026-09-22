from __future__ import annotations

import html
import os
import sys
from datetime import datetime, timezone
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import streamlit as st

from dashboard import api_client

st.set_page_config(page_title="설비 이상 대응 콘솔 | ForgeAI", page_icon="ForgeAI", layout="wide")


SENSOR_LABELS = {
    "air_temperature_k": ("공기 온도", "K"),
    "process_temperature_k": ("공정 온도", "K"),
    "rotational_speed_rpm": ("회전 속도", "rpm"),
    "torque_nm": ("토크", "Nm"),
    "tool_wear_min": ("공구 마모", "min"),
}
SEVERITY_ORDER = {"CRITICAL": 4, "HIGH": 3, "MEDIUM": 2, "LOW": 1}
SEVERITY_LABELS = {
    "CRITICAL": "위험",
    "HIGH": "높음",
    "MEDIUM": "주의",
    "LOW": "낮음",
    "SAFE": "정상",
    "WARNING": "주의",
    "UNKNOWN": "확인 필요",
}
STATE_LABELS = {
    "ready": "분석 전",
    "running": "분석 중",
    "complete": "결과 완료",
    "error": "API 실패",
}


st.html(
    """
    <style>
    :root {
        --forge-bg: #171a1d;
        --forge-panel: #20252a;
        --forge-panel-2: #252b31;
        --forge-line: #3b434c;
        --forge-line-soft: #2f363d;
        --forge-text: #f1f5f7;
        --forge-muted: #aab4bd;
        --forge-faint: #76828d;
        --forge-green: #6fa77b;
        --forge-amber: #c49a45;
        --forge-red: #be625e;
        --forge-blue: #6f91ad;
    }
    .stApp { background: var(--forge-bg); color: var(--forge-text); }
    header[data-testid="stHeader"] { background: var(--forge-bg); }
    section[data-testid="stSidebar"] { background: #20242a; }
    section[data-testid="stSidebar"] * { color: #d8dee4; }
    .block-container { padding-top: 1.4rem; padding-bottom: 3rem; max-width: 1480px; }
    h1, h2, h3 { letter-spacing: 0; }
    div[data-testid="stForm"] {
        background: var(--forge-panel);
        border: 1px solid var(--forge-line);
        border-radius: 4px;
        padding: 1rem 1rem 1.1rem;
    }
    div[data-testid="stFormSubmitButton"] button {
        background: var(--forge-blue);
        border: 1px solid #88a5ba;
        color: #101417;
        border-radius: 4px;
        font-weight: 800;
    }
    div[data-testid="stFormSubmitButton"] button:hover {
        background: #88a5ba;
        border-color: #9eb7c8;
        color: #101417;
    }
    div[data-testid="stMetric"] { background: transparent; border: 0; padding: 0; }
    .forge-context {
        display: grid;
        grid-template-columns: minmax(160px, 1.2fr) repeat(5, minmax(110px, 1fr));
        gap: 0;
        border: 1px solid var(--forge-line);
        border-radius: 4px;
        overflow: hidden;
        margin: .4rem 0 1rem;
        background: var(--forge-panel);
    }
    .forge-context-title, .forge-context-cell {
        padding: .82rem .95rem;
        border-right: 1px solid var(--forge-line-soft);
        min-width: 0;
    }
    .forge-context-cell:last-child { border-right: 0; }
    .forge-context-title { background: #1d2227; }
    .forge-eyebrow {
        color: var(--forge-muted);
        font-size: .72rem;
        font-weight: 700;
        letter-spacing: .04em;
        text-transform: uppercase;
        margin-bottom: .28rem;
    }
    .forge-title {
        color: var(--forge-text);
        font-size: 1.48rem;
        font-weight: 760;
        line-height: 1.2;
    }
    .forge-value {
        color: var(--forge-text);
        font-size: .98rem;
        font-weight: 680;
        white-space: normal;
        overflow: hidden;
        text-overflow: ellipsis;
    }
    .forge-muted { color: var(--forge-muted); font-size: .78rem; margin-top: .16rem; }
    .forge-status { display: inline-flex; align-items: center; gap: .45rem; }
    .forge-dot {
        width: .58rem;
        height: .58rem;
        border-radius: 999px;
        background: var(--forge-faint);
        flex: 0 0 auto;
    }
    .forge-dot.ok, .forge-pill.ok { background: var(--forge-green); }
    .forge-dot.warn, .forge-pill.warn { background: var(--forge-amber); }
    .forge-dot.danger, .forge-pill.danger { background: var(--forge-red); }
    .forge-dot.info, .forge-pill.info { background: var(--forge-blue); }
    .forge-judgment {
        border: 1px solid var(--forge-line);
        border-radius: 4px;
        background: var(--forge-panel);
        padding: 1rem;
        margin: .8rem 0 1rem;
    }
    .forge-judgment-header {
        display: flex;
        justify-content: space-between;
        gap: 1rem;
        border-bottom: 1px solid var(--forge-line-soft);
        padding-bottom: .75rem;
        margin-bottom: .9rem;
    }
    .forge-judgment-title { font-size: 1.18rem; font-weight: 760; line-height: 1.35; }
    .forge-judgment-summary { color: var(--forge-muted); margin-top: .35rem; line-height: 1.45; }
    .forge-pill {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        min-height: 1.8rem;
        padding: .22rem .65rem;
        border-radius: 3px;
        color: #101417;
        font-size: .78rem;
        font-weight: 800;
        white-space: nowrap;
    }
    .forge-pill.neutral { background: #687480; color: #f5f7f8; }
    .forge-judgment-grid {
        display: grid;
        grid-template-columns: repeat(3, minmax(0, 1fr));
        gap: 1px;
        background: var(--forge-line-soft);
        border: 1px solid var(--forge-line-soft);
    }
    .forge-judge-cell { background: #1c2126; padding: .75rem .85rem; min-width: 0; }
    .forge-label { color: var(--forge-muted); font-size: .76rem; margin-bottom: .3rem; }
    .forge-judge-value {
        color: var(--forge-text);
        font-size: 1rem;
        font-weight: 760;
        white-space: normal;
        overflow-wrap: anywhere;
    }
    .forge-section { border-top: 1px solid var(--forge-line); padding-top: .95rem; margin-top: 1.2rem; }
    .forge-section-title { color: var(--forge-text); font-size: 1.03rem; font-weight: 760; margin-bottom: .75rem; }
    .forge-sensor-grid {
        display: grid;
        grid-template-columns: repeat(5, minmax(120px, 1fr));
        gap: 1px;
        background: var(--forge-line-soft);
        border: 1px solid var(--forge-line-soft);
        border-radius: 4px;
        overflow: hidden;
    }
    .forge-sensor { background: var(--forge-panel); padding: .85rem; min-width: 0; }
    .forge-sensor-value { font-size: 1.16rem; font-weight: 780; color: var(--forge-text); }
    .forge-sensor-unit { color: var(--forge-muted); font-size: .82rem; margin-left: .16rem; }
    .forge-table {
        width: 100%;
        border-collapse: collapse;
        border: 1px solid var(--forge-line);
        border-radius: 4px;
        overflow: hidden;
        font-size: .9rem;
    }
    .forge-table th {
        background: #1d2227;
        color: var(--forge-muted);
        text-align: left;
        padding: .7rem .75rem;
        border-bottom: 1px solid var(--forge-line);
        font-weight: 720;
    }
    .forge-table td {
        background: var(--forge-panel);
        color: var(--forge-text);
        padding: .72rem .75rem;
        border-bottom: 1px solid var(--forge-line-soft);
        vertical-align: top;
    }
    .forge-table tr:last-child td { border-bottom: 0; }
    .forge-empty, .forge-callout {
        border: 1px solid var(--forge-line);
        border-radius: 4px;
        background: var(--forge-panel);
        padding: .9rem 1rem;
        color: var(--forge-muted);
        line-height: 1.5;
    }
    .forge-callout {
        border-left: 4px solid var(--forge-blue);
        color: var(--forge-text);
        margin-bottom: .8rem;
    }
    .forge-callout.warn { border-left-color: var(--forge-amber); }
    .forge-callout.danger { border-left-color: var(--forge-red); }
    .forge-callout.ok { border-left-color: var(--forge-green); }
    .forge-timeline { border-left: 2px solid var(--forge-line); margin-left: .45rem; padding-left: 1rem; }
    .forge-step { position: relative; padding: 0 0 .95rem; }
    .forge-step::before {
        content: "";
        position: absolute;
        left: -1.38rem;
        top: .2rem;
        width: .68rem;
        height: .68rem;
        border-radius: 999px;
        background: var(--forge-blue);
        border: 2px solid var(--forge-bg);
    }
    .forge-step.p1::before { background: var(--forge-red); }
    .forge-step.p2::before { background: var(--forge-amber); }
    .forge-step.p3::before { background: var(--forge-green); }
    .forge-step-head { display: flex; flex-wrap: wrap; gap: .45rem .65rem; align-items: center; margin-bottom: .28rem; }
    .forge-step-title { color: var(--forge-text); font-weight: 760; }
    .forge-step-meta { color: var(--forge-muted); font-size: .83rem; }
    .forge-step-body { color: var(--forge-text); line-height: 1.5; }
    .forge-trace {
        color: var(--forge-muted);
        font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
        font-size: .82rem;
        word-break: break-all;
    }
    @media (max-width: 1200px) {
        .forge-context { grid-template-columns: repeat(2, minmax(0, 1fr)); }
        .forge-context-title { grid-column: 1 / -1; }
        .forge-sensor-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
    }
    @media (max-width: 700px) {
        .forge-context, .forge-judgment-grid, .forge-sensor-grid { grid-template-columns: 1fr; }
        .forge-judgment-header { flex-direction: column; }
    }
    </style>
    """,
)


def esc(value: Any) -> str:
    return html.escape("" if value is None else str(value))


def fmt_number(value: Any, decimals: int = 1) -> str:
    if value is None:
        return "-"
    try:
        return f"{float(value):.{decimals}f}"
    except (TypeError, ValueError):
        return esc(value)


def fmt_score(value: Any) -> str:
    if value is None:
        return "근거 확인 필요"
    try:
        return f"{float(value):.2f}"
    except (TypeError, ValueError):
        return "근거 확인 필요"


def fmt_datetime(value: Any) -> str:
    if not value:
        return "-"
    if isinstance(value, datetime):
        dt = value
    else:
        try:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return esc(value)
    return dt.astimezone().strftime("%Y-%m-%d %H:%M:%S")


def status_class(value: str | None) -> str:
    value = (value or "").upper()
    if value in {"SAFE", "APPROVE", "OK", "CONNECTED", "P3"}:
        return "ok"
    if value in {"WARNING", "MEDIUM", "LOW", "REVIEW", "RUNNING", "P2"}:
        return "warn"
    if value in {"CRITICAL", "HIGH", "REJECT", "ERROR", "FAILED", "P1"}:
        return "danger"
    return "info"


def priority_class(priority: str | None) -> str:
    return {"P1": "p1", "P2": "p2", "P3": "p3"}.get((priority or "").upper(), "p3")


def build_log_dict(
    equipment_id: str,
    machine_type: str,
    log_level: str,
    air_temp: float,
    proc_temp: float,
    rpm: float,
    torque: float,
    tool_wear: float,
    failure_types: list[str],
    message: str,
) -> dict[str, Any]:
    return {
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


def get_health_state() -> tuple[str, str]:
    try:
        api_client.health()
    except Exception as exc:
        return "오프라인", f"{api_client.get_base_url()} · {exc.__class__.__name__}"
    return "연결됨", api_client.get_base_url()


def highest_severity(anomalies: list[dict[str, Any]], risk_level: str | None) -> str:
    if anomalies:
        return max(
            (str(item.get("severity", "LOW")).upper() for item in anomalies),
            key=lambda item: SEVERITY_ORDER.get(item, 0),
        )
    return "SAFE" if risk_level == "SAFE" else (risk_level or "UNKNOWN")


def normalize_result(result: dict[str, Any] | None) -> dict[str, Any]:
    result = result or {}
    return {
        "risk": result.get("risk_assessment") or {},
        "anomaly": result.get("anomaly_report") or {},
        "sop": result.get("sop_context") or {},
        "plan": result.get("action_plan") or {},
        "validation": result.get("validation_result") or {},
        "routing": result.get("routing_decision") or {},
        "metrics": result.get("metrics") or {},
        "correlation_id": result.get("correlation_id") or "",
        "completed_at": result.get("pipeline_completed_at") or "",
    }


def render_context_bar(
    equipment_id: str,
    machine_type: str,
    analysis_time: str,
    api_status: str,
    api_detail: str,
    page_state: str,
) -> None:
    api_class = "ok" if api_status == "연결됨" else "danger"
    state_class = {"ready": "info", "running": "warn", "complete": "ok", "error": "danger"}.get(page_state, "info")
    st.html(
        f"""
        <div class="forge-context">
            <div class="forge-context-title">
                <div class="forge-eyebrow">ForgeAI</div>
                <div class="forge-title">설비 이상 대응 콘솔</div>
            </div>
            <div class="forge-context-cell">
                <div class="forge-label">설비 ID</div>
                <div class="forge-value">{esc(equipment_id)}</div>
            </div>
            <div class="forge-context-cell">
                <div class="forge-label">기종</div>
                <div class="forge-value">{esc(machine_type)}</div>
            </div>
            <div class="forge-context-cell">
                <div class="forge-label">분석 시각</div>
                <div class="forge-value">{esc(analysis_time)}</div>
            </div>
            <div class="forge-context-cell">
                <div class="forge-label">API 연결 상태</div>
                <div class="forge-value forge-status"><span class="forge-dot {api_class}"></span>{esc(api_status)}</div>
                <div class="forge-muted">{esc(api_detail)}</div>
            </div>
            <div class="forge-context-cell">
                <div class="forge-label">처리 상태</div>
                <div class="forge-value forge-status"><span class="forge-dot {state_class}"></span>{esc(STATE_LABELS.get(page_state, page_state))}</div>
            </div>
        </div>
        """,
    )


def render_judgment(result: dict[str, Any] | None, page_state: str, error_message: str | None = None) -> None:
    data = normalize_result(result)
    risk = data["risk"]
    anomaly = data["anomaly"]
    plan = data["plan"]
    validation = data["validation"]
    routing = data["routing"]
    metrics = data["metrics"]

    anomalies = anomaly.get("anomalies") or []
    risk_level = risk.get("risk_level") or metrics.get("risk_level")
    has_anomaly = bool(anomaly.get("has_anomaly")) if anomaly else risk_level in {"WARNING", "CRITICAL"}
    severity = highest_severity(anomalies, risk_level)
    recommendation = validation.get("recommendation")
    grounding = validation.get("overall_grounding_score")
    escalation = plan.get("escalation_required")
    route = routing.get("route")

    if page_state == "error":
        headline = "API 호출 실패"
        summary = error_message or "응답을 받지 못했습니다. 백엔드 주소와 실행 상태를 확인한 뒤 재시도하십시오."
        badge_text = "재시도 필요"
        badge_class = "danger"
        has_anomaly_text = "확인 불가"
    elif result is None:
        headline = "분석 대기"
        summary = "입력값을 확인하고 분석 실행을 누르면 이상 여부, 근거, 조치 계획을 같은 화면에서 확인합니다."
        badge_text = "입력 확인"
        badge_class = "info"
        has_anomaly_text = "분석 전"
    elif not has_anomaly:
        headline = "현재 입력값 기준 이상 감지 없음"
        summary = risk.get("summary") or anomaly.get("summary") or "규칙 기반 위험 판정에서 즉시 조치 대상이 확인되지 않았습니다."
        badge_text = "정상"
        badge_class = "ok"
        has_anomaly_text = "정상"
    else:
        headline = "이상 감지됨"
        summary = anomaly.get("summary") or risk.get("summary") or "상세 이상 항목과 우선 조치 계획을 확인하십시오."
        badge_text = SEVERITY_LABELS.get(severity, severity)
        badge_class = status_class(severity)
        has_anomaly_text = "탐지됨"

    validation_text = recommendation or ("근거 확인 필요" if result else "-")
    escalation_text = "필요" if escalation else ("불필요" if escalation is False else "-")
    grounding_text = fmt_score(grounding)
    if grounding in (None, 0, 0.0) and validation_text in {"REVIEW", "REJECT", "근거 확인 필요"}:
        grounding_text = f"{grounding_text} · 근거 확인 필요"
    route_text = route or ("조기 종료" if metrics.get("early_exit") else "-")

    st.html(
        f"""
        <section class="forge-judgment">
            <div class="forge-judgment-header">
                <div>
                    <div class="forge-label">최우선 판단</div>
                    <div class="forge-judgment-title">{esc(headline)}</div>
                    <div class="forge-judgment-summary">{esc(summary)}</div>
                </div>
                <div><span class="forge-pill {badge_class}">{esc(badge_text)}</span></div>
            </div>
            <div class="forge-judgment-grid">
                <div class="forge-judge-cell">
                    <div class="forge-label">이상 감지 여부</div>
                    <div class="forge-judge-value">{esc(has_anomaly_text)}</div>
                </div>
                <div class="forge-judge-cell">
                    <div class="forge-label">심각도</div>
                    <div class="forge-judge-value">{esc(SEVERITY_LABELS.get(severity, severity))}</div>
                </div>
                <div class="forge-judge-cell">
                    <div class="forge-label">이상 항목 수</div>
                    <div class="forge-judge-value">{len(anomalies)}</div>
                </div>
                <div class="forge-judge-cell">
                    <div class="forge-label">검증 결과</div>
                    <div class="forge-judge-value">{esc(validation_text)}</div>
                </div>
                <div class="forge-judge-cell">
                    <div class="forge-label">근거 점수</div>
                    <div class="forge-judge-value">{esc(grounding_text)}</div>
                </div>
                <div class="forge-judge-cell">
                    <div class="forge-label">에스컬레이션 / 라우팅</div>
                    <div class="forge-judge-value">{esc(escalation_text)} · {esc(route_text)}</div>
                </div>
            </div>
        </section>
        """,
    )


def render_sensor_state(log_dict: dict[str, Any]) -> None:
    cells = []
    for reading in log_dict["readings"]:
        sensor_id = reading["sensor_id"]
        label, default_unit = SENSOR_LABELS.get(sensor_id, (sensor_id, reading.get("unit", "")))
        unit = reading.get("unit") or default_unit
        decimals = 0 if unit in {"rpm", "min"} else 1
        cells.append(
            f"""
            <div class="forge-sensor">
                <div class="forge-label">{esc(label)}</div>
                <div><span class="forge-sensor-value">{fmt_number(reading.get("value"), decimals)}</span><span class="forge-sensor-unit">{esc(unit)}</span></div>
            </div>
            """
        )
    st.html(
        f"""
        <section class="forge-section">
            <div class="forge-section-title">설비 상태</div>
            <div class="forge-sensor-grid">{''.join(cells)}</div>
        </section>
        """,
    )


def render_anomaly_evidence(result: dict[str, Any] | None) -> None:
    anomaly = normalize_result(result)["anomaly"]
    anomalies = anomaly.get("anomalies") or []
    if not result:
        body = '<div class="forge-empty">분석 실행 후 이상 근거가 표시됩니다.</div>'
    elif not anomalies:
        body = '<div class="forge-callout ok">이상 항목이 없습니다. 경고 패널 대신 정상 상태로 기록됩니다.</div>'
    else:
        rows = []
        for item in anomalies:
            expected = item.get("expected_range")
            expected_text = f"{fmt_number(expected[0])} ~ {fmt_number(expected[1])}" if expected else "-"
            rows.append(
                f"""
                <tr>
                    <td>{esc(item.get("sensor_id"))}</td>
                    <td>{fmt_number(item.get("observed_value"))}</td>
                    <td>{esc(expected_text)}</td>
                    <td>{esc(SEVERITY_LABELS.get(item.get("severity"), item.get("severity")))}</td>
                    <td>{esc(item.get("description"))}</td>
                </tr>
                """
            )
        body = f"""
        <table class="forge-table">
            <thead>
                <tr>
                    <th>sensor_id</th>
                    <th>관측값</th>
                    <th>정상 범위</th>
                    <th>심각도</th>
                    <th>이상 설명</th>
                </tr>
            </thead>
            <tbody>{''.join(rows)}</tbody>
        </table>
        """
    st.html(
        f"""
        <section class="forge-section">
            <div class="forge-section-title">이상 근거</div>
            {body}
        </section>
        """,
    )


def render_sop_context(result: dict[str, Any] | None) -> None:
    sop = normalize_result(result)["sop"]
    chunks = sop.get("chunks") or []
    st.html('<section class="forge-section"><div class="forge-section-title">참조 SOP 문서</div>')
    if not result:
        st.html('<div class="forge-empty">분석 실행 후 검색된 SOP 문서와 관련도가 표시됩니다.</div>')
    elif not chunks:
        st.html('<div class="forge-callout warn">검색된 SOP가 없습니다. 조치 근거를 별도로 확인해야 합니다.</div>')
    else:
        st.caption(f"검색 쿼리: `{sop.get('query_used', '')}`")
        for chunk in chunks:
            score = chunk.get("relevance_score")
            page = f" · p.{chunk.get('page_number')}" if chunk.get("page_number") else ""
            with st.expander(f"{chunk.get('document_name', 'SOP')} · 관련도 {fmt_score(score)}{page}"):
                st.write(chunk.get("text", ""))
                st.caption(f"chunk_id: `{chunk.get('chunk_id', '-')}`")
    st.html("</section>")


def render_action_plan(result: dict[str, Any] | None) -> None:
    plan = normalize_result(result)["plan"]
    steps = plan.get("steps") or []
    escalation_required = plan.get("escalation_required")
    escalation_reason = plan.get("escalation_reason")
    st.html('<section class="forge-section"><div class="forge-section-title">조치 계획</div>')
    if escalation_required:
        st.html(
            f'<div class="forge-callout danger"><strong>에스컬레이션 필요</strong><br>{esc(escalation_reason or "사유가 응답에 포함되지 않았습니다.")}</div>',
        )
    elif result and escalation_required is False:
        st.html('<div class="forge-callout ok">에스컬레이션 요구가 없습니다. 아래 조치 순서를 기준으로 현장 확인을 진행합니다.</div>')

    if not result:
        st.html('<div class="forge-empty">분석 실행 후 P1/P2/P3 작업 지시가 표시됩니다.</div>')
    elif not steps:
        st.html('<div class="forge-empty">조치 계획이 없습니다. 정상 조기 종료 또는 rule-only 결과일 수 있습니다.</div>')
    else:
        step_markup = []
        for step in steps:
            priority = step.get("priority", "P3")
            duration = step.get("estimated_duration_minutes")
            duration_text = f"{duration}분" if duration else "시간 미정"
            sop_ref = f" · SOP {esc(step.get('sop_reference'))}" if step.get("sop_reference") else ""
            step_markup.append(
                f"""
                <div class="forge-step {priority_class(priority)}">
                    <div class="forge-step-head">
                        <span class="forge-pill {status_class(priority)}">{esc(priority)}</span>
                        <span class="forge-step-title">단계 {esc(step.get("step_number"))}</span>
                        <span class="forge-step-meta">{esc(duration_text)} · 담당 {esc(step.get("responsible_role"))}{sop_ref}</span>
                    </div>
                    <div class="forge-step-body">{esc(step.get("action"))}</div>
                </div>
                """
            )
        st.html(f'<div class="forge-timeline">{"".join(step_markup)}</div>')
    st.html("</section>")


def render_validation(result: dict[str, Any] | None) -> None:
    data = normalize_result(result)
    validation = data["validation"]
    correlation_id = data["correlation_id"]
    recommendation = validation.get("recommendation")
    grounding = validation.get("overall_grounding_score")
    ungrounded = validation.get("ungrounded_steps") or []
    explanation = validation.get("explanation")
    strategy = validation.get("validation_strategy")
    contradiction_count = validation.get("contradiction_count")
    status = status_class(recommendation)
    summary = {
        "APPROVE": "SOP 근거가 조치 계획을 지지합니다.",
        "REVIEW": "사람 검토가 필요합니다. 근거 부족 또는 정책상 보류 조건을 확인하십시오.",
        "REJECT": "조치 계획 근거가 부족합니다. 현장 적용 전 재검토가 필요합니다.",
    }.get(recommendation, "검증 결과가 없습니다. 정상 조기 종료 또는 rule-only 결과일 수 있습니다.")

    st.html('<section class="forge-section"><div class="forge-section-title">근거와 검증</div>')
    if not result:
        st.html('<div class="forge-empty">분석 실행 후 검증 결과와 추적 정보가 표시됩니다.</div>')
    else:
        st.html(
            f"""
            <div class="forge-callout {status}">
                <strong>{esc(recommendation or "검증 결과 없음")}</strong><br>
                {esc(summary)}
            </div>
            <table class="forge-table">
                <tbody>
                    <tr><th>근거 점수</th><td>{esc(fmt_score(grounding))}</td></tr>
                    <tr><th>근거 부족 단계</th><td>{esc(", ".join(map(str, ungrounded)) if ungrounded else "없음")}</td></tr>
                    <tr><th>검증 방식</th><td>{esc(strategy or "-")}</td></tr>
                    <tr><th>모순 검출 수</th><td>{esc(contradiction_count if contradiction_count is not None else "-")}</td></tr>
                    <tr><th>correlation ID</th><td><span class="forge-trace">{esc(correlation_id or "-")}</span></td></tr>
                </tbody>
            </table>
            """,
        )
        if explanation:
            with st.expander("검증 설명"):
                st.write(explanation)
        with st.expander("원문과 추적 정보"):
            st.json(result)
        if correlation_id:
            langfuse_host = os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com")
            langfuse_enabled = os.getenv("LANGFUSE_ENABLED", "false").lower() == "true"
            st.caption(f"Correlation ID: `{correlation_id}`")
            if langfuse_enabled:
                st.markdown(f"[Langfuse에서 LLM Trace 보기]({langfuse_host}/trace/{correlation_id})")
    st.html("</section>")


if "single_result" not in st.session_state:
    st.session_state.single_result = None
if "single_error" not in st.session_state:
    st.session_state.single_error = None
if "single_request" not in st.session_state:
    st.session_state.single_request = build_log_dict(
        "M-12345",
        "M",
        "ERROR",
        298.1,
        308.6,
        1251.0,
        42.8,
        216.0,
        [],
        "Machine failure detected",
    )


api_status, api_detail = get_health_state()
result = st.session_state.single_result
error = st.session_state.single_error
request_log = st.session_state.single_request
page_state = "error" if error else ("complete" if result else "ready")
result_data = normalize_result(result)
machine_type_current = request_log.get("tags", {}).get("machine_type", "M")
analysis_time = fmt_datetime(result_data["completed_at"] or request_log.get("timestamp"))

render_context_bar(
    request_log.get("equipment_id", "M-12345"),
    machine_type_current,
    analysis_time,
    api_status,
    api_detail,
    page_state,
)
render_judgment(result, page_state, error)

with st.form("analyze_form"):
    st.subheader("분석 입력")
    col1, col2, col3 = st.columns(3)
    with col1:
        equipment_id = st.text_input("설비 ID", value=request_log.get("equipment_id", "M-12345"))
    with col2:
        machine_type = st.selectbox("기종", ["L", "M", "H"], index=["L", "M", "H"].index(machine_type_current))
    with col3:
        log_level = st.selectbox("로그 레벨", ["ERROR", "WARN", "INFO", "CRITICAL"], index=0)

    st.subheader("센서 값")
    readings_by_id = {item["sensor_id"]: item for item in request_log.get("readings", [])}
    c1, c2, c3, c4, c5 = st.columns(5)
    with c1:
        air_temp = st.number_input(
            "공기 온도 (K)",
            value=float(readings_by_id.get("air_temperature_k", {}).get("value", 298.1)),
            format="%.1f",
        )
    with c2:
        proc_temp = st.number_input(
            "공정 온도 (K)",
            value=float(readings_by_id.get("process_temperature_k", {}).get("value", 308.6)),
            format="%.1f",
        )
    with c3:
        rpm = st.number_input(
            "회전 속도 (rpm)",
            value=float(readings_by_id.get("rotational_speed_rpm", {}).get("value", 1251.0)),
            format="%.0f",
        )
    with c4:
        torque = st.number_input(
            "토크 (Nm)",
            value=float(readings_by_id.get("torque_nm", {}).get("value", 42.8)),
            format="%.1f",
        )
    with c5:
        tool_wear = st.number_input(
            "공구 마모 (min)",
            value=float(readings_by_id.get("tool_wear_min", {}).get("value", 216.0)),
            format="%.0f",
        )

    failure_types_value = request_log.get("tags", {}).get("failure_types", "")
    failure_types = st.multiselect(
        "고장 유형 태그 (알고 있는 경우)",
        ["TWF", "HDF", "PWF", "OSF", "RNF"],
        default=[item for item in failure_types_value.split(",") if item],
    )
    message = st.text_input("메시지", value=request_log.get("message", "Machine failure detected"))
    submitted = st.form_submit_button("분석 실행", type="primary", use_container_width=True)

if submitted:
    next_log = build_log_dict(
        equipment_id,
        machine_type,
        log_level,
        air_temp,
        proc_temp,
        rpm,
        torque,
        tool_wear,
        failure_types,
        message,
    )
    st.session_state.single_request = next_log
    st.session_state.single_error = None

    render_context_bar(equipment_id, machine_type, fmt_datetime(next_log["timestamp"]), api_status, api_detail, "running")
    with st.spinner("분석 중입니다. LLM API 호출, SOP 검색, 조치계획 검증 단계 때문에 대기할 수 있습니다."):
        try:
            st.session_state.single_result = api_client.analyze(next_log)
        except Exception as exc:
            st.session_state.single_result = None
            st.session_state.single_error = f"{exc.__class__.__name__}: {exc}"
    st.rerun()

render_sensor_state(st.session_state.single_request)

left, right = st.columns([1.05, 0.95])
with left:
    render_anomaly_evidence(st.session_state.single_result)
    render_sop_context(st.session_state.single_result)
with right:
    render_action_plan(st.session_state.single_result)
    render_validation(st.session_state.single_result)
