# Reproducibility

This document describes the environment, software versions, and steps required to re-run the experiments described in the thesis.

## Hardware

| Role | Device | Specs |
|---|---|---|
| Server | Raspberry Pi 5 | 16 GB RAM, 1 TB NVMe (USB 3.2 enclosure), 2.5 GbE |
| Agent  | Raspberry Pi 5 | 16 GB RAM, 1 TB NVMe (USB 3.2 enclosure), 2.5 GbE |

The original setup was 2 nodes; a single-node cluster works for smoke testing but produces less stable timing because of pod scheduling pressure.

## Software Versions

| Component | Version | Notes |
|---|---|---|
| k3s | v1.30.x | One server + one agent, default flannel CNI |
| ArgoCD | 2.13+ | Installed via upstream Helm chart |
| Argo Rollouts | 1.8.4 | Image tag pinned in WorkflowTemplates |
| Argo Workflows | 3.5+ | Installed via upstream Helm chart |
| Argo Events | 1.9+ | EventBus uses NATS JetStream (default) |
| Istio sidecar mode | 1.28.3 | Namespace: `podinfo` |
| Istio ambient mode | 1.29.0 | Namespace: `podinfo-ambient` (ztunnel + waypoint) |
| kube-prometheus-stack | 65.x | Helm release name **must** match the `prometheus-url` parameter (see below) |
| Loki / Tempo / Pyroscope | (current) | Optional for traces and profiles dashboards |
| podinfo | v6.5.4 (stable), v6.6.0 (canary) | `ghcr.io/stefanprodan/podinfo` |
| Storage | Longhorn | 2 replicas |
| TLS | cert-manager | DNS-01 solver against any DNS provider you control |

## Prerequisites Outside This Repo

- A Kubernetes cluster (k3s, kind, or similar) with `kubectl` access.
- A working `kube-prometheus-stack` Helm release.
- A working `argo-cd`, `argo-rollouts`, `argo-workflows`, and `argo-events` install (or apply `manifests/platform/argo-events/` for the EventBus).
- A DNS provider for cert-manager DNS-01 challenges if you use the public Gateway. The original setup uses Cloudflare; the secret is **not** included in this repo. Replace the cert-manager `ClusterIssuer` with one matching your provider, or skip TLS by adjusting `manifests/experiments/common/istio-public-gateway/gateway.yaml`.

## Post-Switch Wait (Mandatory)

After a mode switch (or any cluster restart) wait at least 2 minutes before running the pre-experiment checks or submitting a chaos workflow. The PrometheusRule has `for: 1m`, so the cluster needs at least two scrape cycles on the new mesh's metric labels (15 s `interval` plus the 1 m `for` window) before alert state is steady. `scripts/validate-telemetry.sh <mode>` verifies that the active mode's Istio metrics already carry the expected labels; if it reports missing time series, wait one more scrape cycle and re-run.

## prometheus-url Parameter

The `WorkflowTemplate`s under `manifests/automation/` embed the Prometheus URL as a workflow parameter. The default is

```
http://grafana-prometheus-stack-k-prometheus.monitoring.svc.cluster.local:9090
```

This URL is only correct when your kube-prometheus-stack Helm release is named `grafana-prometheus-stack` and lives in the `monitoring` namespace. If your release name or namespace differ, override the parameter when triggering Workflows:

```bash
argo submit --from workflowtemplate/chaos-experiment \
  -p prometheus-url="http://<your-release>-kube-prom-prometheus.<your-ns>.svc.cluster.local:9090" \
  -p mesh-mode=sidecar -p fault-percentage=80 -p traffic-duration=150
```

Or edit the `default` value in `workflow-template*.yaml` once and commit the change to your fork.

## Bootstrap Sequence

For the rationale behind the order (why a clean `none` step is mandatory, why ArgoCD prune is enabled, why the podinfo Rollouts apps stay manual-sync) see thesis §3.4. The operational steps are:

1. **Cluster up.** Install k3s on both Pis, join the agent to the server.
2. **GitOps bootstrap.** Install ArgoCD; apply `manifests/argocd/ba2-project.yaml` and `manifests/argocd/ba2-experiment.application.yaml`. ArgoCD reads the rest of this repo via the rewritten `repoURL` (https://github.com/dro42/ba2-thesis-artifact.git).
3. **Platform.** Install kube-prometheus-stack, argo-rollouts, argo-workflows, argo-events. The `manifests/platform/argo-events/` directory provides only the EventBus and metrics service; the controllers themselves are installed via Helm.
4. **Mode select.** Edit the `ba2-experiment` Application's `path:` to point at one of `manifests/experiments/modes/{istio-sidecar,istio-ambient}`. ArgoCD rolls out the mesh + the podinfo overlay. Wait the post-switch 2 minutes (above) before the first run.
5. **Run.** `scripts/run-experiment-batch.sh` orchestrates a batch (default 10 runs) and writes timing JSONs to `experiments/results/<mode>/<timestamp>/`.

## Reproducing Without a Cluster

The bundled `examples/results/` directory contains one full 10-run batch per mode, sufficient to reproduce the analysis:

```bash
cd analysis
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python thesis_stats.py all \
  ../examples/results/sidecar/20260403-123733 \
  ../examples/results/ambient/20260403-184055
```

Output figures land in `analysis/output/` (or as configured via CLI flags); see `analysis/README.md`.

## Common Pitfalls

- **Different Helm release name** for kube-prometheus-stack -> `prometheus-url` mismatch -> the chaos workflow's metrics-snapshot step silently produces `no-data`. Check the value in any `run-N-timing.json`; if `metrics_snapshot.stable_error_rate` is `"no-data"`, the URL is wrong.
- **CNI conflicts on switch.** ArgoCD prune must be enabled; the `cleanup-check` PreSync hook in `manifests/experiments/common/cleanup-check/` aborts a sync if leftover CRDs from the previous mode are still bound. Investigate first before disabling the hook.
- **Ambient mode label**. The fault-injection step toggles the `istio.io/dataplane-mode=ambient` label on the `argo-events` namespace so workflow steps remain mesh-attached during chaos. This is automated in the workflow.
