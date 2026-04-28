---
name: evaluate-langgraph-mlflow
description: |
  Build an MLflow-tracked evaluation harness for LangGraph LLM applications
  (e.g. autoqa's test_suite_reviewer and test_case_reviewer). Treats the pipeline
  as a binary classifier (overall_verdict Yes/No) plus a per-rubric multi-cell
  classifier (M1-M5 for RTM, 5 review objectives for TC), and produces an MLflow
  experiment with per-run params, aggregate metrics, per-record predictions, and
  rich artifacts (confusion matrices, per-rubric breakdowns, latency histograms,
  prompt-version manifests). Applies MLOps best practices: reproducibility (pin
  model + prompt versions + fixture hash), parameter/tag conventions for
  cross-run comparison, mlflow.evaluate() with custom metrics, autologging via
  mlflow.langchain.autolog(), trace export per record, and a registered-model
  promotion path for prompt versions that beat the baseline. Use when the user
  asks to "evaluate the pipeline with MLflow", "track LLM evaluation runs",
  "compare prompt versions in MLflow", "set up MLflow for LangGraph",
  "compute per-rubric accuracy / F1 / ROC AUC", or "wire CI to gate on
  evaluation metrics". Builds on top of generate-rtm-dataset and
  generate-tc-dataset (which produce the labelled fixtures this skill scores
  the pipeline against).
---

# evaluate-langgraph-mlflow

Build an MLflow-tracked evaluation harness that scores a LangGraph application
against a labelled fixture, logs aggregate + per-record metrics, captures per-
graph-execution traces, and supports cross-run comparison for prompt-iteration
A/B testing. Targeted at autoqa's two reviewers (`test_suite_reviewer`,
`test_case_reviewer`) but the pattern generalises to any LangGraph that emits
a structured Pydantic verdict against a known ground-truth label.

This skill is a **harness builder + protocol**. It writes a Python script
(typically under `scripts/`), shapes the MLflow experiment structure, and
defines the metric catalogue. It does NOT modify the pipeline itself or the
existing pytest integration tests — those keep their job of catching helper-
rule violations.

## Mission

Set up a reproducible, comparable evaluation loop:

1. Take a labelled fixture (e.g. `tests/fixtures/test-suite-reviewer-200/inputs.jsonl`
   + `outputs.jsonl`, or `gold_dataset-tc.jsonl` with `expected_overall_verdict`
   annotations).
2. Invoke the LangGraph pipeline against every input record, in parallel via
   `asyncio.gather`.
3. Compute and log to MLflow:
   - **Run params** — pinning every reproducibility-relevant knob.
   - **Aggregate metrics** — overall accuracy / F1 / ROC AUC + per-rubric breakdown.
   - **Per-record artifacts** — predictions.jsonl, confusion matrix, latency histogram.
   - **Traces** — one trace per record showing the LangGraph node sequence.
4. Compare runs side by side; promote the winning prompt-set via MLflow Model
   Registry aliases.

## When to invoke

- "Evaluate the pipeline with MLflow / track this evaluation run"
- "Compare prompt versions A vs B (e.g. synthesizer-v5 vs synthesizer-v6)"
- "Compute per-rubric F1 / accuracy / ROC AUC for the test_suite_reviewer"
- "Set up MLflow tracking for LangGraph evaluation"
- "Wire CI to gate on evaluation metrics regressing"
- "Promote a prompt set to production via MLflow registry"
- User has a fixture from `generate-rtm-dataset` / `generate-tc-dataset` and
  asks how to score the pipeline against it
- User mentions accuracy / F1 / ROC AUC / calibration in the context of
  LangGraph evaluation

If the user wants to *generate* a labelled fixture (rather than score against
one), redirect to `generate-rtm-dataset` or `generate-tc-dataset` first — this
skill needs ground-truth labels to compute metrics.

## Prerequisites

```bash
uv add --dev mlflow scikit-learn matplotlib
```

Optionally, set the tracking URI (defaults to local `./mlruns`):

```bash
export MLFLOW_TRACKING_URI="file:./mlruns"            # local
# or
export MLFLOW_TRACKING_URI="http://localhost:5000"    # remote server
# or
export MLFLOW_TRACKING_URI="databricks"               # managed
```

For the autoqa repo, local tracking under `./mlruns` is fine; the directory is
already gitignored by the existing `logs/` pattern (verify and add `mlruns/`
to `.gitignore` if missing).

## Concept: pipeline-as-classifier

Both reviewers emit a structured assessment with a top-level binary verdict
plus a per-rubric multi-cell breakdown. Treat each as a stack of classifiers:

| component | binary classifier | multi-cell classifier |
|---|---|---|
| `test_suite_reviewer` | `overall_verdict` ∈ {Yes, No} | M1-M5 × {Yes, No, N-A} |
| `test_case_reviewer` | `overall_verdict` ∈ {Yes, No} | 5 objectives × {Yes, No} + partial flag |

Score each level independently:
- **Binary** — accuracy, precision, recall, F1, ROC AUC (if you can extract a
  score), confusion matrix.
- **Multi-cell** — per-cell accuracy, per-cell F1, macro-F1 across cells,
  Krippendorff alpha for inter-rater-style agreement (LLM vs ground truth).
- **Calibration** — for partial flags (TC component): how often does
  `partial=true` correctly predict ground-truth partials?

## Setup: MLflow experiment structure

Apply consistent naming so cross-run comparison works:

| MLflow concept | autoqa convention | example |
|---|---|---|
| **Experiment name** | `{component}-{fixture_label}` | `test_suite_reviewer-cgm-200` |
| **Run name** | `{prompt_set_label}-{git_short_sha}` | `synthesizer-v6-stack-aec5cca` |
| **Params** (pinned reproducibility knobs) | model, prompt versions, max_concurrent, fixture_path, fixture_size | see "Run params catalogue" below |
| **Tags** (queryable metadata) | git_sha, env, prompt_set_label, owner | `git_sha=aec5cca`, `env=local` |
| **Metrics** (aggregate scalars) | overall_accuracy, per_rubric_accuracy.M1, macro_f1, mean_latency_s, p95_latency_s | see "Metrics catalogue" |
| **Artifacts** (rich outputs) | predictions.jsonl, confusion_matrix.png, per_rubric.csv, prompt_versions.json, traces/ | see "Artifacts" |

Create the experiment once:

```python
import mlflow
mlflow.set_experiment("test_suite_reviewer-cgm-200")
```

## Run params catalogue (every run MUST log all of these)

```python
mlflow.log_params({
    # Component identity
    "component": "test_suite_reviewer",         # or test_case_reviewer
    "git_sha": <subprocess: git rev-parse HEAD>,
    "git_dirty": <subprocess: git status --porcelain | wc -l > 0>,
    # Model
    "model": os.getenv("TEST_MODEL", "gpt-4o-mini"),
    # Prompt versions (every Jinja2 template the runnable touches)
    "prompt_decomposer":  prompt_config.decomposer,
    "prompt_summarizer":  prompt_config.summarizer,
    "prompt_coverage":    prompt_config.coverage,
    "prompt_synthesizer": prompt_config.synthesizer,
    # Fixture identity
    "fixture_path":  str(fixture_path),
    "fixture_sha256": <hash of inputs.jsonl>,
    "fixture_size": len(records),
    # Concurrency
    "max_concurrent": MAX_CONCURRENT,
    # Random seed (where applicable; LLM nondeterminism is logged separately)
    "temperature": model_kwargs.get("temperature", 0.0),
})

mlflow.set_tags({
    "prompt_set_label": "v6-stack",            # human label for the prompt set
    "env": os.getenv("AUTOQA_ENV", "local"),    # local / ci / prod
    "owner": os.getenv("USER", "unknown"),
})
```

Pinning all of these makes any future regression trivially diff-able: change
*one* knob, re-run, compare.

## Metrics catalogue (every run logs the relevant subset)

### Always-on aggregate metrics

```python
mlflow.log_metrics({
    # Top-line binary
    "overall_accuracy":  acc,
    "overall_precision": prec,
    "overall_recall":    recall,
    "overall_f1":        f1,
    # If a continuous score is available (rare for verdict-only LLMs)
    "overall_roc_auc":   roc_auc,

    # Per-rubric (RTM example — TC has 5 objective ids instead)
    "rubric_accuracy.M1": m1_acc,
    "rubric_accuracy.M2": m2_acc,
    "rubric_accuracy.M3": m3_acc,
    "rubric_accuracy.M4": m4_acc,
    "rubric_accuracy.M5": m5_acc,
    "rubric_f1.M1":       m1_f1,
    "rubric_f1.M2":       m2_f1,
    "rubric_f1.M3":       m3_f1,
    "rubric_f1.M4":       m4_f1,
    "rubric_f1.M5":       m5_f1,
    "rubric_macro_f1":    macro_f1,

    # Calibration (TC component only)
    "partial_flag_accuracy": partial_acc,

    # Helper invariants (% of records where the deterministic rule held)
    "helper_invariant_pass_rate": helper_pass,
    "aggregator_skip_rate":       skipped / total,

    # Latency
    "mean_latency_s":  mean_lat,
    "p50_latency_s":   p50_lat,
    "p95_latency_s":   p95_lat,
    "p99_latency_s":   p99_lat,
    "wall_clock_s":    total_wall,

    # Cost (if you have token usage)
    "total_input_tokens":  in_tokens,
    "total_output_tokens": out_tokens,
    "estimated_cost_usd":  cost,
})
```

### Per-record step metrics (optional, useful for time-series view)

```python
for i, record in enumerate(records):
    mlflow.log_metric("record_latency_s", record.latency, step=i)
    mlflow.log_metric("record_overall_correct", int(record.match), step=i)
```

## Artifacts (every run writes the relevant subset)

| Artifact | Format | Purpose |
|---|---|---|
| `predictions.jsonl` | one JSON per record: `{record_id, ground_truth, predicted, per_rubric, partial_flags, latency_s, raw_state}` | per-record audit |
| `confusion_matrix.png` | matplotlib | binary classifier visual |
| `per_rubric.csv` | rubric_code, accuracy, f1, support, no_count, yes_count, na_count | rubric breakdown |
| `latency_histogram.png` | matplotlib | tail latency visual |
| `prompt_versions.json` | `{role: filename}` plus SHA256 of each template body | exact prompt-content provenance |
| `fixture_metadata.json` | `{path, sha256, size, label_distribution}` | fixture identity |
| `traces/` directory | one JSON per record: serialized LangGraph state at each node | execution trace for debugging |
| `failures.jsonl` | filter of predictions.jsonl where match=False | quick-access regression set |

## Reference harness (autoqa-flavour)

Save as `scripts/evaluate_with_mlflow.py`. Two CLI args: component and fixture path.

```python
"""MLflow evaluation harness for LangGraph reviewers (autoqa).

Usage:
    uv run python scripts/evaluate_with_mlflow.py \
        --component test_suite_reviewer \
        --fixture tests/fixtures/test-suite-reviewer-200/inputs.jsonl \
        --ground-truth tests/fixtures/test-suite-reviewer-200/outputs.jsonl \
        --run-name "v6-stack-$(git rev-parse --short HEAD)"
"""
import argparse, asyncio, hashlib, json, os, subprocess, time
from pathlib import Path
from collections import Counter
from typing import Any

import mlflow
from sklearn.metrics import accuracy_score, f1_score, precision_recall_fscore_support, confusion_matrix
import matplotlib.pyplot as plt
import numpy as np

# Component-specific imports
from autoqa.components.test_suite_reviewer.pipeline import RTMReviewerRunnable
from autoqa.components.test_suite_reviewer.core import Requirement, TestCase, SynthesizedAssessment
from autoqa.components.test_case_reviewer.pipeline import TCReviewerRunnable
from autoqa.components.test_case_reviewer.core import Requirement as TCRequirement, TestCase as TCTestCase, TestCaseAssessment
from autoqa.components.test_case_reviewer.nodes import load_default_review_objectives
from autoqa.components.clients import RateLimitOpenAIClient
from autoqa.core.config import settings


def _git_sha() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"]).decode().strip()
    except Exception:
        return "unknown"


def _git_dirty() -> bool:
    try:
        return bool(subprocess.check_output(["git", "status", "--porcelain"]).decode().strip())
    except Exception:
        return False


def _file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()[:16]


def _prompt_versions_manifest(prompt_config) -> dict:
    """Capture each Jinja2 template's path + content hash. Pinpoints exactly
    which prompt body produced this run."""
    out = {}
    for role in ("decomposer", "summarizer", "coverage", "synthesizer"):
        if not hasattr(prompt_config, role):
            continue
        filename = getattr(prompt_config, role)
        path = Path(__file__).parent.parent / "autoqa" / "prompts" / filename
        out[role] = {
            "filename": filename,
            "sha256": _file_sha256(path) if path.exists() else None,
        }
    return out


async def _run_pipeline_rtm(client, model, inputs, max_concurrent):
    graph = RTMReviewerRunnable(client=client, model=model)
    sem = asyncio.Semaphore(max_concurrent)

    async def run_one(idx, row):
        async with sem:
            t0 = time.perf_counter()
            result = await graph.graph.ainvoke({
                "requirement": Requirement(**row["requirement"]),
                "test_cases": [TestCase(**tc) for tc in row["test_cases"]],
            })
            return idx, row, result, time.perf_counter() - t0

    completed = await asyncio.gather(
        *(run_one(i, row) for i, row in enumerate(inputs)),
        return_exceptions=True,
    )
    return completed


def _score_rtm(completed, ground_truth):
    """Compute predictions-vs-ground-truth records for the RTM component."""
    predictions = []
    skipped = 0
    for c in completed:
        if isinstance(c, Exception):
            skipped += 1
            continue
        idx, row, state, latency = c
        sa = state.get("synthesized_assessment")
        if sa is None:
            skipped += 1
            continue
        gt = ground_truth[idx]["synthesized_assessment"]
        pred_overall = sa.overall_verdict
        gt_overall = gt["overall_verdict"]
        per_rubric = []
        for f, gt_f in zip(sa.mandatory_findings, gt["mandatory_findings"]):
            per_rubric.append({
                "code": f.code,
                "predicted": f.verdict,
                "ground_truth": gt_f["verdict"],
                "match": f.verdict == gt_f["verdict"],
                "partial_predicted": f.partial,
                "partial_ground_truth": gt_f.get("partial", False),
            })
        predictions.append({
            "record_idx": idx,
            "req_id": row["requirement"]["req_id"],
            "ground_truth_overall": gt_overall,
            "predicted_overall": pred_overall,
            "match": pred_overall == gt_overall,
            "per_rubric": per_rubric,
            "latency_s": latency,
        })
    return predictions, skipped


def _aggregate_metrics(predictions, rubric_codes):
    """Reduce per-record predictions to MLflow metric scalars."""
    if not predictions:
        return {}
    y_true = [p["ground_truth_overall"] for p in predictions]
    y_pred = [p["predicted_overall"] for p in predictions]
    acc = accuracy_score(y_true, y_pred)
    prec, recall, f1, _ = precision_recall_fscore_support(
        y_true, y_pred, average="binary", pos_label="Yes", zero_division=0,
    )
    metrics = {
        "overall_accuracy":  acc,
        "overall_precision": prec,
        "overall_recall":    recall,
        "overall_f1":        f1,
    }
    # Per-rubric
    per_rubric_f1 = []
    for code in rubric_codes:
        rub_y_true = [r["ground_truth"] for p in predictions for r in p["per_rubric"] if r["code"] == code]
        rub_y_pred = [r["predicted"] for p in predictions for r in p["per_rubric"] if r["code"] == code]
        if rub_y_true:
            metrics[f"rubric_accuracy.{code}"] = accuracy_score(rub_y_true, rub_y_pred)
            r_f1 = f1_score(rub_y_true, rub_y_pred, average="macro", zero_division=0)
            metrics[f"rubric_f1.{code}"] = r_f1
            per_rubric_f1.append(r_f1)
    if per_rubric_f1:
        metrics["rubric_macro_f1"] = float(np.mean(per_rubric_f1))
    # Latency
    lats = [p["latency_s"] for p in predictions]
    metrics["mean_latency_s"] = float(np.mean(lats))
    metrics["p50_latency_s"]  = float(np.percentile(lats, 50))
    metrics["p95_latency_s"]  = float(np.percentile(lats, 95))
    metrics["p99_latency_s"]  = float(np.percentile(lats, 99))
    return metrics


def _plot_confusion_matrix(predictions, out_path):
    y_true = [p["ground_truth_overall"] for p in predictions]
    y_pred = [p["predicted_overall"] for p in predictions]
    labels = ["Yes", "No"]
    cm = confusion_matrix(y_true, y_pred, labels=labels)
    fig, ax = plt.subplots(figsize=(4, 4))
    im = ax.imshow(cm, cmap="Blues")
    ax.set_xticks(range(len(labels))); ax.set_xticklabels(labels)
    ax.set_yticks(range(len(labels))); ax.set_yticklabels(labels)
    for i in range(len(labels)):
        for j in range(len(labels)):
            ax.text(j, i, str(cm[i][j]), ha="center", va="center", color="black")
    ax.set_xlabel("Predicted"); ax.set_ylabel("Ground truth")
    ax.set_title("Overall verdict — confusion matrix")
    plt.tight_layout()
    plt.savefig(out_path, dpi=120)
    plt.close(fig)


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--component", choices=("test_suite_reviewer", "test_case_reviewer"), required=True)
    ap.add_argument("--fixture", type=Path, required=True)
    ap.add_argument("--ground-truth", type=Path, required=False,
                    help="outputs.jsonl with ground-truth synthesized/aggregated assessment")
    ap.add_argument("--run-name", required=False)
    ap.add_argument("--max-concurrent", type=int, default=10)
    args = ap.parse_args()

    inputs = [json.loads(l) for l in args.fixture.read_text(encoding="utf-8").splitlines() if l.strip()]
    ground_truth = (
        [json.loads(l) for l in args.ground_truth.read_text(encoding="utf-8").splitlines() if l.strip()]
        if args.ground_truth else None
    )

    mlflow.set_experiment(f"{args.component}-{args.fixture.parent.name}")
    with mlflow.start_run(run_name=args.run_name):
        # Pin everything reproducibility-relevant
        client = RateLimitOpenAIClient(api_key=os.getenv("OPENAI_API_KEY"))
        model = os.getenv("TEST_MODEL", "gpt-4o-mini")
        prompt_config = settings.prompt_config

        mlflow.log_params({
            "component":  args.component,
            "model":      model,
            "git_sha":    _git_sha(),
            "git_dirty":  _git_dirty(),
            "prompt_decomposer":  prompt_config.decomposer,
            "prompt_summarizer":  prompt_config.summarizer,
            "prompt_coverage":    prompt_config.coverage,
            "prompt_synthesizer": prompt_config.synthesizer,
            "fixture_path":   str(args.fixture),
            "fixture_sha256": _file_sha256(args.fixture),
            "fixture_size":   len(inputs),
            "max_concurrent": args.max_concurrent,
        })
        mlflow.set_tags({
            "env":               os.getenv("AUTOQA_ENV", "local"),
            "prompt_set_label":  os.getenv("PROMPT_SET_LABEL", "default"),
        })

        # Run pipeline
        t0 = time.perf_counter()
        if args.component == "test_suite_reviewer":
            completed = await _run_pipeline_rtm(client, model, inputs, args.max_concurrent)
            predictions, skipped = _score_rtm(completed, ground_truth)
            rubric_codes = ["M1", "M2", "M3", "M4", "M5"]
        else:
            # ... TC variant (mirrors RTM with TestCaseAssessment + 5 objective ids)
            raise NotImplementedError("TC component — fill in mirror of _run_pipeline_rtm + _score_tc")
        wall_clock_s = time.perf_counter() - t0

        # Metrics
        metrics = _aggregate_metrics(predictions, rubric_codes)
        metrics["aggregator_skip_rate"] = skipped / max(len(inputs), 1)
        metrics["wall_clock_s"] = wall_clock_s
        mlflow.log_metrics(metrics)

        # Per-record step metrics (optional)
        for p in predictions:
            mlflow.log_metric("record_overall_correct", int(p["match"]), step=p["record_idx"])
            mlflow.log_metric("record_latency_s", p["latency_s"], step=p["record_idx"])

        # Artifacts
        run_dir = Path("logs") / "mlflow_run"
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "predictions.jsonl").write_text(
            "\n".join(json.dumps(p) for p in predictions), encoding="utf-8")
        failures = [p for p in predictions if not p["match"]]
        (run_dir / "failures.jsonl").write_text(
            "\n".join(json.dumps(p) for p in failures), encoding="utf-8")
        _plot_confusion_matrix(predictions, run_dir / "confusion_matrix.png")
        (run_dir / "prompt_versions.json").write_text(
            json.dumps(_prompt_versions_manifest(prompt_config), indent=2), encoding="utf-8")
        mlflow.log_artifacts(str(run_dir))

        print(f"[mlflow] run complete: overall_accuracy={metrics.get('overall_accuracy'):.3f}, "
              f"wall_clock={wall_clock_s:.1f}s, skipped={skipped}/{len(inputs)}")


if __name__ == "__main__":
    asyncio.run(main())
```

## Tracing — capture LangGraph execution per record

Three options, pick what fits the use case:

1. **mlflow.langchain.autolog()** — call once before any pipeline invocation.
   Auto-captures every LangChain/LangGraph LLM call as an MLflow trace. Works
   out of the box; no per-call instrumentation needed.

   ```python
   import mlflow
   mlflow.langchain.autolog()
   # ... rest of evaluation harness
   ```

2. **Manual trace per record** — for finer control:

   ```python
   with mlflow.start_span(name=f"record-{idx}") as span:
       span.set_attribute("req_id", row["requirement"]["req_id"])
       result = await graph.graph.ainvoke(state)
       span.set_attribute("predicted_verdict",
                          result["synthesized_assessment"].overall_verdict)
   ```

3. **Serialize LangGraph state** to `traces/{record_idx}.json` and log as
   artifact. Cheaper than full tracing but loses the timing breakdown.

For high-volume evaluation runs (200+ records), prefer option 1 or 3 to avoid
trace-API rate-limit / storage cost.

## Run comparison + promotion

### Comparing two runs

In the MLflow UI: filter the experiment by `prompt_set_label`, sort by
`overall_f1` or `rubric_macro_f1`. The diff view shows param-level deltas.

Programmatically:

```python
from mlflow.tracking import MlflowClient
client = MlflowClient()
runs = client.search_runs(
    experiment_ids=[exp_id],
    filter_string="tags.prompt_set_label = 'v6-stack' OR tags.prompt_set_label = 'v5-stack'",
    order_by=["metrics.overall_f1 DESC"],
)
```

### Promotion path

When a prompt set beats the baseline on `rubric_macro_f1` AND
`overall_accuracy` AND wall-clock isn't materially worse:

1. Tag the winning run: `mlflow.set_tag("status", "promoted")`.
2. Register the model (the prompt+config bundle) under a registered-model
   name like `test_suite_reviewer-prompt-config`:
   ```python
   client.create_registered_model("test_suite_reviewer-prompt-config")
   client.create_model_version(
       name="test_suite_reviewer-prompt-config",
       source=run.info.artifact_uri,
       run_id=run.info.run_id,
   )
   ```
3. Apply the alias `production`:
   ```python
   client.set_registered_model_alias(
       "test_suite_reviewer-prompt-config", "production", version_number,
   )
   ```
4. Update `autoqa/core/config.py::PromptConfig` defaults to match the promoted
   versions (the source of truth in code; MLflow registry is the audit log).

## CI/CD integration (regression gate)

Run the harness as a CI job on every PR:

```yaml
# .github/workflows/eval.yml (sketch)
- name: Run MLflow evaluation
  env:
    OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
    MLFLOW_TRACKING_URI: ${{ secrets.MLFLOW_TRACKING_URI }}
    PROMPT_SET_LABEL: pr-${{ github.event.pull_request.number }}
    AUTOQA_ENV: ci
  run: |
    uv run python scripts/evaluate_with_mlflow.py \
      --component test_suite_reviewer \
      --fixture tests/fixtures/test-suite-reviewer-200/inputs.jsonl \
      --ground-truth tests/fixtures/test-suite-reviewer-200/outputs.jsonl

- name: Gate on metric thresholds
  run: |
    uv run python scripts/check_eval_gate.py \
      --min-overall-accuracy 0.85 \
      --min-rubric-macro-f1 0.80 \
      --max-aggregator-skip-rate 0.05
```

`check_eval_gate.py` reads the most recent run for the experiment, asserts
each metric clears its threshold, and exits non-zero on regression. Tune the
thresholds against the baseline run's measured values, leaving a small
buffer (e.g. baseline_accuracy - 0.03).

## Drift detection (optional but recommended)

Schedule a periodic re-run against the same fixture (e.g. weekly cron) — when
the upstream LLM provider updates the model behind `gpt-4o-mini`, you'll see
metric drift in MLflow before users do. Tag the scheduled runs with
`env=scheduled-drift` and alert when `overall_accuracy` drops > X percentage
points vs the rolling 4-week median.

## MLOps best-practice checklist

- ✓ Every run pins git_sha, model, and every prompt-template version.
- ✓ Fixture identity captured by SHA256 hash, not just path.
- ✓ Every metric is logged from the same scoring function (no ad-hoc per-run
  calculations).
- ✓ Failures (`predictions.jsonl` rows where `match=False`) are an artifact,
  not just a stdout dump — searchable across runs.
- ✓ Latency is logged as percentiles, not just means (LLM tail latency
  matters).
- ✓ Aggregator skip rate is a first-class metric — silent JSON-parse failures
  are a frequent regression mode.
- ✓ Calibration metrics (partial-flag accuracy) are tracked separately from
  verdict accuracy — partial-flag drift is a softer regression signal but a
  real one.
- ✓ Run names include git sha + prompt set label so the experiment list is
  scannable without opening each run.
- ✓ Tags carry environment + owner — easy filtering of CI vs local vs
  scheduled runs.
- ✓ Promotion goes via Model Registry alias, not by editing config and hoping
  someone reviews. Aliases are auditable and reversible.
- ✓ CI gate uses metric thresholds tied to a measured baseline, not arbitrary
  round numbers.

## Pitfalls

- **MLflow tracking server contention** — `file:./mlruns` works for one user
  but corrupts under concurrent writes. Use a real backend (PostgreSQL +
  S3 artifact store) the moment more than one engineer is logging.
- **Token/cost tracking requires usage instrumentation** — autoqa's
  `RateLimitOpenAIClient` doesn't currently surface token counts to MLflow.
  If cost is a metric you need, instrument the client to return usage in the
  response object and aggregate in the harness.
- **mlflow.langchain.autolog() can blow up payload sizes** — for 200-record
  runs at MAX_CONCURRENT=10, autolog produces ~2000 trace spans. Consider
  sampling (`autolog(log_traces_sample_rate=0.1)`) or option 3 (state-dump
  artifacts) instead.
- **Pinning prompt_versions in params doesn't pin prompt CONTENT** — the
  template files can be edited without changing filename. The
  `prompt_versions.json` artifact carries the SHA256 of each template body to
  detect this; treat any run where the SHA differs from the registered version
  as untrusted.
- **N-A handling in F1 metrics** — sklearn's `f1_score` treats N-A as a third
  class; for RTM rubrics this is correct. For TC rubrics (binary Yes/No only)
  use `average="binary"` with `pos_label="Yes"`.
- **Confusion-matrix imbalance** — when known-good and known-bad classes are
  imbalanced (e.g. 70/30), accuracy is misleading. Always log F1 alongside
  accuracy, and prefer macro-F1 for imbalanced rubric cells.

## Verification

After running the harness once:

1. Open `MLFLOW_TRACKING_URI` (e.g. `mlflow ui` for local). Confirm the
   experiment appears with one run.
2. Inspect run params — every prompt-template filename + git_sha is present.
3. Inspect run metrics — `overall_accuracy`, `rubric_macro_f1`, and
   `aggregator_skip_rate` all populated.
4. Inspect artifacts — `predictions.jsonl` row count equals fixture size minus
   skipped, `confusion_matrix.png` renders, `prompt_versions.json` carries
   SHA256s.
5. Run the harness a second time with one prompt version flipped (e.g.
   synthesizer-v6 → synthesizer-v5). Confirm the experiment now lists 2 runs
   and the diff view shows the version delta + the metric impact.

## Out of scope

- Building the labelled fixture itself — use `generate-rtm-dataset` /
  `generate-tc-dataset`.
- Training new LLMs / fine-tuning — this skill is for *evaluating*, not
  training. Fine-tuning workflows would log model artifacts via
  `mlflow.pyfunc` instead of `mlflow.log_artifacts`.
- CI infrastructure setup (GitHub Actions / Azure Pipelines / Jenkins) — the
  YAML sketch above is illustrative; adapt to the project's existing CI.
- Cost optimisation — beyond logging tokens/cost as metrics, this skill
  doesn't prescribe how to reduce spend.
