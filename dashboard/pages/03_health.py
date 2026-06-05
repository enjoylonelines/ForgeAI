from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import streamlit as st

from dashboard import api_client

st.set_page_config(page_title="시스템 상태 | ForgeAI", page_icon="🩺", layout="wide")
st.title("🩺 시스템 상태")

if st.button("새로고침", type="secondary"):
    st.rerun()

try:
    h = api_client.health()
    overall = h.get("status", "unknown")

    if overall == "ok":
        st.success("전체 시스템 정상", icon="✅")
    else:
        st.warning("일부 서비스 이상", icon="⚠️")

    st.divider()
    c1, c2, c3 = st.columns(3)

    ollama_status = h.get("ollama", "unknown")
    with c1:
        st.metric(
            "Ollama LLM",
            "정상" if ollama_status == "ok" else "오류",
        )
        if ollama_status == "ok":
            st.success("qwen2.5:7b + nomic-embed-text 로드됨")
        else:
            st.error("Ollama 서버 연결 실패")

    chroma_status = h.get("chromadb", "unknown")
    with c2:
        st.metric(
            "ChromaDB",
            "정상" if chroma_status == "ok" else "오류",
        )
        if chroma_status == "ok":
            st.success("벡터 DB 연결됨")
        else:
            st.error("ChromaDB 연결 실패")

    doc_count = h.get("collection_doc_count", 0)
    with c3:
        st.metric("SOP 문서 청크 수", doc_count)
        if doc_count == 0:
            st.warning("SOP 문서가 인제스트되지 않았습니다")
        else:
            st.success(f"{doc_count}개 청크 인덱싱됨")

    st.divider()
    st.subheader("연결 정보")
    info_col1, info_col2 = st.columns(2)
    with info_col1:
        st.caption(f"FastAPI URL: `{api_client.get_base_url()}`")
        langfuse_host = os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com")
        langfuse_enabled = os.getenv("LANGFUSE_ENABLED", "false").lower() == "true"
        st.caption(f"Langfuse: {'활성화' if langfuse_enabled else '비활성화'} ({langfuse_host})")
    with info_col2:
        if langfuse_enabled:
            st.markdown(f"[Langfuse 대시보드 열기]({langfuse_host})")

except Exception as e:
    st.error(f"백엔드에 연결할 수 없습니다: {e}", icon="🔴")
    st.caption(f"API URL: {api_client.get_base_url()}")
    st.info("FastAPI 서버가 실행 중인지 확인하세요: `uvicorn main:app --reload`")
