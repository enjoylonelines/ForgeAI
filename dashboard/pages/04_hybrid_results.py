from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import pandas as pd
import plotly.express as px
import streamlit as st

from dashboard.hybrid_results import comparison_rows, load_hybrid_results

st.set_page_config(
    page_title="하이브리드 정책 검증 | ForgeAI",
    page_icon="🧭",
    layout="wide",
)

st.title("하이브리드 정비 정책 검증")
st.caption(
    "통합 ML의 Recall–행동량 한계를 모드별로 분해하고, "
    "물리 규칙과 예방정비를 결합한 운영정책을 반복 test 분할에서 검증합니다."
)

try:
    payload = load_hybrid_results()
except FileNotFoundError as exc:
    st.error(str(exc))
    st.stop()

summary = payload["summary"]
run_count = len(payload["runs"])
hybrid = summary["hybrid_policy"]
rules = summary["physics_rule_baseline"]
maintenance = summary["twf_maintenance"]
labels = summary["label_audit"]

metric1, metric2, metric3, metric4 = st.columns(4)
metric1.metric(
    "행동 대상 감소",
    f"{hybrid['median_action_reduction_vs_unified_pct']:.1f}%",
    help="통합 4모드 ML 대비 test 행동 대상 상태 중앙값 감소율",
)
metric2.metric(
    "하이브리드 FN=0",
    f"{hybrid['zero_fn_runs']}/{run_count}회",
    help="validation에서 정책을 고정한 뒤 test에서 관측한 결과",
)
metric3.metric(
    "최종 행동 대상",
    f"{hybrid['action_states']['median']:.0f}건",
    help="AI4I test 2,000행 기준 중앙값이며 실제 공장 알림 횟수가 아닙니다.",
)
metric4.metric(
    "주 평가 고장",
    f"{labels['primary_target_failures']}건",
    help="TWF/HDF/PWF/OSF 중 하나 이상에 해당하는 전체 고장",
)

st.info(
    "모든 임계값은 validation에서만 선택하고 test에는 고정 적용했습니다. "
    "AI4I는 합성·행 단위 데이터이므로 아래 수치는 실제 공장 알림 절감률이 아니라 "
    "동일 test 상태 중 정비 판단 대상으로 분류된 건수의 비교입니다.",
    icon="ℹ️",
)

left, right = st.columns(2)
with left:
    st.subheader("센서 기반 위험 판정")
    st.markdown(
        """
        **대상:** HDF · PWF · OSF  
        **운영정책:** 데이터 생성 원리와 일치하는 물리 규칙  
        **핵심 피처:** ΔT · power · wear×torque
        """
    )
    st.metric(
        "물리 규칙 행동 대상 중앙값",
        f"{rules['alerts']['median']:.1f}건",
        delta=f"FN=0 {rules['zero_fn_runs']}/{run_count}회",
        delta_color="off",
    )
    st.caption(
        "모드별 ML은 test FN=0을 "
        f"{summary['sensor_ml']['zero_fn_runs']}/{run_count}회만 유지해 "
        "최종 운영정책에서 제외했습니다."
    )

with right:
    st.subheader("마모 기반 예방정비")
    st.markdown(
        """
        **대상:** TWF  
        **운영정책:** 고장 행 예측 대신 공구 교체 권고  
        **기준:** tool wear 198분 도달
        """
    )
    st.metric(
        "교체 권고 상태 중앙값",
        f"{maintenance['maintenance_due_states']['median']:.1f}건",
        delta=(
            "기준 미만 TWF "
            f"{maintenance['failures_below_threshold']['median']:.0f}건"
        ),
        delta_color="inverse",
    )
    st.caption(
        "TWF는 고마모 구간 내부에서 개별 고장 여부를 구분할 센서 정보가 부족해 "
        "분류 알림이 아닌 예방정비 트랙으로 분리했습니다."
    )

st.divider()
st.subheader("원인 미분류 · 사후 검토 큐")
st.caption(
    "아래 상태는 고장 전 예측 경고가 아닙니다. 고장 발생 후 현재 센서 규칙과 "
    "원인 분류 체계로 설명되지 않아 엔지니어 확인이 필요한 사례입니다."
)
audit_left, audit_right = st.columns(2)
audit_left.metric(
    "RNF-only",
    f"{labels['rnf_only_excluded']}건",
    help="다른 고장 모드 플래그 없이 RNF만 기록된 사례",
)
audit_right.metric(
    "원인 플래그 없음",
    f"{labels['flagless_failures_excluded']}건",
    help="Machine failure=1이지만 어떤 원인 모드도 기록되지 않은 사례",
)

st.divider()
st.subheader("동일 프로토콜 비교")
comparison = pd.DataFrame(comparison_rows(payload))
st.dataframe(comparison, width="stretch", hide_index=True)

chart_rows = []
for row in comparison_rows(payload):
    label = row["비교 대상"]
    key = {
        "통합 4모드 ML": "unified_ml",
        "HDF/PWF/OSF 모드별 ML": "sensor_ml",
        "HDF/PWF/OSF 물리 규칙": "physics_rule_baseline",
        "최종 하이브리드 정책": "hybrid_policy",
    }[label]
    metric_key = "action_states" if key == "hybrid_policy" else "alerts"
    chart_rows.append(
        {
            "비교 대상": label,
            "행동 대상 중앙값": summary[key][metric_key]["median"],
            "정책": "최종" if key == "hybrid_policy" else "비교",
        }
    )

fig = px.bar(
    pd.DataFrame(chart_rows),
    x="비교 대상",
    y="행동 대상 중앙값",
    color="정책",
    color_discrete_map={"최종": "#0f766e", "비교": "#94a3b8"},
    text_auto=".0f",
)
fig.update_layout(
    showlegend=False,
    xaxis_title=None,
    yaxis_title="test 행동 대상 상태 수",
    margin=dict(l=20, r=20, t=20, b=20),
)
st.plotly_chart(fig, width="stretch")

with st.expander("라벨 정책과 평가 범위"):
    st.markdown(
        f"""
        - 주 타깃 TWF/HDF/PWF/OSF: **{labels['primary_target_failures']}건**
        - RNF-only 별도 감사: **{labels['rnf_only_excluded']}건**
        - `Machine failure=1`이지만 원인 플래그가 없는 행: **{labels['flagless_failures_excluded']}건**
        - 분할: **{summary['protocol']['split']}**
        - 반복 시드: **{', '.join(map(str, summary['protocol']['seeds']))}**
        """
    )

st.subheader("이력서에 어필할 내용")
for highlight in payload["resume_highlights"]:
    st.markdown(f"- {highlight}")

with st.expander("해석상 제한"):
    for caveat in payload["caveats"]:
        st.markdown(f"- {caveat}")
