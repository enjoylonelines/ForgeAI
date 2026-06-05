import os

import streamlit as st

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dashboard import api_client

st.set_page_config(
    page_title="ForgeAI 모니터링 대시보드",
    page_icon="🏭",
    layout="wide",
)

with st.sidebar:
    st.title("🏭 ForgeAI")
    st.caption("제조 설비 이상 탐지 멀티에이전트 RAG 시스템")

    st.divider()
    st.subheader("연결 상태")

    try:
        h = api_client.health()
        ollama_ok = h.get("ollama") == "ok"
        chroma_ok = h.get("chromadb") == "ok"
        st.success("백엔드 연결됨", icon="✅")
        st.metric("Ollama", "정상" if ollama_ok else "오류", delta=None)
        st.metric("ChromaDB", "정상" if chroma_ok else "오류", delta=None)
        st.metric("SOP 문서 수", h.get("collection_doc_count", "-"))
    except Exception:
        st.error("백엔드에 연결할 수 없습니다", icon="🔴")
        st.caption(f"API URL: {api_client.get_base_url()}")

    st.divider()
    langfuse_host = os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com")
    st.markdown(f"[Langfuse 대시보드 열기]({langfuse_host})")

st.title("ForgeAI 이상 탐지 모니터링")
st.markdown("""
ForgeAI는 제조 설비 센서 로그를 분석하여 이상을 탐지하고 SOP 기반 조치 계획을 생성하는
**멀티에이전트 RAG 시스템**입니다.

| 에이전트 | 역할 |
|---------|------|
| PerceptionAgent | 센서 데이터 분석 및 이상 감지 |
| SOPRAGAgent | 관련 SOP 문서 벡터 검색 |
| ActionPlanAgent | SOP 기반 단계별 조치 계획 생성 |
| HallucinationValidator | 조치 계획의 SOP 근거 검증 |

왼쪽 메뉴에서 페이지를 선택하세요.
""")
