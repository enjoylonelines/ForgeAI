# ForgeAI Agent Reliability Evaluation Contract

## Status

- Version: `agent-reliability-v1`
- Scope: versioned agent evaluation contract plus implemented evaluator/result evidence
- Mode: deterministic mock contract first; one API provider smoke is opt-in only
- Source cases: `data/eval/agent_reliability_cases.jsonl`
- Evaluator: `scripts/eval_agent_reliability.py`
- Mock result: `output/agent_reliability_mock.json`
- Live API smoke result: `output/agent_reliability_live_api.json`

## U1 Gaps Promoted To Tasks

| U1 gap | U2 contract coverage | First cases | Next implementation owner |
|---|---|---|---|
| tool selection 평가 미구현 | required tool set and required-tool recall denominator | AR-001, AR-002, AR-003 | U3 evaluator |
| forbidden tool 호출 평가 미구현 | forbidden tool list and forbidden-call-rate denominator | AR-001, AR-005, AR-007 | U3 evaluator |
| max iteration 준수 평가 미구현 | repeated-tool case with `max_tool_calls=5` | AR-008 | U3 evaluator |
| invalid argument 처리 평가 미구현 | malformed argument failure reason | AR-007 | U3 evaluator |
| grounding 평가와 Agent 평가 미연결 | validator REVIEW/REJECT, contradiction, empty SOP cases | AR-014, AR-016, AR-017 | U3/U4 |
| unsafe AUTO 독립 지표 미구현 | safety cases with expected non-AUTO route | AR-003, AR-014, AR-024 | U3 evaluator |
| latency 관측 분포 미구현 | latency metadata must be recorded if available, not claimed as benchmark | AR-020 | U6 observability |
| token usage 관측 미구현 | token usage unavailable is explicit, never zero-filled | AR-021 | U6 observability |
| monetary cost 관측 미구현 | local/API monetary cost unavailable is explicit without versioned pricing | AR-022 | U6 observability |
| live reliability 평가셋 미구현 | live dependencies marked opt-in and not run in CI | AR-023 | U5/U6 live API smoke |

## Case Schema

Required fields per JSONL row:

- `case_id`: stable unique id, `AR-###`
- `scenario`: short snake_case description
- `input`: deterministic mock input or live opt-in descriptor
- `dependency_mode`: `mock`, `mock_degraded`, or `live_opt_in`
- `required_tools`: tool names that must appear for the case to count as complete
- `forbidden_tools`: tool names that must not appear
- `expected_route`: one of `AUTO`, `HUMAN_REVIEW`, `ESCALATE`
- `max_tool_calls`: maximum accepted DiagnosticAgent tool calls
- `expected_failure_reason`: `null` for clean cases, otherwise an explicit reason
- `evidence_source`: code, test, ADR, plan, or U1 gap used to justify the label
- `covers`: metric/task tags consumed by the future evaluator

Known DiagnosticAgent tools are:

- `get_sensor_thresholds`
- `calculate_risk_index`
- `alert_maintenance_team`

## Labeling Rules

- The contract separates current-code coverage from desired reliability gates.
- Existing current-code routes are used when they are already safe and tested.
- U1 gaps are represented as explicit failure cases instead of silent success.
- `CRITICAL`, contradiction, degraded validator, malformed tool args, unknown tool, and max-iteration exhaustion must not become unsafe automatic authority.
- Missing token or cost metadata must be reported as unavailable, never as `0`.

## Mock Boundary

The mock contract does not call live Ollama, NLI model download/inference, Chroma reindexing, Langfuse, external APIs, real alert channels, or live control. `alert_maintenance_team` is treated as a mock/dry-run tool call for evaluation.

## Implemented Evidence

- `scripts/eval_agent_reliability.py` evaluates the 23 mock cases and skips the one live opt-in case by default.
- `output/agent_reliability_mock.json` records deterministic mock metrics, public denominators, failure case ids, and mock observability status.
- `output/agent_reliability_live_api.json` records a single opt-in API provider smoke with latency and token usage observed.
- `docs/agent-reliability-result.md` is the portfolio-safe result summary and remains the source for claims/limits wording.

## Still Deferred

- Live Ollama, NLI model, Chroma reindexing, Langfuse, real alert channels, and live control are not part of this contract.
- The API provider smoke is not a full ForgePipeline live benchmark.
- Latency is a single smoke observation, not a p50/p95 distribution or SLA.
- Monetary cost remains `unavailable` because no versioned pricing table is part of this repository contract.
