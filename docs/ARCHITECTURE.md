# Architecture

This document is the artifact-facing companion to thesis Chapter 4 (Implementation). The thesis carries the design rationale, the timing-chain semantics, and the figures; this file maps each pipeline stage to the manifest that implements it, names the cluster's namespaces, and pins the decision thresholds and mode-switch state machine to concrete file locations.

## Cluster Topology

```
┌────────────────────────────────────────────────────────────────────────┐
│  k3s cluster (1 server + 1 agent on Raspberry Pi 5, 16 GB each)        │
│                                                                        │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │ argocd            ArgoCD (GitOps controller, app-of-apps)         │  │
│  │ argo-events       EventBus + EventSource + Sensor + Workflow CRDs │  │
│  │ argo-rollouts     Argo Rollouts controller                        │  │
│  │ monitoring        kube-prometheus-stack (Prometheus, AM, Grafana, │  │
│  │                   Loki, Tempo, Alloy, Mimir, Pyroscope)           │  │
│  │ istio-system      istiod, gateways, public Gateway API resource   │  │
│  │ istio-cni         (ambient mode only) ztunnel + waypoint          │  │
│  │ podinfo /         App under test:                                 │  │
│  │ podinfo-ambient   stable v6.5.4, canary v6.6.0, 90/10 split       │  │
│  └──────────────────────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────────────────────┘
```

Mode switching is Git-controlled: ArgoCD watches `manifests/experiments/modes/{none,istio-sidecar,istio-ambient}` and only one is active at any time. A `cleanup-check` PreSync hook prevents starting a new mode while a previous one is still partially mounted.

## Remediation Pipeline (Where to Find What)

The pipeline is the chain `Prometheus -> Alertmanager -> Argo Events -> Argo Workflows -> Argo Rollouts`. Each experiment run records six timestamps `T0..T5` along it (T3 was reserved but proved unnecessary; only T0, T1, T2, T4, T5 reach the timing JSON). For the chain semantics, the dual-signal decision logic, and the timing definitions, see thesis §4.4 and Fig. `\ref{fig:remediation-pipeline}`.

The table below is the artifact-of-record: each stage names the manifest that implements it and the key fields a reader should grep for.

| Pipeline stage | Manifest | Key fields |
|---|---|---|
| PrometheusRule fires (T1 -> T2) | `manifests/monitoring/prometheus-rules.yaml` | `interval: 15s`; `for: 1m` on every rule; alerts `PodInfoStableHighErrorRate` and `PodInfoStableHighLatency` (sidecar) plus `PodInfoAmbientStableHighErrorRate` and `PodInfoAmbientStableHighLatency` (ambient) |
| Alertmanager -> Argo Events bridge | `manifests/automation/eventsource-webhook.yaml` | `EventSource` `webhook` on port 12000; endpoints `/podinfo-stable-health` (sidecar) and `/podinfo-ambient-stable-health` (ambient) |
| Sensor wiring alerts to Workflow trigger | `manifests/automation/sensor-failover.yaml` | `Sensor` `podinfo-failover` filters `body.status: firing` (drops resolved); triggers `failover-sidecar` and `failover-ambient` reference the WorkflowTemplates below |
| Failover Workflow logic (T4) | `manifests/automation/workflow-template.yaml` | `WorkflowTemplate`s `podinfo-failover-sidecar` and `podinfo-failover-ambient`; both abort the canary via Argo Rollouts after a final dual-signal check |
| End-to-end chaos experiment (T0-T5 instrumentation) | `manifests/automation/workflow-template-chaos.yaml` | parameters `mesh-mode`, `fault-percentage`, `traffic-duration`; emits `---TIMING-JSON-START---`/`---TIMING-JSON-END---` log markers consumed by the timing-extraction fallback (see [DATA-SCHEMA.md](DATA-SCHEMA.md)) |
| EventBus prerequisite | `manifests/platform/argo-events/eventbus.yaml` | NATS JetStream; on a single-node k3s the cluster never forms unless `replicas: 1` is patched into the EventBus status (see [EXPERIMENT-EXECUTION.md](EXPERIMENT-EXECUTION.md) "Gotchas") |

## Decision Thresholds

The PrometheusRule trips an alert (and thus the failover) when one of:

- `error_rate > 5 %` over a 1 min window for the canary destination
- `p99_latency_ratio > 2x` (canary p99 / stable p99) over a 1 min window

The exact PromQL is in `manifests/monitoring/prometheus-rules.yaml`. Sidecar and ambient mode use different label matchers (`destination_app=` for sidecar versus `destination_service_name=` for ambient) and the rule contains both alert variants so the PrometheusRule can stay constant across the two mode runs.

## Mode-Switch State Machine

```
modes/none ──> modes/istio-sidecar  ──> experiment runs ──> modes/none
            └─> modes/istio-ambient  ──> experiment runs ──> modes/none
```

The `modes/none` step ensures clean teardown (CNI, ztunnel, sidecar injectors) before the next mode bootstraps. ArgoCD prune is intentionally enabled so out-of-mode resources are deleted on switch.
