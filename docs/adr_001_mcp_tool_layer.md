# ADR-001: MCP 도구 계층 도입

**날짜**: 2026-07-20  
**상태**: 승인됨  
**작성자**: ForgeAI

---

## 배경

ForgeAI 파이프라인은 에스컬레이션(D5) 이후 인간 조사자가 개입한다. 조사자가 파이프라인과 동일한 데이터·도구를 보려면 도구 접근 인터페이스가 표준화되어야 한다. MCP(Model Context Protocol)는 자동 소비자(파이프라인)와 인간 소비자(엔지니어 + Claude Desktop/Code)가 동일한 도구 계층을 공유할 수 있게 한다.

## 결정

- FastMCP + STDIO 트랜스포트로 도구 2개(`search_sop`, `get_sensor_context`)를 노출한다.
- MCP 서버(`mcp_server/`)는 ForgeAI 본체(`main.py`, FastAPI)와 **런타임을 분리**한다. 본체는 in-process 함수 호출을 유지하며 MCP 서버에 의존하지 않는다.

## 신뢰성 설계 3종

### 1. Pydantic 입력 검증 + 구조화 에러 반환
입력 오류를 `INPUT_VALIDATION_ERROR` + `detail` + `hint` 구조로 반환한다. LLM이 hint를 읽고 수정된 인자로 자동 재시도할 수 있다.

### 2. 출력 토큰 예산 기반 truncation
`search_sop`는 청크당 최대 600자, 전체 최대 2,400자로 제한한다. 초과 텍스트는 `…[N chars truncated]` 표시를 남겨 축약 여부를 명시한다.

### 3. 도구 description 버전 관리
각 도구 description 앞에 `[v1.0.0]` 을 명시한다. 클라이언트 캐시가 구버전 description을 유지하는 경우를 추적하기 위함이다. description이 변경되면 마이너 버전을 올린다.

## 고려하지 않은 범위 (ADR 경계 기록)

### 인증 (원격 전환 시)
현재 STDIO 트랜스포트는 로컬 프로세스이므로 인증이 불필요하다. HTTP/SSE 원격 전환 시:
- Bearer 토큰 또는 OAuth 2.0 PKCE 흐름 도입이 트리거된다.
- FastMCP의 `auth=` 파라미터로 처리 가능하다.
- `tool_configuration` 수준 권한(도구별 읽기·쓰기 분리)도 이 시점에 설계한다.

### 멱등성 / 타임아웃
현재 두 도구는 읽기 전용이므로 멱등성 문제가 없다. **쓰기 도구(예: 알람 발송, 설정 변경) 추가가 멱등성·타임아웃 설계의 트리거**다. 이 시점에 별도 ADR을 작성한다.

### resources / prompts 프리미티브
MCP 스펙의 `resources`·`prompts` 프리미티브는 현재 범위에서 제외한다. SOP 문서 전체를 resource로 노출하거나 진단 prompt 템플릿을 표준화할 필요가 생기면 도입을 검토한다.

### 원격 배포
STDIO → HTTP/SSE 전환 시 포트 충돌(FastAPI 8000 vs MCP HTTP 포트)을 피하기 위해 MCP 서버 전용 포트(예: 8001)를 별도 할당한다.

## 결과

- 엔지니어가 Claude Desktop/Code에서 파이프라인과 동일한 SOP·센서 데이터를 조회할 수 있다.
- 도구 인터페이스가 표준화되어 향후 추가 소비자(Slack bot, 대시보드 등)로 확장 가능하다.
- ForgeAI 본체 코드 변경 없이 독립 배포·테스트가 가능하다.
