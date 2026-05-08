#!/bin/bash
# Validate mesh telemetry is flowing correctly before running experiments.
# Usage: ./scripts/validate-telemetry.sh <sidecar|ambient>
#
# Queries Prometheus via kubectl exec to verify Istio metrics are present
# for podinfo stable/canary services in the expected mesh mode.

set -euo pipefail

PROM_URL="http://grafana-prometheus-stack-k-prometheus.monitoring.svc.cluster.local:9090"
PROM_POD_LABEL="app.kubernetes.io/name=prometheus"
PROM_NS="monitoring"

PASS=0
FAIL=0

# --- Helpers ---

usage() {
  echo "Usage: $0 <sidecar|ambient>"
  echo ""
  echo "Validates that Istio mesh telemetry is flowing into Prometheus"
  echo "for the podinfo stable/canary services."
  echo ""
  echo "Modes:"
  echo "  sidecar  - Istio sidecar proxy mode (namespace: podinfo)"
  echo "  ambient  - Istio ambient/ztunnel mode (namespace: podinfo-ambient)"
  exit 1
}

# Execute a PromQL instant query via kubectl exec into the Prometheus pod.
# Returns the raw JSON response.
prom_query() {
  local query="$1"
  kubectl exec -n "$PROM_NS" "$(kubectl get pod -n "$PROM_NS" -l "$PROM_POD_LABEL" -o jsonpath='{.items[0].metadata.name}')" \
    -c prometheus -- \
    wget -qO- "${PROM_URL}/api/v1/query?query=$(python3 -c "import urllib.parse; print(urllib.parse.quote('''${query}'''))")" 2>/dev/null
}

# Check if a PromQL query returns any results.
# $1: description, $2: PromQL query
check() {
  local desc="$1"
  local query="$2"
  local result

  result=$(prom_query "$query") || {
    echo "  [FAIL] $desc (query execution failed)"
    FAIL=$((FAIL + 1))
    return
  }

  local status
  status=$(echo "$result" | python3 -c "import sys,json; print(json.load(sys.stdin).get('status',''))" 2>/dev/null)
  if [ "$status" != "success" ]; then
    echo "  [FAIL] $desc (Prometheus returned status: $status)"
    FAIL=$((FAIL + 1))
    return
  fi

  local count
  count=$(echo "$result" | python3 -c "import sys,json; print(len(json.load(sys.stdin)['data']['result']))" 2>/dev/null)
  if [ "$count" -gt 0 ] 2>/dev/null; then
    echo "  [PASS] $desc ($count series found)"
    PASS=$((PASS + 1))
  else
    echo "  [FAIL] $desc (0 series found)"
    FAIL=$((FAIL + 1))
  fi
}

# --- Main ---

if [ $# -ne 1 ]; then
  usage
fi

MODE="$1"
if [ "$MODE" != "sidecar" ] && [ "$MODE" != "ambient" ]; then
  echo "Error: mode must be 'sidecar' or 'ambient', got '$MODE'"
  echo ""
  usage
fi

echo "============================================="
echo " Telemetry Validation: $MODE mode"
echo "============================================="
echo ""

# --- Common checks ---

echo "[Common]"

check "Prometheus is up" \
  'up{job=~".*prometheus.*"}'

check "Alloy is scraping mesh metrics (istio_requests_total exists)" \
  'count(istio_requests_total)'

echo ""

# --- Mode-specific checks ---

if [ "$MODE" = "sidecar" ]; then
  NS="podinfo"
  STABLE_SVC="podinfo-stable.${NS}.svc.cluster.local"
  CANARY_SVC="podinfo-canary.${NS}.svc.cluster.local"

  echo "[Sidecar mode — namespace: $NS]"

  check "istio_requests_total for stable (FQDN + reporter=destination)" \
    "istio_requests_total{destination_service=\"${STABLE_SVC}\",reporter=\"destination\"}"

  check "istio_requests_total for canary (FQDN + reporter=destination)" \
    "istio_requests_total{destination_service=\"${CANARY_SVC}\",reporter=\"destination\"}"

  check "response_code label present on stable traffic" \
    "istio_requests_total{destination_service=\"${STABLE_SVC}\",reporter=\"destination\",response_code=~\".+\"}"

  check "istio_request_duration_milliseconds_bucket histogram for stable" \
    "istio_request_duration_milliseconds_bucket{destination_service=\"${STABLE_SVC}\",reporter=\"destination\"}"

  check "istio_request_duration_milliseconds_bucket histogram for canary" \
    "istio_request_duration_milliseconds_bucket{destination_service=\"${CANARY_SVC}\",reporter=\"destination\"}"

elif [ "$MODE" = "ambient" ]; then
  NS="podinfo-ambient"

  echo "[Ambient mode — namespace: $NS]"

  check "istio_requests_total for stable (service_name + namespace)" \
    "istio_requests_total{destination_service_name=\"podinfo-stable\",destination_service_namespace=\"${NS}\"}"

  check "istio_requests_total for canary (service_name + namespace)" \
    "istio_requests_total{destination_service_name=\"podinfo-canary\",destination_service_namespace=\"${NS}\"}"

  check "response_code label present on stable traffic" \
    "istio_requests_total{destination_service_name=\"podinfo-stable\",destination_service_namespace=\"${NS}\",response_code=~\".+\"}"

  check "istio_request_duration_milliseconds_bucket histogram for stable" \
    "istio_request_duration_milliseconds_bucket{destination_service_name=\"podinfo-stable\",destination_service_namespace=\"${NS}\"}"

  check "istio_request_duration_milliseconds_bucket histogram for canary" \
    "istio_request_duration_milliseconds_bucket{destination_service_name=\"podinfo-canary\",destination_service_namespace=\"${NS}\"}"
fi

echo ""
echo "============================================="
echo " Results: $PASS passed, $FAIL failed"
echo "============================================="

exit "$FAIL"
