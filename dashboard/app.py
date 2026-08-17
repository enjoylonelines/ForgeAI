import os

import streamlit as st

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dashboard import api_client
from dashboard.hybrid_results import load_hybrid_results

st.set_page_config(
    page_title="ForgeAI 모니터링 대시보드",
    page_icon="🏭",
    layout="wide",
)

with st.sidebar:
    st.title("🏭 ForgeAI")
    st.caption("물리 규칙과 예방정비를 결합한 설비 모니터링")

    st.divider()
    with st.expander("레거시 RCA 백엔드 상태"):
        try:
            h = api_client.health()
            st.success("백엔드 연결됨", icon="✅")
            st.caption(
                f"Ollama: {h.get('ollama', 'unknown')} · "
                f"ChromaDB: {h.get('chromadb', 'unknown')} · "
                f"SOP 청크: {h.get('collection_doc_count', '-')}"
            )
        except Exception:
            st.caption(f"오프라인 · API URL: {api_client.get_base_url()}")

st.title("ForgeAI 하이브리드 설비 모니터링")
st.markdown(
    """
    통합 모델의 점수만 높이는 대신 **고장 모드별 정보 한계와 정비 비용을 분해**해,
    HDF·PWF·OSF는 물리 규칙으로 판정하고 TWF는 마모 기반 예방정비로 전환했습니다.
    """
)

try:
    payload = load_hybrid_results()
except FileNotFoundError as exc:
    st.warning(str(exc))
else:
    summary = payload["summary"]
    hybrid = summary["hybrid_policy"]
    rules = summary["physics_rule_baseline"]
    maintenance = summary["twf_maintenance"]
    run_count = len(payload["runs"])

    m1, m2, m3, m4 = st.columns(4)
    m1.metric(
        "행동 대상 감소",
        f"{hybrid['median_action_reduction_vs_unified_pct']:.1f}%",
        help="통합 4모드 ML 대비 test 행동 대상 상태 중앙값",
    )
    m2.metric("관측 미탐 0", f"{hybrid['zero_fn_runs']}/{run_count}회")
    m3.metric("최종 행동 대상", f"{hybrid['action_states']['median']:.0f}건")
    m4.metric(
        "평가 프로토콜",
        "60/20/20",
        help="train/validation/test, 10개 반복 시드",
    )

    st.caption(
        "AI4I test 2,000행 기준 반복 중앙값입니다. 실제 공장 알림 횟수나 "
        "미래 미탐률 0% 보장을 의미하지 않습니다."
    )

    st.divider()
    left, right = st.columns(2)
    with left:
        st.subheader("센서 기반 위험 판정")
        st.markdown("**HDF · PWF · OSF**")
        st.metric(
            "물리 규칙 행동 대상",
            f"{rules['alerts']['median']:.1f}건",
            delta=f"FN=0 {rules['zero_fn_runs']}/{run_count}회",
            delta_color="off",
        )
        st.caption("ΔT · power · wear×torque로 투명하게 판정")
    with right:
        st.subheader("마모 기반 교체 권고")
        st.markdown("**TWF · tool wear 198분**")
        st.metric(
            "교체 권고 상태",
            f"{maintenance['maintenance_due_states']['median']:.1f}건",
            delta="예방정비 트랙",
            delta_color="off",
        )
        st.caption("개별 고장 확률 대신 교체 시점을 관리")

    st.divider()
    st.subheader("원인 미분류 · 사후 검토")
    st.caption(
        "예측 경고가 아니라 고장 발생 후 현재 분류 체계로 설명되지 않은 사례를 "
        "엔지니어 검토 큐로 분리합니다."
    )
    audit = summary["label_audit"]
    audit_left, audit_right = st.columns(2)
    audit_left.metric("RNF-only 검토", f"{audit['rnf_only_excluded']}건")
    audit_right.metric(
        "원인 플래그 없음",
        f"{audit['flagless_failures_excluded']}건",
    )

    st.divider()
    st.subheader("이력서에 어필할 내용")
    for highlight in payload["resume_highlights"]:
        st.markdown(f"- {highlight}")

    st.info(
        "세부 비교·라벨 정책·해석상 제한은 왼쪽 메뉴의 "
        "**하이브리드 정비 정책 검증** 페이지에서 확인할 수 있습니다.",
        icon="🧭",
    )
