# Experiment Execution

How to run the BA2 experiments end-to-end and produce the data the analysis pipeline consumes. Pipeline internals (the T0-T5 timing chain, decision thresholds, mode-switch state machine) live in [ARCHITECTURE.md](ARCHITECTURE.md). Cluster bring-up and software versions live in [REPRODUCIBILITY.md](REPRODUCIBILITY.md). The on-disk shape of the produced data lives in [DATA-SCHEMA.md](DATA-SCHEMA.md). The downstream analysis lives in [../analysis/README.md](../analysis/README.md).

## Prerequisites

A k3s cluster with `kube-prometheus-stack`, ArgoCD, Argo Rollouts, Argo Workflows, and Argo Events deployed; the `ba2-experiment` ArgoCD Application installed from `manifests/argocd/`; and `kubectl`, `argo`, `argocd`, `python3` on `PATH`. See [REPRODUCIBILITY.md](REPRODUCIBILITY.md) for the full bring-up.

## 1. Switch mesh mode

Mode is selected by the `path` field of the `ba2-experiment` ArgoCD Application:

| Target | Path |
|---|---|
| Clean slate / teardown | `manifests/experiments/modes/none` |
| Istio sidecar | `manifests/experiments/modes/istio-sidecar` |
| Istio ambient | `manifests/experiments/modes/istio-ambient` |

Edit `manifests/argocd/ba2-experiment.application.yaml`, commit, push, then re-apply and sync:

```bash
git add manifests/argocd/ba2-experiment.application.yaml
git commit -m "experiment: switch to <mode>"
git push

kubectl apply -f manifests/argocd/ba2-experiment.application.yaml   # picks up the new path
argocd app sync ba2-experiment
argocd app wait ba2-experiment --health --timeout 300
```

Always go through `none` between sidecar and ambient so the previous mesh's CRDs are pruned (see thesis §3.4 for the design reason; the state machine itself is in [ARCHITECTURE.md](ARCHITECTURE.md)).

After the switch, sync the matching podinfo Rollouts app (these are manual-sync so ArgoCD does not fight live rollout mutations):

```bash
# sidecar
argocd app sync podinfo-dev-istio-rollouts && argocd app wait podinfo-dev-istio-rollouts --health
# ambient
argocd app sync podinfo-dev-istio-ambient-rollouts && argocd app wait podinfo-dev-istio-ambient-rollouts --health
```

## 2. Pre-flight checks

```bash
./scripts/pre-experiment-check.sh sidecar     # or ambient
./scripts/validate-telemetry.sh sidecar       # or ambient
```

`pre-experiment-check.sh` validates that ArgoCD, Argo Workflows, and Argo Rollouts are healthy, that `podinfo-stable` and `podinfo-canary` are running, and that the failover Sensor is loaded. `validate-telemetry.sh` queries Prometheus to confirm the active mode's Istio metric labels are populated (`destination_service` for sidecar, `destination_service_name` for ambient).

## 3. Run experiments

### Single run (smoke test, ~5 min)

```bash
argo submit --from workflowtemplate/chaos-experiment -n argo-events \
  -p mesh-mode=sidecar \
  -p fault-percentage=80 \
  -p traffic-duration=150 \
  --watch
```

If your `kube-prometheus-stack` Helm release name differs from the default, also pass `-p prometheus-url=...`. See [REPRODUCIBILITY.md](REPRODUCIBILITY.md).

### Batch run (canonical thesis data, n=10, ~80 min)

```bash
./scripts/run-experiment-batch.sh sidecar 10 80 150
# positional args: <sidecar|ambient> <num-runs> [fault-pct=60] [traffic-dur=150] [outdir]
```

Results land in `experiments/results/<mode>/<UTC-timestamp>/`. The directory holds `run-N-timing.json`, `run-N-log.txt`, and `run-N-workflow.json` per run, plus `batch-meta.json` and `resources-{pre,post}.json`. See [DATA-SCHEMA.md](DATA-SCHEMA.md) for the field-by-field schema.

The thesis batches use `fault-percentage=80`, `traffic-duration=150`. Defaults are 60 % and 150 s.

## 4. What each run does

The setup-fault-pipeline-decision-cleanup loop is described in thesis §4.4 (and summarised in Fig. `\ref{fig:remediation-pipeline}`). Wall-clock per run is ~5-7 minutes: ~15 s setup, ~150 s fault + traffic generation, ~60-90 s alert pipeline (T1 -> T2 -> T4), ~60 s decision and cleanup. Each run records six timestamps and writes `run-N-timing.json`; the field-by-field schema and the four-tier resilience used when artifact upload fails are documented in [DATA-SCHEMA.md](DATA-SCHEMA.md). Stage-to-manifest mapping is in [ARCHITECTURE.md](ARCHITECTURE.md).

## 5. Analyze

Two batches (one sidecar, one ambient) are needed for the cross-mode comparison the thesis reports:

```bash
cd analysis
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

python thesis_stats.py all \
  ../experiments/results/sidecar/<ts> \
  ../experiments/results/ambient/<ts>
```

Subcommands, output figures, and the statistical methods used are documented in [../analysis/README.md](../analysis/README.md).

If you do not have a cluster, run the same command against the bundled batches under `examples/results/` to reproduce the thesis figures from the included data.

## Full reproduction checklist

```
[ ] Switch to none    -> commit, push, kubectl apply, argocd app sync ba2-experiment, wait
[ ] Switch to sidecar -> commit, push, kubectl apply, argocd app sync ba2-experiment, wait
[ ] argocd app sync podinfo-dev-istio-rollouts && wait
[ ] Wait ~2 min for Prometheus scrape
[ ] ./scripts/pre-experiment-check.sh sidecar
[ ] ./scripts/validate-telemetry.sh sidecar
[ ] ./scripts/run-experiment-batch.sh sidecar 10 80 150     (~80 min)

[ ] Switch to none    -> commit, push, kubectl apply, sync, wait
[ ] Switch to ambient -> commit, push, kubectl apply, sync, wait
[ ] argocd app sync podinfo-dev-istio-ambient-rollouts && wait
[ ] Wait ~2 min for Prometheus scrape
[ ] ./scripts/pre-experiment-check.sh ambient
[ ] ./scripts/validate-telemetry.sh ambient
[ ] ./scripts/run-experiment-batch.sh ambient 10 80 150     (~80 min)

[ ] cd analysis && python thesis_stats.py all \
      ../experiments/results/sidecar/<ts> \
      ../experiments/results/ambient/<ts>
[ ] Review figures in analysis/output/
```

Total wall-clock: ~3-4 hours including mode switches and the 120 s cooldown between runs.

## Gotchas

1. **Single-node EventBus needs a status patch.** Argo Events' EventBus controller hardcodes `replicas: 3` in JetStream config; on a 1-node k3s the cluster never forms. Patch it once after install:
   ```bash
   kubectl patch eventbus default -n argo-events --subresource=status --type=merge \
     -p '{"status":{"config":{"jetstream":{"streamConfig":"replicas: 1\nmaxbytes: 1GB\nmaxmsgs: 1000000\nretention: 0\nmaxage: 72h\nduplicates: 300s\ndiscard: 0\n"}}}}'
   ```
2. **Wait ~2 min after a mode switch before pre-flight checks.** Prometheus needs at least one full scrape cycle on the new mesh's metrics for `validate-telemetry.sh` to find correctly-labeled time series.
