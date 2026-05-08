# Provenance

This document is the inverse of the thesis appendix. The appendix lists which artifact files the thesis cites as entry points; this file traces every public artifact file back to its private origin in `ba-gitops-infra` (or marks it as authored fresh for this artifact), so the examiner can verify that nothing was silently introduced, removed, or sanitised in a way that would affect experimental validity.

## Source Repositories

| Symbol  | Origin                                             | Visibility                |
| ------- | -------------------------------------------------- | ------------------------- |
| `INFRA` | https://github.com/dro42/ba-gitops-infra (private) | private, multi-tenant     |
| `BA2WS` | https://github.com/dro42/ba2-workspace (private)   | private, thesis workspace |
| `NEW`   | originally authored for this artifact              | public                    |

## File-by-File Mapping

### Manifests — `argocd/`

| Public path                                                            | Origin                                                                          | Notes                          |
| ---------------------------------------------------------------------- | ------------------------------------------------------------------------------- | ------------------------------ |
| `manifests/argocd/ba2-project.yaml`                                    | INFRA: `gitops-infra/clusters/k3s/infra/argocd/ba2-project.yaml`                | verbatim                       |
| `manifests/argocd/ba2-experiment.application.yaml`                     | INFRA: `gitops-infra/clusters/k3s/infra/argocd/ba2-experiment.application.yaml` | `repoURL` and `path` rewritten |
| `manifests/argocd/podinfo-dev-istio-rollouts.application.yaml`         | INFRA: `gitops-infra/clusters/k3s/argocd/apps/...`                              | `repoURL` and `path` rewritten |
| `manifests/argocd/podinfo-dev-istio-ambient-rollouts.application.yaml` | INFRA                                                                           | `repoURL` and `path` rewritten |
| `manifests/argocd/podinfo-automation.application.yaml`                 | INFRA                                                                           | `repoURL` and `path` rewritten |

### Manifests — `platform/argo-events/`

| Public path                                                              | Origin                                                                               |
| ------------------------------------------------------------------------ | ------------------------------------------------------------------------------------ |
| `manifests/platform/argo-events/argo-events-app.yaml`                    | INFRA: `gitops-infra/clusters/k3s/infra/argo-events/argo-events-app.yaml` (verbatim) |
| `manifests/platform/argo-events/eventbus.yaml`                           | INFRA: `.../argo-events/resources/eventbus.yaml` (verbatim)                          |
| `manifests/platform/argo-events/argo-events-metrics-service.yaml`        | INFRA: `.../argo-events/resources/...` (verbatim)                                    |
| `manifests/platform/argo-events/argo-events-metrics-servicemonitor.yaml` | INFRA: `.../argo-events/resources/...` (verbatim)                                    |
| `manifests/platform/argo-events/kustomization.yaml`                      | INFRA: `.../argo-events/kustomization.yaml` (verbatim)                               |

### Manifests — `experiments/`

The full subtree at `manifests/experiments/` mirrors INFRA: `gitops-infra/clusters/k3s/experiments/ba2/` (28 files), with `repoURL` and `path` fields rewritten in the embedded ArgoCD `Application` manifests to point to this repository.

### Manifests — `automation/`

All 8 files come verbatim from INFRA: `gitops-infra/apps/podinfo-automation/`:

- `eventsource-webhook.yaml`
- `sensor-failover.yaml`
- `workflow-template.yaml`
- `workflow-template-chaos.yaml`
- `workflow-template-experiment.yaml`
- `workflow-template-canary-abort-test.yaml`
- `rbac.yaml`
- `kustomization.yaml`

The `prometheus-url` parameter inside the workflow templates was kept as-is (default value `grafana-prometheus-stack-k-prometheus.monitoring.svc.cluster.local:9090`); this is cluster-specific, not secret. See `docs/REPRODUCIBILITY.md`.

### Manifests — `monitoring/`

| Public path                                                             | Origin                                                                         |
| ----------------------------------------------------------------------- | ------------------------------------------------------------------------------ |
| `manifests/monitoring/prometheus-rules.yaml`                            | INFRA: `gitops-infra/apps/podinfo-automation/prometheus-rules.yaml` (verbatim) |
| `manifests/monitoring/dashboards/ba2-experiment-ops-dashboard-cm.yaml`  | INFRA: `gitops-infra/apps/monitoring/dashboards/...` (verbatim)                |
| `manifests/monitoring/dashboards/ba2-istio-ambient-dashboard-cm.yaml`   | INFRA (verbatim)                                                               |
| `manifests/monitoring/dashboards/ba2-istio-sidecar-dashboard-cm.yaml`   | INFRA (verbatim)                                                               |
| `manifests/monitoring/dashboards/ba2-istio-telemetry-dashboard-cm.yaml` | INFRA (verbatim)                                                               |
| `manifests/monitoring/dashboards/ba2-podinfo-canary-dashboard-cm.yaml`  | INFRA (verbatim)                                                               |
| `manifests/monitoring/dashboards/ba2-profiles-dashboard-cm.yaml`        | INFRA (verbatim)                                                               |
| `manifests/monitoring/dashboards/ba2-traces-dashboard-cm.yaml`          | INFRA (verbatim)                                                               |

All 7 dashboards are originally authored for this thesis (no `gnetId`, no `__inputs`, no community tags). They are released under Apache-2.0; see `NOTICE`.

### Manifests — `podinfo/` and `istio-telemetry/`

Added during artifact extraction because the copied ArgoCD Applications reference these paths:

| Public path                                              | Origin                                                                             |
| -------------------------------------------------------- | ---------------------------------------------------------------------------------- |
| `manifests/podinfo/base/`                                | INFRA: `gitops-infra/apps/podinfo/base/` (verbatim)                                |
| `manifests/podinfo/overlays/dev-istio-rollouts/`         | INFRA: `gitops-infra/apps/podinfo/overlays/dev-istio-rollouts/` (verbatim)         |
| `manifests/podinfo/overlays/dev-istio-ambient-rollouts/` | INFRA: `gitops-infra/apps/podinfo/overlays/dev-istio-ambient-rollouts/` (verbatim) |
| `manifests/istio-telemetry/`                             | INFRA: `gitops-infra/apps/istio-telemetry/` (verbatim)                             |

This is a deviation from the original plan (which did not list these as copy targets). Without them, the ArgoCD Applications point to nothing.

### Scripts

| Public path                       | Origin                                                           |
| --------------------------------- | ---------------------------------------------------------------- |
| `scripts/pre-experiment-check.sh` | INFRA: `gitops-infra/scripts/pre-experiment-check.sh` (verbatim) |
| `scripts/validate-telemetry.sh`   | INFRA: `gitops-infra/scripts/validate-telemetry.sh` (verbatim)   |
| `scripts/run-experiment-batch.sh` | INFRA: `gitops-infra/scripts/run-experiment-batch.sh` (verbatim) |
| `scripts/snapshot-resources.sh`   | INFRA: `gitops-infra/scripts/snapshot-resources.sh` (verbatim)   |
| `scripts/analyze-results.py`      | INFRA: `gitops-infra/scripts/analyze-results.py` (verbatim)      |

### Analysis

| Public path                 | Origin                                                                  |
| --------------------------- | ----------------------------------------------------------------------- |
| `analysis/thesis_stats.py`  | BA2WS: `.claude/skills/thesis-stats/scripts/thesis_stats.py` (verbatim) |
| `analysis/requirements.txt` | NEW (author authored for this artifact)                                 |
| `analysis/README.md`        | NEW                                                                     |

### Docs

| Public path                    | Origin                                                                                           |
| ------------------------------ | ------------------------------------------------------------------------------------------------ |
| `docs/EXPERIMENT-EXECUTION.md` | BA2WS: `fh_vault/6_Sem/BA2/Experiment/experiment-execution-guide.md` (vault wikilinks rewritten) |
| `docs/ARCHITECTURE.md`         | NEW                                                                                              |
| `docs/REPRODUCIBILITY.md`      | NEW                                                                                              |
| `docs/DATA-SCHEMA.md`          | NEW                                                                                              |
| `docs/PROVENANCE.md`           | NEW (this file)                                                                                  |

### Metadata and Boilerplate

All NEW: `README.md`, `LICENSE` (Apache-2.0 standard text), `NOTICE`, `CITATION.cff`, `.zenodo.json`, `.gitignore`, `manifests/README.md`, `.github/workflows/lint.yml`.

### Examples

| Public path                                 | Origin                                                                                  |
| ------------------------------------------- | --------------------------------------------------------------------------------------- |
| `examples/results/sidecar/20260403-123733/` | INFRA: `gitops-infra/experiments/results/sidecar/20260403-123733/` (verbatim, 33 files) |
| `examples/results/ambient/20260403-184055/` | INFRA: `gitops-infra/experiments/results/ambient/20260403-184055/` (verbatim, 33 files) |

These are real experiment runs performed during thesis work. No redaction was applied because the JSON files contain only:
- UUID experiment IDs
- UNIX timestamps
- Metric values (numeric)
- Argo Workflow object dumps (k8s API objects, no credentials; the only IP visible is a transient broken-pipe error message containing the cluster's RFC1918 service CIDR)

## What Was Excluded

| Excluded path                                                                                                                        | Reason                                                                                              |
| ------------------------------------------------------------------------------------------------------------------------------------ | --------------------------------------------------------------------------------------------------- |
| `INFRA: gitops-infra/clusters/k3s/infra/{authentik,tekton,zigbee2mqtt,mqtt,openhab,influxdb,linkerd-*,pyroscope}/`                   | unrelated cluster bootstrap                                                                         |
| `INFRA: gitops-infra/**/ss_*.yaml`, `**/*-sealed.yaml`                                                                               | sealed-secrets bound to a specific controller key; useless to readers and reveal internal hostnames |
| `INFRA: gitops-infra/clusters/k3s/infra/cert-manager/ss_cloudflare-api-token.yaml`                                                   | Cloudflare DNS-01 token (sealed); replace with your own DNS provider                                |
| `INFRA: scripts/{bootstrap,deploy-monitoring,setup-local-access,seal-secret,fix-*,gen-authentik-oidc-secrets,configure-k3s-oidc}.sh` | general cluster ops, not BA2-specific                                                               |
| `INFRA: infrastructure-overview.md`, `RQ.md`, `Results.md`, `OBSERVABILITY-AUDIT-REMAINING.md`                                       | working notes; their content is reproduced fresh in `docs/`                                         |
| `INFRA: .git/` history                                                                                                               | fresh-repo strategy; this artifact is a single-commit snapshot at the day of submission             |

## Verification

Reproduce the file inventory:

```bash
find /path/to/ba2-thesis-artifact -type f | grep -v '/.git/' | sort > files.txt
wc -l files.txt   # expected: 90 manifest+script files + new metadata + examples
```

For any file marked "verbatim", a `diff` against the corresponding INFRA path should show no changes (modulo line-ending normalization).
