# KG-grounded RCA comparison experiment

This experiment compares two conditions for the same synthetic tool-wear event:

1. `llm_only`: the model receives sensor readings and symptoms only.
2. `kg_sop`: the model additionally receives an authorized causal subgraph and
   selected SOP procedure evidence.

The runner invokes `codex exec` with the current ChatGPT OAuth session. It does
not require an OpenAI API key and does not send repository files to the model.
Only the scenario, graph edges, and SOP excerpts embedded in the prompt are
provided.

The causal chain uses structured `{statement, evidence_ids}` items. An earlier
smoke version used free-form strings and showed that a model can repeat the
right graph path while omitting per-edge provenance. The schema now prevents
that ambiguity.

```bash
.venv/bin/python experiments/kg_grounded_rca/run_experiment.py
```

Outputs are written to a timestamped directory below `results/`. Each response
is retained with its deterministic score, and `summary.json` aggregates the
comparison.

If the deterministic scoring rules change, re-score saved model outputs without
spending additional model usage:

```bash
.venv/bin/python experiments/kg_grounded_rca/rescore_results.py \
  experiments/kg_grounded_rca/results/<timestamp>
```

This is a feasibility experiment, not evidence that the approach generalizes.
The next stage should add multiple failure modes, adversarial graph gaps, wrong
SOP retrieval, and repeated runs with a pinned model configuration.

## Compound-failure experiment

The second experiment compares `llm_only`, `single_label_osf`, and
`multi_path_kg_sop` for a simultaneous TWF + OSF event:

```bash
.venv/bin/python experiments/kg_grounded_rca/run_compound_experiment.py
```

This directly tests whether the pipeline loses a contributing TWF path when the
rule engine forwards only the safety-priority OSF label.

Saved compound runs can be re-scored without additional model usage:

```bash
.venv/bin/python experiments/kg_grounded_rca/rescore_compound_results.py \
  experiments/kg_grounded_rca/compound_results/<timestamp>
```
