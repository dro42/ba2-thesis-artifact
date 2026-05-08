#!/usr/bin/env bash
set -euo pipefail

# Pre-experiment verification for BA2 thesis experiments.
# Checks that all required infrastructure, monitoring, and mesh components
# are running before starting an experiment batch.
#
# Usage: ./scripts/pre-experiment-check.sh <sidecar|ambient>

PASS_ICON="\xE2\x9C\x94"
FAIL_ICON="\xE2\x9C\x98"

PASSED=0
FAILED=0

usage() {
  echo "Usage: $0 <sidecar|ambient>" >&2
  exit 1
}

if [[ $# -ne 1 ]]; then
  usage
fi

MODE="$1"

case "$MODE" in
  sidecar)  APP_NS="podinfo" ;;
  ambient)  APP_NS="podinfo-ambient" ;;
  *)        echo "Error: mode must be 'sidecar' or 'ambient'" >&2; usage ;;
esac

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

check_pass() {
  local label="$1"
  printf "  ${PASS_ICON}  %s\n" "$label"
  PASSED=$((PASSED + 1))
}

check_fail() {
  local label="$1"
  printf "  ${FAIL_ICON}  %s\n" "$label"
  FAILED=$((FAILED + 1))
}

# check_pods_running <namespace> <label_selector> <description>
check_pods_running() {
  local ns="$1" selector="$2" desc="$3"
  if kubectl get pods -n "$ns" -l "$selector" --no-headers 2>/dev/null \
      | grep -qE 'Running'; then
    check_pass "$desc"
  else
    check_fail "$desc"
  fi
}

# check_resource_exists <resource_type> <namespace> <name> <description>
check_resource_exists() {
  local kind="$1" ns="$2" name="$3" desc="$4"
  if kubectl get "$kind" -n "$ns" "$name" &>/dev/null; then
    check_pass "$desc"
  else
    check_fail "$desc"
  fi
}

# ---------------------------------------------------------------------------
# Core Infrastructure
# ---------------------------------------------------------------------------

echo ""
echo "=== Core Infrastructure ==="

check_pods_running "argocd" "app.kubernetes.io/name=argocd-server" \
  "ArgoCD server running (argocd)"

check_pods_running "argo-rollouts" "app.kubernetes.io/name=argo-rollouts" \
  "Argo Rollouts controller running (argo-rollouts)"

check_resource_exists "eventbus" "argo-events" "default" \
  "Argo Events EventBus deployed (argo-events/default)"

check_pods_running "argo-events" "sensor-name=podinfo-failover" \
  "Argo Events sensor running (argo-events, podinfo-failover)"

check_pods_running "argo-events" "eventsource-name=webhook" \
  "Argo Events eventsource running (argo-events, webhook)"

# ---------------------------------------------------------------------------
# Monitoring
# ---------------------------------------------------------------------------

echo ""
echo "=== Monitoring ==="

check_pods_running "monitoring" "app.kubernetes.io/name=prometheus" \
  "Prometheus running (monitoring)"

check_pods_running "monitoring" "app.kubernetes.io/name=grafana" \
  "Grafana running (monitoring)"

check_resource_exists "prometheusrules" "monitoring" "podinfo-stable-health" \
  "PrometheusRules loaded (monitoring/podinfo-stable-health)"

# ---------------------------------------------------------------------------
# Mesh-specific checks
# ---------------------------------------------------------------------------

echo ""
echo "=== Mesh: ${MODE} ==="

# Common: istiod
check_pods_running "istio-system" "app=istiod" \
  "istiod running (istio-system)"

if [[ "$MODE" == "sidecar" ]]; then

  # Sidecar injection: pods should have 2/2 containers (app + istio-proxy)
  sidecar_ok=true
  while IFS= read -r line; do
    ready=$(echo "$line" | awk '{print $2}')
    containers_total="${ready#*/}"
    if [[ "$containers_total" -lt 2 ]]; then
      sidecar_ok=false
      break
    fi
  done < <(kubectl get pods -n podinfo --no-headers 2>/dev/null | grep -E 'Running')

  # Also verify istio-proxy container exists (check both containers and initContainers for native sidecars in Istio 1.28+)
  proxy_found=false
  if kubectl get pods -n podinfo -o jsonpath='{.items[*].spec.containers[*].name} {.items[*].spec.initContainers[*].name}' 2>/dev/null \
      | tr ' ' '\n' | grep -q 'istio-proxy'; then
    proxy_found=true
  fi

  if [[ "$sidecar_ok" == true && "$proxy_found" == true ]]; then
    check_pass "podinfo pods have sidecars (2/2 containers, istio-proxy present)"
  else
    check_fail "podinfo pods have sidecars (2/2 containers, istio-proxy present)"
  fi

  check_resource_exists "rollout" "podinfo" "podinfo" \
    "Rollout exists (podinfo/podinfo)"

elif [[ "$MODE" == "ambient" ]]; then

  check_pods_running "istio-system" "app=ztunnel" \
    "ztunnel running (istio-system)"

  check_pods_running "podinfo-ambient" "gateway.networking.k8s.io/gateway-name" \
    "waypoint proxy running (podinfo-ambient)"

  # Ambient: pods should have 1/1 containers (no sidecar)
  no_sidecar_ok=true
  pod_count=0
  while IFS= read -r line; do
    ready=$(echo "$line" | awk '{print $2}')
    containers_total="${ready#*/}"
    ((pod_count++))
    if [[ "$containers_total" -gt 1 ]]; then
      no_sidecar_ok=false
      break
    fi
  done < <(kubectl get pods -n podinfo-ambient --no-headers 2>/dev/null | grep -E 'Running')

  if [[ "$no_sidecar_ok" == true && "$pod_count" -gt 0 ]]; then
    check_pass "podinfo-ambient pods have NO sidecars (1/1 containers)"
  else
    check_fail "podinfo-ambient pods have NO sidecars (1/1 containers)"
  fi

  check_resource_exists "rollout" "podinfo-ambient" "podinfo" \
    "Rollout exists (podinfo-ambient/podinfo)"

fi

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

TOTAL=$((PASSED + FAILED))
echo ""
echo "=== Summary ==="
echo "  Passed: ${PASSED}/${TOTAL}"
echo "  Failed: ${FAILED}/${TOTAL}"

if [[ "$FAILED" -gt 0 ]]; then
  echo ""
  echo "Some checks failed. Fix the issues above before running experiments."
  exit 1
else
  echo ""
  echo "All checks passed. Next steps:"
  echo "  1. ./scripts/validate-telemetry.sh ${MODE}"
  echo "  2. ./scripts/run-experiment-batch.sh ${MODE} 10"
  exit 0
fi
