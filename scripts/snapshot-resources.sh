#!/usr/bin/env bash
set -euo pipefail

usage() {
  echo "Usage: $0 <sidecar|ambient> <label>" >&2
  exit 1
}

if [[ $# -ne 2 ]]; then
  usage
fi

MESH_MODE="$1"
LABEL="$2"

case "$MESH_MODE" in
  sidecar) APP_NS="podinfo" ;;
  ambient) APP_NS="podinfo-ambient" ;;
  *) echo "Error: mesh_mode must be 'sidecar' or 'ambient'" >&2; usage ;;
esac

TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

# Collect pod metrics from istio-system
istio_pods=$(kubectl top pods -n istio-system --no-headers 2>/dev/null | awk '{printf "{\"name\":\"%s\",\"namespace\":\"istio-system\",\"cpu\":\"%s\",\"memory\":\"%s\"}", $1, $2, $3; if(NR>0) printf ","}' | sed 's/,$//')

# Collect pod metrics from the app namespace
app_pods=$(kubectl top pods -n "$APP_NS" --no-headers 2>/dev/null | awk '{printf "{\"name\":\"%s\",\"namespace\":\"'"$APP_NS"'\",\"cpu\":\"%s\",\"memory\":\"%s\"}", $1, $2, $3; if(NR>0) printf ","}' | sed 's/,$//')

# Combine pod arrays
if [[ -n "$istio_pods" && -n "$app_pods" ]]; then
  all_pods="${istio_pods},${app_pods}"
elif [[ -n "$istio_pods" ]]; then
  all_pods="$istio_pods"
elif [[ -n "$app_pods" ]]; then
  all_pods="$app_pods"
else
  all_pods=""
fi

# Collect node metrics
nodes=$(kubectl top nodes --no-headers 2>/dev/null | awk '{printf "{\"name\":\"%s\",\"cpu\":\"%s\",\"cpu_percent\":\"%s\",\"memory\":\"%s\",\"memory_percent\":\"%s\"}", $1, $2, $3, $4, $5; if(NR>0) printf ","}' | sed 's/,$//')

# Output JSON
cat <<EOF
{
  "timestamp": "${TIMESTAMP}",
  "mesh_mode": "${MESH_MODE}",
  "label": "${LABEL}",
  "pods": [${all_pods}],
  "nodes": [${nodes}]
}
EOF
