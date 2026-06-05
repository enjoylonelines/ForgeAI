from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import pandas as pd
import plotly.express as px
import streamlit as st

from dashboard import api_client

st.set_page_config(page_title="배치 분석 | ForgeAI", page_icon="📊", layout="wide")
st.title("📊 배치 CSV 이상 탐지 분석")

st.info(
    "AI4I 2020 형식의 CSV 파일을 업로드하세요. "
    "필요한 컬럼: `Air temperature [K]`, `Process temperature [K]`, "
    "`Rotational speed [rpm]`, `Torque [Nm]`, `Tool wear [min]`"
)

uploaded = st.file_uploader("CSV 파일 선택", type=["csv"])

if uploaded:
    file_bytes = uploaded.read()
    row_preview = pd.read_csv(pd.io.common.BytesIO(file_bytes), nrows=5)
    with st.expander("파일 미리보기 (상위 5행)"):
        st.dataframe(row_preview)

    max_rows = st.number_input(
        "분석할 최대 행 수 (0 = 전체, 주의: 행당 1~2분 소요)",
        min_value=0,
        value=10,
        step=5,
    )

    if st.button("배치 분석 실행", type="primary"):
        if max_rows > 0:
            df_limited = pd.read_csv(pd.io.common.BytesIO(file_bytes), nrows=max_rows)
            import io
            buf = io.BytesIO()
            df_limited.to_csv(buf, index=False)
            send_bytes = buf.getvalue()
            filename = uploaded.name
        else:
            send_bytes = file_bytes
            filename = uploaded.name

        with st.spinner(f"분석 중... ({max_rows if max_rows else '전체'} 행)"):
            try:
                result = api_client.analyze_csv(send_bytes, filename)
            except Exception as e:
                st.error(f"API 호출 실패: {e}")
                st.stop()

        total = result.get("total_rows", 0)
        processed = result.get("processed_rows", 0)
        anomaly_count = result.get("anomaly_count", 0)
        results = result.get("results", [])

        st.divider()

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("전체 행", total)
        m2.metric("처리 성공", processed)
        m3.metric("이상 탐지", anomaly_count)
        rate = round(processed / total * 100, 1) if total else 0
        m4.metric("처리율", f"{rate}%")

        ok_results = [r for r in results if "error" not in r]

        if ok_results:
            st.subheader("분석 결과 시각화")
            col1, col2 = st.columns(2)

            with col1:
                normal_count = sum(1 for r in ok_results if not r.get("has_anomaly"))
                fig_pie = px.pie(
                    values=[anomaly_count, normal_count],
                    names=["이상 탐지", "정상"],
                    color_discrete_sequence=["#ef4444", "#22c55e"],
                    title="이상 탐지 비율",
                )
                st.plotly_chart(fig_pie, use_container_width=True)

            with col2:
                rec_counts = {"APPROVE": 0, "REVIEW": 0, "REJECT": 0}
                for r in ok_results:
                    rec = r.get("recommendation", "")
                    if rec in rec_counts:
                        rec_counts[rec] += 1
                fig_bar = px.bar(
                    x=list(rec_counts.keys()),
                    y=list(rec_counts.values()),
                    color=list(rec_counts.keys()),
                    color_discrete_map={
                        "APPROVE": "#22c55e",
                        "REVIEW": "#f59e0b",
                        "REJECT": "#ef4444",
                    },
                    title="검증 결과 분포",
                    labels={"x": "결과", "y": "건수"},
                )
                fig_bar.update_layout(showlegend=False)
                st.plotly_chart(fig_bar, use_container_width=True)

            grounding_scores = [
                r.get("grounding_score", 0) for r in ok_results if r.get("grounding_score") is not None
            ]
            if grounding_scores:
                fig_hist = px.histogram(
                    x=grounding_scores,
                    nbins=20,
                    title="근거 점수(Grounding Score) 분포",
                    labels={"x": "점수", "y": "건수"},
                    color_discrete_sequence=["#6366f1"],
                )
                st.plotly_chart(fig_hist, use_container_width=True)

        st.subheader("상세 결과")
        rows = []
        for r in results:
            if "error" in r:
                rows.append({
                    "행": r.get("row_index", ""),
                    "결과": "오류",
                    "이상": "-",
                    "검증": "-",
                    "점수": "-",
                    "요약": r.get("error", ""),
                })
            else:
                rows.append({
                    "행": r.get("row_index", ""),
                    "결과": "✅" if not r.get("has_anomaly") else "⚠️",
                    "이상": "있음" if r.get("has_anomaly") else "없음",
                    "검증": r.get("recommendation", ""),
                    "점수": round(r.get("grounding_score", 0), 3),
                    "요약": r.get("summary", ""),
                })
        st.dataframe(pd.DataFrame(rows), use_container_width=True)
