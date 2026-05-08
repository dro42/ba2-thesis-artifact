# BA2 Experiment Mode Switching

This tree adds a Git-controlled Argo CD root called `ba2-experiment` for switching safely between:

- `none`
- `istio-sidecar`
- `istio-ambient`

## Structure

- `modes/none`: empty safe mode that prunes experiment apps and runs cleanup checks
- `modes/istio-sidecar`: deploys BA2-specific Istio sidecar component apps and the Rollouts-based podinfo app
- `modes/istio-ambient`: deploys BA2-specific Istio ambient component apps and the Rollouts-based podinfo app
- `mesh/*`: BA2-specific app-of-apps trees for mesh components; these are separate from the existing manual `service-mesh-*` apps

## Why BA2-Specific Mesh Trees

The BA2 experiment uses a parallel ArgoCD application tree separate from any production-mesh masters and keeps the podinfo Rollouts applications on manual sync. The design rationale (why ArgoCD cannot make a parent app wait on nested children, and why auto-sync would fight live rollout mutations) is in thesis §3.4 (GitOps Workflow and Mode Switching). The structural details below are the operational consequence.

## Switching Flow

1. Ensure `argo-rollouts` is already Healthy.
2. Commit `manifests/argocd/ba2-experiment.application.yaml` with `spec.source.path` set to `manifests/experiments/modes/none`.
3. Wait for Argo CD to pick up the Application spec change, then sync:

   ```bash
   argocd app sync ba2-experiment
   argocd app wait ba2-experiment --health --sync
   ```

4. Commit `manifests/argocd/ba2-experiment.application.yaml` again with the target path:

   - `manifests/experiments/modes/istio-sidecar`
   - `manifests/experiments/modes/istio-ambient`

5. Sync `ba2-experiment` again and wait for health.

## Safety Guards

- Active modes run a `PreSync` hook that fails if `rollouts.argoproj.io` is missing or the Argo Rollouts controller is not Available.
- `none` runs a `PostSync` cleanup check that verifies the BA2 mesh apps, BA2 podinfo apps, experiment namespaces, Istio workloads, and Istio admission webhooks are gone before the next mode is activated.
- `podinfo-traffic-test-*` applications remain outside this switch path and must be run manually after the target mode is Healthy.
