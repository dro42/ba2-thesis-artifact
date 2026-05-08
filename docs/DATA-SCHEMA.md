# Data Schema

This document describes the on-disk format produced by `scripts/run-experiment-batch.sh` and consumed by `scripts/analyze-results.py` and `analysis/thesis_stats.py`.

## Directory Structure

```
experiments/results/
└── <mode>/                       # "sidecar" or "ambient"
    └── <YYYYMMDD-HHMMSS>/        # batch start time, UTC, no separators
        ├── batch-meta.json
        ├── resources-pre.json
        ├── resources-post.json
        ├── run-N-timing.json     # one per run (N = 1..10 by default)
        ├── run-N-workflow.json   # one per run (full Argo Workflow object dump)
        └── run-N-log.txt         # one per run (workflow logs)
```

## `batch-meta.json`

Top-level metadata about the batch.

```json
{
  "batch_id": "20260403-123733",
  "mesh_mode": "sidecar",
  "started_at": "2026-04-03T12:37:33Z",
  "completed_at": "2026-04-03T13:14:02Z",
  "n_runs": 10,
  "fault_percentage_default": 80,
  "traffic_duration_s_default": 150,
  "git_sha": "<infra-repo SHA at run time>",
  "k8s_version": "v1.30.x",
  "istio_version": "1.28.3",
  "podinfo_stable": "v6.5.4",
  "podinfo_canary": "v6.6.0"
}
```

## `run-N-timing.json` (Primary Source for RQ1+RQ2)

```json
{
  "experiment_id": "<UUIDv4>",
  "timestamp": "<ISO 8601 UTC>",
  "mesh_mode": "sidecar | ambient",
  "fault_percentage": 80,
  "traffic_duration_s": 150,
  "timing": {
    "t0_fault_injected":   1775220045,    // UNIX seconds
    "t1_alert_pending":    1775220080,    // UNIX seconds, or null
    "t2_alert_firing":     1775220146,    // UNIX seconds, or null
    "t4_failover_workflow": "name=podinfo-failover-sidecar-h2gkm[0]",
    "t5_collection":       1775220520
  },
  "deltas_seconds": {
    "t0_to_t1": 35,        // alert detection latency
    "t1_to_t2": 66,        // pending->firing window (PrometheusRule for: 1m + scrape)
    "t0_to_t2": 101,       // total time fault->firing
    "t0_to_t5": 475        // end-to-end batch duration
  },
  "metrics_snapshot": {
    "stable_error_rate":      "0.4070128717265868",  // string, parse as float
    "stable_p99_latency_ms":  "4.940613026819923"
  },
  "rollout": {
    "phase":   "Healthy | Degraded | Paused | Progressing | ...",
    "message": "<Argo Rollouts message>"
  },
  "outcome": "remediated | true_negative | false_negative | false_positive | incomplete"
}
```

### Outcome Decision Matrix

```
                    fault_percentage = 0      fault_percentage > 0
                   ┌──────────────────────┬──────────────────────────┐
rollout=Healthy    │   true_negative      │   remediated (good)      │
                   │   (good)             │                          │
                   ├──────────────────────┼──────────────────────────┤
rollout=Degraded   │   false_positive     │   remediated (good,      │
                   │   (BAD)              │   canary correctly       │
                   │                      │   rejected)              │
                   └──────────────────────┴──────────────────────────┘
```

`incomplete` covers all other rollout phases (Progressing, Paused, ...) and means the run is not analyzable.

### Timing Extraction Resilience

`run-N-timing.json` is the primary source for the RQ1 and RQ2 statistics, but under fault load Argo Workflows occasionally fails to upload its declared output artifact. To keep batches usable, `scripts/run-experiment-batch.sh` reads the timing JSON through a four-tier fallback. Tiers run in order; the first one that yields a parseable JSON wins. If none succeed, `outcome` is set to `incomplete` and the run is excluded from the analysis.

| Tier | Source | When it applies |
|---|---|---|
| 1 | `argo cp ... --artifact-name=timing-json` of the chaos workflow output artifact | Happy path; the chaos workflow declared its output and Argo's artifact server returned the file |
| 2 | Inline artifact embedded in `run-N-workflow.json` (`status.nodes[].outputs.artifacts[].raw.data`, base64) | The workflow finished but `argo cp` could not retrieve the artifact; the timing JSON is still inside the Workflow object dump |
| 3 | Delimiter parsing of `run-N-log.txt` for `---TIMING-JSON-START---` / `---TIMING-JSON-END---` markers | The chaos workflow shell scripts always echo the timing JSON between these markers (see `manifests/automation/workflow-template-chaos.yaml`); recovers data even when both artifact paths failed |
| 4 | Line-by-line scan of `run-N-log.txt` for human-readable timestamps (`T0 (fault injected): ...`, `T1 (alert pending): ...`, ...) | Last resort when the JSON markers are also missing (truncated log, killed workflow); produces a synthetic timing JSON with `experiment_id: "parsed-from-log"` and `rollout.phase: "unknown"` so it is easy to filter out |

Tiers 1-3 produce identically structured JSON and are treated equivalently in the analysis; tier 4 records are flagged by `experiment_id == "parsed-from-log"` (and a missing `rollout.phase`) so they can be inspected by hand before inclusion in the cross-mode comparison. The implementation lives in `scripts/run-experiment-batch.sh` (the four blocks gated on `TIMING_EXTRACTED`).

## `run-N-workflow.json`

A full `kubectl get workflow ... -o json` dump of the chaos Workflow object. Used as a forensic record for failures and as the source for tiers 2 and 3 of the timing-extraction fallback above. Schema follows the upstream Argo Workflows API; see `argoproj.io/v1alpha1` Workflow CRD.

## `run-N-log.txt`

Plaintext output of `argo logs <workflow>`. Required because under fault load some Argo artifact uploads fail and the timing JSON has to be reconstructed from log content via the `---TIMING-JSON-START---` / `---TIMING-JSON-END---` delimiters embedded in the workflow shell scripts.

## `resources-{pre,post}.json`

CPU and memory snapshots of every BA2-relevant pod, captured before and after the batch. Used for RQ3-adjacent observations on resource overhead.

```json
{
  "captured_at": "2026-04-03T12:37:32Z",
  "pods": [
    {
      "namespace": "podinfo",
      "name": "podinfo-stable-xxx",
      "cpu_millicores": 12,
      "memory_mib": 34
    }
  ]
}
```

## CSV Output of `scripts/analyze-results.py`

The analyze script emits a flat CSV per batch. Columns:

| Column | Source | Type |
|---|---|---|
| `run_id` | `run-N` (1-based) | int |
| `mesh_mode` | `mesh_mode` | str |
| `fault_pct` | `fault_percentage` | int |
| `t0_to_t1_s` | `deltas_seconds.t0_to_t1` | float / null |
| `t1_to_t2_s` | `deltas_seconds.t1_to_t2` | float / null |
| `t0_to_t2_s` | `deltas_seconds.t0_to_t2` | float / null |
| `t0_to_t5_s` | `deltas_seconds.t0_to_t5` | float |
| `stable_error_rate` | `metrics_snapshot.stable_error_rate` | float |
| `stable_p99_latency_ms` | `metrics_snapshot.stable_p99_latency_ms` | float |
| `rollout_phase` | `rollout.phase` | str |
| `outcome` | `outcome` | str |

Null timing fields appear when the alert never moved out of `pending` (typical for `fault_percentage = 0`).
