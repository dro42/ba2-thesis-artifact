#!/usr/bin/env bash
# run-experiment-batch.sh — Run N experiment iterations and collect results
# Usage: ./scripts/run-experiment-batch.sh <mesh-mode> <num-runs> [fault-pct] [traffic-dur]
#
# Example:
#   ./scripts/run-experiment-batch.sh sidecar 10
#   ./scripts/run-experiment-batch.sh ambient 10 80 200
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

MESH_MODE="${1:?Usage: run-experiment-batch.sh <sidecar|ambient> <num-runs> [fault-pct] [traffic-dur] [outdir]}"
NUM_RUNS="${2:?Specify number of runs}"
FAULT_PCT="${3:-60}"
TRAFFIC_DUR="${4:-150}"
BATCH_TS="$(date -u '+%Y%m%d-%H%M%S')"
OUTDIR="${5:-$REPO_DIR/experiments/results/${MESH_MODE}/${BATCH_TS}}"

mkdir -p "$OUTDIR"

echo "============================================================"
echo "  Batch Experiment: $MESH_MODE"
echo "  Runs:   $NUM_RUNS"
echo "  Fault:  ${FAULT_PCT}%"
echo "  Traffic: ${TRAFFIC_DUR}s"
echo "  Output: $OUTDIR"
echo "============================================================"
echo ""

# Pre-experiment resource snapshot
if [ -x "$SCRIPT_DIR/snapshot-resources.sh" ]; then
  "$SCRIPT_DIR/snapshot-resources.sh" "$MESH_MODE" "pre-experiment" > "$OUTDIR/resources-pre.json" 2>/dev/null || true
  echo "[pre] Resource snapshot saved"
else
  echo "[pre] snapshot-resources.sh not found, skipping"
fi

SUCCESSES=0
FAILURES=0

for i in $(seq 1 "$NUM_RUNS"); do
  echo ""
  echo "=== Run $i/$NUM_RUNS ==="

  # Submit experiment and capture workflow name
  WF_NAME=$(argo submit --from workflowtemplate/chaos-experiment -n argo-events \
    -p mesh-mode="$MESH_MODE" \
    -p fault-percentage="$FAULT_PCT" \
    -p traffic-duration="$TRAFFIC_DUR" \
    --output name 2>&1) || {
    echo "  ERROR: Failed to submit workflow"
    FAILURES=$((FAILURES + 1))
    continue
  }

  echo "  Workflow: $WF_NAME"

  # Wait for workflow completion (max 15 min)
  # Argo CLI v4 does not support --timeout on 'argo wait', so poll manually
  DEADLINE=$((SECONDS + 900))
  WF_DONE=false
  while [ $SECONDS -lt $DEADLINE ]; do
    PHASE=$(argo get -n argo-events "$WF_NAME" -o json 2>/dev/null \
      | python3 -c "import sys,json; print(json.load(sys.stdin).get('status',{}).get('phase',''))" 2>/dev/null || echo "")
    if [ "$PHASE" = "Succeeded" ] || [ "$PHASE" = "Failed" ] || [ "$PHASE" = "Error" ]; then
      WF_DONE=true
      echo "  Workflow finished: $PHASE"
      break
    fi
    sleep 15
  done
  if [ "$WF_DONE" = false ]; then
    echo "  WARNING: Workflow did not complete within 15 minutes"
  fi

  # Save full workflow JSON
  argo get -n argo-events "$WF_NAME" -o json > "$OUTDIR/run-${i}-workflow.json" 2>/dev/null || true

  # Save full logs FIRST — single argo logs call, no truncation.
  # Try node-filtered logs (smaller/faster), fall back to full workflow logs.
  argo logs -n argo-events "$WF_NAME" --node-field templateName=collect-timing-report \
    > "$OUTDIR/run-${i}-log.txt" 2>/dev/null || \
    argo logs -n argo-events "$WF_NAME" \
    > "$OUTDIR/run-${i}-log.txt" 2>/dev/null || true

  # Extract timing JSON — 4-tier fallback
  TIMING_EXTRACTED=false

  # Tier 1: argo cp artifact (most reliable when artifact storage is configured)
  ARTIFACT_TMP=$(mktemp -d)
  if argo cp -n argo-events "$WF_NAME" "$ARTIFACT_TMP" --artifact-name=timing-json 2>/dev/null; then
    TIMING_FILE=$(find "$ARTIFACT_TMP" -name "timing.json" -type f 2>/dev/null | head -1)
    if [ -n "$TIMING_FILE" ] && python3 -c "import json; json.load(open('$TIMING_FILE'))" 2>/dev/null; then
      cp "$TIMING_FILE" "$OUTDIR/run-${i}-timing.json"
      echo "  Timing artifact extracted via argo cp"
      TIMING_EXTRACTED=true
    fi
  fi
  rm -rf "$ARTIFACT_TMP"

  # Tier 2: inline artifact from workflow JSON
  if [ "$TIMING_EXTRACTED" = false ]; then
    python3 -c "
import sys, json
wf = json.load(open('$OUTDIR/run-${i}-workflow.json'))
for nid, node in wf.get('status',{}).get('nodes',{}).items():
    if node.get('templateName') == 'collect-timing-report':
        for a in node.get('outputs',{}).get('artifacts',[]):
            if a.get('name') == 'timing-json' and 'raw' in a:
                data = a['raw'].get('data','')
                if data:
                    import base64
                    decoded = base64.b64decode(data).decode()
                    parsed = json.loads(decoded)
                    json.dump(parsed, open('$OUTDIR/run-${i}-timing.json','w'), indent=2)
                    print('  Timing extracted from inline artifact')
                    sys.exit(0)
" 2>/dev/null && TIMING_EXTRACTED=true || true
  fi

  # Tier 3: extract JSON between delimiters from saved logs
  if [ "$TIMING_EXTRACTED" = false ] && [ -f "$OUTDIR/run-${i}-log.txt" ]; then
    python3 -c "
import json, re
with open('$OUTDIR/run-${i}-log.txt') as f:
    log = f.read()
log = re.sub(r'\x1b\[[0-9;]*m', '', log)
log = re.sub(r'^[a-z0-9-]+: ', '', log, flags=re.MULTILINE)
match = re.search(r'---TIMING-JSON-START---\s*(.*?)\s*---TIMING-JSON-END---', log, re.DOTALL)
if match:
    parsed = json.loads(match.group(1))
    json.dump(parsed, open('$OUTDIR/run-${i}-timing.json','w'), indent=2)
    print('  Timing extracted from saved logs')
    exit(0)
exit(1)
" 2>/dev/null && TIMING_EXTRACTED=true || true
  fi

  # Tier 4: parse human-readable timing lines from saved logs
  if [ "$TIMING_EXTRACTED" = false ] && [ -f "$OUTDIR/run-${i}-log.txt" ]; then
    python3 -c "
import json, re
with open('$OUTDIR/run-${i}-log.txt') as f:
    log = f.read()
log = re.sub(r'\x1b\[[0-9;]*m', '', log)
log = re.sub(r'^[a-z0-9-]+: ', '', log, flags=re.MULTILINE)
def extract(pattern):
    m = re.search(pattern, log)
    return int(m.group(1)) if m else None
t0 = extract(r'T0 \(fault injected\):\s+(\d+)')
t1 = extract(r'T1 \(alert pending\):\s+(\d+)')
t2 = extract(r'T2 \(alert firing\):\s+(\d+)')
t5 = extract(r'T5 \(collection time\):\s+(\d+)')
t4_match = re.search(r'T4 \(failover workflow\):\s+(.*)', log)
t4 = t4_match.group(1).strip() if t4_match else None
outcome = 'unknown'
if 'RESULT: PASS' in log:
    outcome = 'true_negative' if 'true negative' in log.lower() else 'remediated'
elif 'RESULT: FAIL' in log:
    outcome = 'false_positive' if 'false positive' in log.lower() else 'false_negative'
err_match = re.search(r'Stable error rate.*?:\s+([\d.]+)', log)
lat_match = re.search(r'Stable p99 latency.*?:\s+([\d.]+)', log)
if t0 and t5:
    timing = {
        'experiment_id': 'parsed-from-log',
        'timestamp': '$(date -u +%Y-%m-%dT%H:%M:%SZ)',
        'mesh_mode': '$MESH_MODE',
        'fault_percentage': $FAULT_PCT,
        'traffic_duration_s': $TRAFFIC_DUR,
        'timing': {
            't0_fault_injected': t0, 't1_alert_pending': t1,
            't2_alert_firing': t2, 't4_failover_workflow': t4,
            't5_collection': t5
        },
        'deltas_seconds': {
            't0_to_t1': (t1 - t0) if t1 else None,
            't1_to_t2': (t2 - t1) if (t1 and t2) else None,
            't0_to_t2': (t2 - t0) if t2 else None,
            't0_to_t5': t5 - t0
        },
        'metrics_snapshot': {
            'stable_error_rate': err_match.group(1) if err_match else None,
            'stable_p99_latency_ms': lat_match.group(1) if lat_match else None
        },
        'rollout': {'phase': 'unknown', 'message': 'parsed from log'},
        'outcome': outcome
    }
    json.dump(timing, open('$OUTDIR/run-${i}-timing.json', 'w'), indent=2)
    print('  Timing extracted from human-readable log')
    exit(0)
exit(1)
" 2>/dev/null && TIMING_EXTRACTED=true || true
  fi

  # Determine outcome — 3-tier fallback
  OUTCOME="UNKNOWN"

  # Tier 1: timing JSON (most reliable if extracted)
  if [ -f "$OUTDIR/run-${i}-timing.json" ]; then
    OUTCOME=$(python3 -c "
import json
d = json.load(open('$OUTDIR/run-${i}-timing.json'))
print(d.get('outcome', 'unknown'))
" 2>/dev/null || echo "UNKNOWN")
  fi

  # Tier 2: workflow JSON phase (works even if timing extraction failed)
  # Note: cannot distinguish baseline (true_negative) from fault (remediated)
  # because workflow phase alone doesn't encode fault-percentage. Tier 1 handles this.
  if [ "$OUTCOME" = "UNKNOWN" ] || [ "$OUTCOME" = "unknown" ]; then
    if [ -f "$OUTDIR/run-${i}-workflow.json" ]; then
      OUTCOME=$(python3 -c "
import json
d = json.load(open('$OUTDIR/run-${i}-workflow.json'))
phase = d.get('status', {}).get('phase', '')
if phase == 'Succeeded':
    print('remediated')
elif phase == 'Failed':
    print('failed')
else:
    print('unknown')
" 2>/dev/null || echo "UNKNOWN")
    fi
  fi

  # Tier 3: log grep with ANSI stripping
  if [ "$OUTCOME" = "UNKNOWN" ] || [ "$OUTCOME" = "unknown" ]; then
    if [ -f "$OUTDIR/run-${i}-log.txt" ]; then
      CLEANED=$(sed 's/\x1b\[[0-9;]*m//g' "$OUTDIR/run-${i}-log.txt" 2>/dev/null)
      if echo "$CLEANED" | grep -q "RESULT: PASS"; then
        OUTCOME="remediated"
      elif echo "$CLEANED" | grep -q "RESULT: FAIL"; then
        OUTCOME="failed"
      fi
    fi
  fi

  # Classify
  case "$OUTCOME" in
    remediated|true_negative)
      SUCCESSES=$((SUCCESSES + 1))
      echo "  Result: PASS ($OUTCOME)"
      ;;
    false_positive|false_negative)
      SUCCESSES=$((SUCCESSES + 1))
      echo "  Result: DATA COLLECTED ($OUTCOME)"
      ;;
    *)
      FAILURES=$((FAILURES + 1))
      echo "  Result: ${OUTCOME:-UNKNOWN}"
      ;;
  esac

  # Cooldown between runs (let metrics and alerts settle)
  if [ "$i" -lt "$NUM_RUNS" ]; then
    echo "  Cooling down 120s before next run..."
    sleep 120
  fi
done

echo ""

# Post-experiment resource snapshot
if [ -x "$SCRIPT_DIR/snapshot-resources.sh" ]; then
  "$SCRIPT_DIR/snapshot-resources.sh" "$MESH_MODE" "post-experiment" > "$OUTDIR/resources-post.json" 2>/dev/null || true
  echo "[post] Resource snapshot saved"
fi

# Write batch metadata
cat > "$OUTDIR/batch-meta.json" <<EOF
{
  "mesh_mode": "$MESH_MODE",
  "num_runs": $NUM_RUNS,
  "successes": $SUCCESSES,
  "failures": $FAILURES,
  "fault_percentage": $FAULT_PCT,
  "traffic_duration_s": $TRAFFIC_DUR,
  "started": "$BATCH_TS",
  "completed": "$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
}
EOF

echo ""
echo "============================================================"
echo "  Batch Complete"
echo "  Successes: $SUCCESSES / $NUM_RUNS"
echo "  Failures:  $FAILURES / $NUM_RUNS"
echo "  Results:   $OUTDIR"
echo "============================================================"
echo ""
echo "Next: python3 scripts/analyze-results.py $OUTDIR"
