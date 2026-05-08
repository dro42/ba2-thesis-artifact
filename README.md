# BA2 Thesis Artifact: Sidecar vs. Ambient

Companion repository for the bachelor thesis

> **Sidecar vs. Ambient: Telemetry Reliability and Automated Canary Remediation in a GitOps-Managed Kubernetes Environment**

[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
<!-- DOI badge: replace XXXXXXX after the v1.0-thesis-submission tag triggers Zenodo. -->
[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.XXXXXXX.svg)](https://doi.org/10.5281/zenodo.XXXXXXX)

## Purpose

This repository bundles the GitOps manifests, scripts, and analysis code referenced from the thesis so that:

1. The thesis examiner and supervisor can audit every artifact the thesis cites.
2. An independent reader can reproduce the experimental setup on a fresh k3s cluster.

The thesis defines the research questions (decision correctness, remediation speed, telemetry fidelity), the methodology, and the findings. This artifact carries only the operational reality (manifests, schemas, runbook commands, version pins, gotchas) that would otherwise bloat the chapter prose. See the thesis §1.3 for the full RQ statements.

## Repository Layout

```
ba2-thesis-artifact/
├── docs/                    Architecture, reproducibility, data schema, provenance, runbook
├── manifests/
│   ├── argocd/              ArgoCD AppProject + Applications (the entry points)
│   ├── platform/argo-events Argo Events EventBus and metrics service
│   ├── experiments/         Mode-switching tree (modes/, mesh/, common/)
│   ├── automation/          EventSource + Sensor + WorkflowTemplates (RQ1+RQ2 pipeline)
│   ├── monitoring/          PrometheusRule alerts + 7 Grafana dashboards
│   ├── podinfo/             Application under test (base + sidecar/ambient overlays)
│   └── istio-telemetry/     Istio Telemetry CR for Tempo trace export
├── scripts/                 Preflight, batch runner, snapshot, analysis (5 files)
├── analysis/                Cross-mode statistical comparison (thesis_stats.py)
├── examples/results/        One full batch per mode (10 runs) for offline reproduction
└── .github/workflows/       yamllint + shellcheck CI
```

## How to Read This Repo

| If you are...                             | Start here                                                          |
| ----------------------------------------- | ------------------------------------------------------------------- |
| The thesis examiner auditing the appendix | `docs/PROVENANCE.md` (file-by-file mapping back to ba-gitops-infra) |
| Reproducing the experiments               | `docs/REPRODUCIBILITY.md` -> `docs/EXPERIMENT-EXECUTION.md`         |
| Understanding the remediation pipeline    | `docs/ARCHITECTURE.md` (T0-T5 timing chain)                         |
| Validating result files                   | `docs/DATA-SCHEMA.md`                                               |
| Re-running the analysis                   | `analysis/README.md`                                                |

## Quick Start

```bash
# 1) Re-run the analysis on the bundled example batches (no cluster required)
cd analysis
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python thesis_stats.py all \
  ../examples/results/sidecar/20260403-123733 \
  ../examples/results/ambient/20260403-184055
```

A live cluster reproduction requires k3s + ArgoCD + kube-prometheus-stack + Argo Rollouts + Argo Events + Argo Workflows. Full bring-up is described in `docs/REPRODUCIBILITY.md`.

## Hostname and Image Customization

All `*.drozd.cloud` references are the author's domain. Replace them with your own when deploying:

- `manifests/experiments/common/istio-public-gateway/gateway.yaml` references `drozd.cloud/public-istio-gateway` namespace selector and a `drozd-cloud-wildcard` TLS Secret.
- `prometheus-url` workflow parameter in `manifests/automation/workflow-template*.yaml` defaults to `grafana-prometheus-stack-k-prometheus.monitoring.svc.cluster.local:9090` and must be adjusted to your kube-prometheus-stack release name.

Container images point at public registries only (`ghcr.io/stefanprodan/podinfo`, `quay.io/argoproj/...`, `curlimages/curl`, `cgr.dev/chainguard/kubectl`). No private registry is required.

## Versioning and Reproducibility

- The Git tag `v1.0-thesis-submission` matches the state at the day of thesis submission and is the canonical citation target.
- Successive bug-fix tags (`v1.0.x`) keep the same Zenodo DOI prefix.
- The full experiment dataset is intentionally NOT in this repo (the `examples/results/` tree shows only one batch per mode); the complete dataset is archived as a separate Zenodo dataset record and linked from the thesis.

## How to Cite

If this artifact is useful for your work, please cite the thesis and the artifact together. Suggested BibTeX entry:

```bibtex
@software{drozd2026ba2artifact,
  author    = {Drozd, Andreas},
  title     = {{Sidecar vs.\ Ambient}: Telemetry Reliability and Automated
               Canary Remediation in a GitOps-Managed Kubernetes Environment
               -- Thesis Artifact},
  year      = {2026},
  version   = {v1.0-thesis-submission},
  publisher = {Zenodo},
  doi       = {10.5281/zenodo.XXXXXXX},
  url       = {https://github.com/dro42/ba2-thesis-artifact}
}
```

A `CITATION.cff` is provided so GitHub renders a citation widget automatically.

## License

Source code, manifests, scripts, dashboards, and documentation are licensed under [Apache-2.0](LICENSE). Upstream component credits and license details are in [NOTICE](NOTICE). All seven Grafana dashboards were originally authored for this thesis (no `gnetId` or `__inputs` from grafana.com); see `docs/PROVENANCE.md` for the file-by-file origin map.

## Provenance

Most manifests originated in the private GitOps infrastructure repo `ba-gitops-infra` (multi-tenant, contains unrelated cluster bootstrap). For this public artifact they were extracted, sealed-secrets and tenant-specific bootstrap files were excluded, and ArgoCD `repoURL` and `path` fields were rewritten to point at this repository. The full mapping is in [`docs/PROVENANCE.md`](docs/PROVENANCE.md).
