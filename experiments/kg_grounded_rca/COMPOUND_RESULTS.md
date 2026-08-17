# Compound TWF + OSF grounding result

## Question

When one sensor event triggers both OSF and TWF, does forwarding only the
safety-priority OSF label lose useful RCA and maintenance context?

## Scenario

- Equipment: `CNC-02`, machine type M
- Tool wear: 216 min
- Torque: 58 Nm
- Combined strain: `216 × 58 = 12,528 min·Nm`
- TWF boundary: 200 min
- M-type OSF boundary: 12,000 min·Nm

The live ForgeAI rule engine selects OSF as the primary safety-priority label and
preserves both modes as:

```text
failure_type = OSF
triggered_failure_types = [OSF, TWF]
```

## Conditions

1. `llm_only`: sensor values and thresholds, no graph or SOP.
2. `single_label_osf`: OSF graph path and SOP-MNT-004 only.
3. `multi_path_kg_sop`: OSF + TWF causal paths and both SOP-MNT-004 and
   SOP-MNT-001.

Each condition was executed three times through `codex exec` using the current
ChatGPT OAuth session.

- Codex CLI: `0.142.5`
- Configured model: `gpt-5.6-sol`
- Reasoning effort: `medium`
- Raw results: `compound_results/20260726T065832Z/`

## Result

| Measure | LLM only | OSF single label | Multi-path KG + SOP |
|---|---:|---:|---:|
| Mean deterministic pass rate | 58.98% | 84.62% | 100% |
| Primary OSF detection | 3/3 | 3/3 | 3/3 |
| TWF contributor detection | 3/3 | 0/3 | 3/3 |
| TWF → resistance → OSF interaction | 0/3 | 0/3 | 3/3 |
| Complete safety action plan | 0/3 | 3/3 | 3/3 |
| Cross-SOP action coverage | 0/3 | 0/3 | 3/3 |
| Runs adding an unapproved procedure | 1/3 | 0/3 | 0/3 |
| Action counts | 7, 8, 7 | 5, 5, 5 | 7, 8, 8 |

## Interpretation

The input itself was sufficient for every condition to identify OSF. LLM-only
also noticed TWF because both numeric boundaries were explicit. It did not,
however, explain the authorized causal interaction between tool-life
exhaustion, increased cutting resistance, and combined overstrain.

The single-label condition was operationally safe: it generated the complete
OSF response plan every time. It was diagnostically incomplete: it omitted TWF
as a contributing failure mode in all three runs and never joined
SOP-MNT-001's tool-wear inspection, measurement, life-counter reset, quality
check, and supervisor-approval context.

Only the multi-path condition consistently:

1. preserved OSF as the primary safety-priority mode;
2. retained TWF as a contributing mode;
3. connected TWF → increased cutting resistance → combined overstrain → OSF;
4. combined structural-damage checks from SOP-MNT-004 with tool-life
   remediation from SOP-MNT-001; and
5. attached authorized graph and SOP evidence to every causal and procedural
   output.

## Implementation consequence

ForgeAI should keep single-label selection for immediate safety triage, but it
must not use that label as the complete RCA or retrieval context.

The downstream contract should preserve three distinct concepts:

```text
primary_failure_mode: OSF
triggered_failure_modes: [OSF, TWF]
causal_paths:
  - TWF -> increased_cutting_resistance
  - increased_cutting_resistance -> combined_mechanical_overstrain
  - combined_mechanical_overstrain -> OSF
sop_sources:
  - SOP-MNT-004
  - SOP-MNT-001
```

In the current implementation, `SOPRAGAgent` receives only
`risk_assessment.failure_type`. The next code change should pass all
`triggered_failure_types` into graph traversal and SOP retrieval, while keeping
`failure_type` as the safety-priority routing label.

## Limits

- The graph subgraph was embedded in the prompt; Neo4j traversal was not tested.
- Only one synthetic compound event was evaluated.
- The graph and SOP were assumed correct and consistent.
- Deterministic concept checks do not replace maintenance-expert review.
- The experiment does not prove improved general RCA accuracy.

The next failure-oriented experiment should remove or corrupt one causal edge
and verify that the system degrades to uncertainty or human review instead of
reconstructing the missing relationship from model memory.
