# KG-grounded RCA feasibility result

## Experiment

- Date: 2026-07-26 KST
- Authentication: current Codex ChatGPT OAuth session
- Codex CLI: `0.142.5`
- Configured model: `gpt-5.6-sol`
- Reasoning effort: `medium`
- Scenario: synthetic CNC tool-wear event (`twf-compound-001`)
- Conditions:
  - `llm_only`: readings and symptoms only
  - `kg_sop`: the same input plus eight authorized graph edges and four SOP
    procedure excerpts

The main comparison ran each condition three times with the same response
contract. The saved raw responses are in
`results/20260725T163033Z/`.

## Main result

| Measure | LLM only | KG + SOP |
|---|---:|---:|
| Mean deterministic pass rate | 72.22% | 94.45% |
| Failure-mode accuracy | 3/3 | 3/3 |
| Root-cause accuracy | 3/3 | 3/3 |
| Runs adding procedures absent from supplied evidence | 3/3 | 0/3 |
| Runs with the complete expected SOP action plan | 0/3 | 3/3 |
| Action counts per run | 7, 7, 8 | 4, 4, 4 |
| Per-chain provenance completeness | expected empty IDs | 1/3 |

Both conditions recognized the obvious tool-wear failure. The graph did not
demonstrate an improvement in failure classification for this scenario.

The meaningful difference was control over causal and procedural output:

- LLM-only runs added holder, runout, coolant, chip-removal, equipment-isolation,
  or energy-control steps that were not supplied by an approved procedure.
- KG + SOP runs produced the same four approved steps every time and used no
  unknown graph or SOP evidence IDs.
- LLM-only produced seven or eight actions; KG + SOP produced four actions in
  all runs.

## Defect found during the experiment

The first response schema represented `causal_chain` as free-form strings.
Although all KG runs duplicated their causal assertions in a separate
evidence-bearing `claims` list, two of three runs omitted graph IDs from the
chain strings themselves.

This means that supplying graph context is not enough to guarantee provenance.
The output contract must attach evidence IDs to each causal-chain item.

The schema was changed to:

```json
{
  "statement": "TWF increases cutting resistance",
  "evidence_ids": ["G6"]
}
```

A one-run-per-condition regression check after this change produced:

| Measure | LLM only | KG + SOP |
|---|---:|---:|
| Pass rate | 75% | 100% |
| Causal-chain evidence policy | pass | pass |
| Unprovided-procedure run | yes | no |
| Complete expected action plan | no | yes |

## What this validates

For this one scenario, a bounded graph subgraph plus selected SOP evidence:

1. constrained the diagnosis to authorized causal edges;
2. prevented unsupported maintenance procedures;
3. produced a stable, fully cited four-step action plan; and
4. exposed the need for schema-level provenance enforcement.

The strongest current claim is therefore:

> KG + SOP grounding improved procedural faithfulness and output consistency for
> one synthetic TWF scenario.

It is not yet valid to claim that a knowledge graph improves general RCA
accuracy.

## Limitations and next gates

- The graph was supplied as an authorized subgraph in the prompt; Neo4j lookup
  was not tested.
- The scenario was synthetic and its primary failure mode was obvious.
- The scorer uses deterministic concept and evidence checks, not expert review.
- The graph and SOP were assumed correct and mutually consistent.
- Three main repetitions and one schema-regression repetition are insufficient
  for a general quality claim.

The next evaluation set should add:

1. ambiguous multi-failure cases such as TWF + OSF;
2. missing or stale graph edges;
3. an incorrectly retrieved SOP;
4. sensor evidence that conflicts with the graph;
5. actual Neo4j subgraph retrieval; and
6. blinded human scoring of causal adequacy and maintenance safety.
