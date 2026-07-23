# ForgeAI k3s 배포 가이드

경량 쿠버네티스(k3s)를 대상으로 한 매니페스트와 fail-safe 아키텍처 문서.

## 파일 구조

```
k8s/
├── namespace.yaml          # forgeai 네임스페이스
├── configmap.yaml          # 환경변수 (OLLAMA_BASE_URL 등)
├── pvc.yaml                # ChromaDB(5Gi) + Ollama 모델(20Gi) 퍼시스턴스
├── ollama-deployment.yaml  # Ollama Deployment + Service
├── deployment.yaml         # ForgeAI Deployment (readiness/liveness probe 포함)
├── service.yaml            # ForgeAI ClusterIP Service
└── kustomization.yaml      # Kustomize 진입점
```

## 빠른 시작

### 1. k3s 설치 (미설치 시)

```bash
curl -sfL https://get.k3s.io | sh -
```

### 2. 이미지 빌드 및 k3s 노드에 로드

```bash
docker build -t forgeai:latest .
docker save forgeai:latest | sudo k3s ctr images import -
```

### 3. 전체 배포

```bash
kubectl apply -k k8s/
```

### 4. 개별 리소스 적용 (순서 중요)

```bash
kubectl apply -f k8s/namespace.yaml
kubectl apply -f k8s/configmap.yaml
kubectl apply -f k8s/pvc.yaml
kubectl apply -f k8s/ollama-deployment.yaml
kubectl wait --for=condition=ready pod -l app=ollama -n forgeai --timeout=300s
kubectl apply -f k8s/deployment.yaml
kubectl apply -f k8s/service.yaml
```

### 5. 배포 확인

```bash
# Pod 상태 확인 (readiness probe 1/1 Ready)
kubectl get pods -n forgeai

# 헬스 체크
kubectl port-forward svc/forgeai 8080:80 -n forgeai &
curl http://localhost:8080/api/v1/health
```

정상 응답 예시:
```json
{"status": "ok", "mode": "full", "ollama": "ok", "chromadb": "ok", "collection_doc_count": 42}
```

## Probe 설계

### readinessProbe (`GET /api/v1/health`)

| 상태 | HTTP 코드 | `mode` 필드 | Pod 트래픽 수신 |
|------|----------|------------|---------------|
| Ollama + ChromaDB 정상 | 200 | `"full"` | ✅ 수신 |
| Ollama 불능 (ChromaDB 정상) | 200 | `"rule-only"` | ✅ 수신 (폴백 모드) |
| ChromaDB 불능 | 503 | - | ❌ 차단 |

### livenessProbe

exec 방식으로 HTTP 응답 코드(200–599)를 확인합니다.
앱이 응답하면 살아있는 것으로 판단하며, Ollama 불능(503 없음)으로 인한 불필요한 재시작을 방지합니다.

### startupProbe

초기 모델 로드(최대 120초)를 기다립니다.

## Fail-safe 아키텍처

Ollama(LLM)가 불능 상태일 때 Rule Engine만으로 분석 요청을 처리합니다.

```
POST /api/v1/analyze
        │
        ▼
 ollama_health() 체크
        │
   ┌────┴────┐
   │ UP      │ DOWN
   ▼         ▼
ForgePipeline  run_rule_only()
 .run()         │
   │            ├─ Rule Engine (결정론적 FDC)
   │            ├─ ML predictor (보조 신호)
   │            └─ 라우팅 규칙 적용
   │                    │
   └──────┬─────────────┘
          ▼
   PipelineResult
   metrics.mode = "full" | "rule-only"
   X-Mode 응답 헤더
```

### rule-only 모드 동작

- **Rule Engine** (결정론적): 센서 임계값 기반 고장 모드 분류 (TWF/HDF/PWF/OSF/NONE)
- **ML predictor** (보조): 통계적 이상 확률 계산
- **라우팅 규칙**: R-1~R-F 중 해당 규칙 적용
- **LLM 에이전트 전체 생략**: 이상 탐지, 진단, SOP 검색, 조치 계획, 검증 없음

### 응답 예시 (rule-only)

```json
{
  "correlation_id": "abc123",
  "risk_assessment": {
    "risk_level": "WARNING",
    "failure_type": "TWF",
    "summary": "Tool wear at 96% of safe range..."
  },
  "routing_decision": {"route": "ESCALATE", "matched_rule": "R-1"},
  "metrics": {"mode": "rule-only", "risk_level": "WARNING"}
}
```

### fail-safe 완료 기준 검증

```bash
# Ollama 서비스 강제 중단
kubectl scale deployment ollama --replicas=0 -n forgeai

# analyze 호출 → 200 응답 + mode: "rule-only" 확인
curl -s -X POST http://localhost:8080/api/v1/analyze \
  -H 'Content-Type: application/json' \
  -d '{...}' | jq '.metrics.mode'
# → "rule-only"

curl -s http://localhost:8080/api/v1/health | jq '{mode, status}'
# → {"mode": "rule-only", "status": "degraded"}
```

## 리소스 요구사항

| 컴포넌트 | CPU (request/limit) | 메모리 (request/limit) | 스토리지 |
|---------|--------------------|-----------------------|---------|
| ForgeAI | 250m / 1 | 512Mi / 1Gi | - |
| Ollama | 1 / 4 | 4Gi / 8Gi | 20Gi |
| ChromaDB | PVC 마운트 | - | 5Gi |
