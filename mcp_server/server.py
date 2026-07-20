"""ForgeAI SOP MCP Server — STDIO transport

도구 목록:
  search_sop          v1.0.0  SOP 문서 벡터 검색
  get_sensor_context  v1.0.0  설비 센서 임계값 + 리스크 지수 조회

신뢰성 설계:
  1. Pydantic 입력 검증 → 구조화 에러 반환 (LLM 재시도 가능)
  2. 출력 토큰 예산 기반 truncation (청크당 600chars, 전체 2400chars)
  3. 도구 description에 버전 명시 (v1.0.0)
"""
from __future__ import annotations

import sys
from pathlib import Path

# 레포 루트를 sys.path에 추가 (STDIO 프로세스는 CWD가 다를 수 있음)
sys.path.insert(0, str(Path(__file__).parent.parent))

from pydantic import ValidationError
from fastmcp import FastMCP

from mcp_server.tools.search_sop import SearchSOPInput, run_search_sop
from mcp_server.tools.get_sensor_context import GetSensorContextInput, run_get_sensor_context

mcp = FastMCP(
    name="ForgeAI-SOP",
    instructions=(
        "ForgeAI 제조 설비 SOP 검색 서버. "
        "search_sop로 관련 SOP 절차를 찾고, "
        "get_sensor_context로 센서 정상 범위와 리스크 지수를 확인하세요."
    ),
)


@mcp.tool(
    description=(
        "[v1.0.0] ForgeAI SOP 문서 벡터 검색. "
        "query(필수), failure_type(선택: TWF|HDF|PWF|OSF|RNF), top_k(선택: 1–5, 기본 3). "
        "입력 오류 시 error 필드와 재시도 가능한 hint를 반환합니다."
    )
)
def search_sop(query: str, failure_type: str | None = None, top_k: int = 3) -> dict:
    try:
        params = SearchSOPInput(query=query, failure_type=failure_type, top_k=top_k)
    except ValidationError as exc:
        return {
            "error": "INPUT_VALIDATION_ERROR",
            "detail": exc.errors(include_url=False),
            "hint": "query는 3–500자, failure_type은 TWF|HDF|PWF|OSF|RNF 중 하나, top_k는 1–5.",
        }

    try:
        return run_search_sop(params.query, params.failure_type, params.top_k)
    except Exception as exc:
        return {
            "error": "INTERNAL_ERROR",
            "message": str(exc),
            "hint": "ChromaDB 또는 임베딩 서버 상태를 확인하세요.",
        }


@mcp.tool(
    description=(
        "[v1.0.0] 설비 센서 임계값 및 리스크 지수 조회. "
        "equipment_type(H|M|L), tool_wear_min(0–500), torque_nm(0–200), "
        "rotational_speed_rpm(0–5000). "
        "입력 오류 시 error 필드와 재시도 가능한 hint를 반환합니다."
    )
)
def get_sensor_context(
    equipment_type: str,
    tool_wear_min: float,
    torque_nm: float,
    rotational_speed_rpm: float,
) -> dict:
    try:
        params = GetSensorContextInput(
            equipment_type=equipment_type,
            tool_wear_min=tool_wear_min,
            torque_nm=torque_nm,
            rotational_speed_rpm=rotational_speed_rpm,
        )
    except ValidationError as exc:
        return {
            "error": "INPUT_VALIDATION_ERROR",
            "detail": exc.errors(include_url=False),
            "hint": "equipment_type은 H|M|L, 각 센서값은 지정 범위 내 숫자.",
        }

    try:
        return run_get_sensor_context(
            params.equipment_type,
            params.tool_wear_min,
            params.torque_nm,
            params.rotational_speed_rpm,
        )
    except Exception as exc:
        return {
            "error": "INTERNAL_ERROR",
            "message": str(exc),
            "hint": "입력값을 확인하고 재시도하세요.",
        }


if __name__ == "__main__":
    mcp.run(transport="stdio")
