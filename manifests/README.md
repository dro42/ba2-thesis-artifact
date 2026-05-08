# Manifests

Apply order, structure, and prerequisites for the BA2 GitOps experiment.

## Apply Order

A clean apply on a fresh cluster proceeds in this sequence (each step waits for ArgoCD to mark the previous one Healthy):

```
1. argocd/ba2-project.yaml                      AppProject defines RBAC for the experiment
2. platform/argo-events/                        EventBus + metrics; required by Sensors
3. argocd/podinfo-automation.application.yaml   Installs automation/ (EventSource + Sensor + WTs + Rules)
4. argocd/ba2-experiment.application.yaml       Mode-switching root: starts at modes/none
5. (set ba2-experiment path to)
   experiments/modes/{istio-sidecar | istio-ambient}
                                                Bootstraps the chosen mesh + the podinfo overlay
```

`scripts/pre-experiment-check.sh` validates that all of the above are Healthy before a batch runs (11 checks).

## Subdirectories

| Path                    | Purpose                                                                                                                                                                                                                                                                             |
| ----------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `argocd/`               | ArgoCD `AppProject` and the 4 root `Application` manifests. The entry points an operator clones the repo to apply by hand.                                                                                                                                                          |
| `platform/argo-events/` | `EventBus` + metrics service. Hard prerequisite for any `EventSource` or `Sensor`. The Argo Events controllers themselves are installed via the upstream Helm chart, not by these YAMLs.                                                                                            |
| `experiments/`          | The mode-switching tree. ArgoCD watches `experiments/modes/{none,istio-sidecar,istio-ambient}`; only one is active at a time.                                                                                                                                                       |
| `automation/`           | The remediation pipeline (RQ1+RQ2): `EventSource` for the Alertmanager webhook, `Sensor` wiring alerts to the failover Workflow, the `WorkflowTemplate`s themselves, and RBAC.                                                                                                      |
| `monitoring/`           | `PrometheusRule` (the alerts that drive the failover) and 7 Grafana dashboards (mounted as ConfigMaps with the `grafana_dashboard` sidecar label).                                                                                                                                  |
| `podinfo/`              | Application under test. `base/` defines the stable Deployment; `overlays/dev-istio-rollouts/` and `overlays/dev-istio-ambient-rollouts/` define the canary `Rollout` and the mesh-mode-specific traffic split (Istio VirtualService for sidecar, HTTPRoute + Waypoint for ambient). |
| `istio-telemetry/`      | The `Telemetry` CR that exports traces to Tempo.                                                                                                                                                                                                                                    |

## Mode-Switching State Machine

For the design rationale (why a parallel BA2 application tree, why auto-sync on the mesh apps but manual-sync on the podinfo Rollouts apps), see thesis §3.4 (GitOps Workflow and Mode Switching). The operational state machine is:

```
modes/none            <- safe / clean state, no mesh, no podinfo
   |
   v
modes/istio-sidecar   <- Istio 1.28.3 sidecar mode + podinfo overlay
   |
   v
modes/none            <- prune sidecar + ambient leftovers
   |
   v
modes/istio-ambient   <- Istio 1.29.0 ambient mode (ztunnel + waypoint) + podinfo overlay
```

The transition through `modes/none` is mandatory; ArgoCD prune is enabled to ensure CNI, sidecar injectors, and ztunnel are fully removed before the next mode bootstraps. The `experiments/common/cleanup-check/` PreSync hook aborts a sync if leftover CRDs are still bound.

## Customization

See `../docs/REPRODUCIBILITY.md` for the customizations every reader needs to apply (Helm release name affects `prometheus-url`, DNS provider for cert-manager, host name in the public Gateway).
