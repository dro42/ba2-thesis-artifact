#!/usr/bin/env python3
"""
analyze-results.py — Parse experiment results and generate thesis-ready output.

Usage:
  # Single mode summary
  python3 scripts/analyze-results.py experiments/results/sidecar/YYYYMMDD-HHMMSS

  # Side-by-side comparison (sidecar vs ambient)
  python3 scripts/analyze-results.py experiments/results/sidecar/YYYYMMDD experiments/results/ambient/YYYYMMDD

Output:
  - Summary statistics (mean, median, std, min, max) for each timing delta
  - Comparison table (sidecar vs ambient)
  - Resource usage comparison
  - CSV export for further analysis
"""
import json
import sys
import csv
from pathlib import Path
from statistics import mean, median, stdev


def load_run_data(result_dir: Path) -> list[dict]:
    """Load timing data from JSON artifacts and log fallbacks."""
    runs = []

    # Try JSON artifacts first (from timing-json workflow artifact)
    for f in sorted(result_dir.glob("run-*-timing.json")):
        try:
            data = json.loads(f.read_text())
            runs.append({
                "t0": data["timing"]["t0_fault_injected"],
                "t1": data["timing"]["t1_alert_pending"],
                "t2": data["timing"]["t2_alert_firing"],
                "t5": data["timing"]["t5_collection"],
                "delta_t0_t1": data["deltas_seconds"]["t0_to_t1"],
                "delta_t0_t2": data["deltas_seconds"]["t0_to_t2"],
                "delta_t1_t2": data["deltas_seconds"]["t1_to_t2"],
                "delta_t0_t5": data["deltas_seconds"]["t0_to_t5"],
                "outcome": data.get("outcome", "unknown"),
                "error_rate": data.get("metrics_snapshot", {}).get("stable_error_rate"),
                "p99_latency": data.get("metrics_snapshot", {}).get("stable_p99_latency_ms"),
            })
            continue
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            print(f"  Warning: could not parse JSON artifact {f}: {e}", file=sys.stderr)

    # Fallback: parse from workflow JSON (contains full workflow status)
    if not runs:
        for f in sorted(result_dir.glob("run-*-workflow.json")):
            run_num = f.stem.split("-")[1]
            log_file = result_dir / f"run-{run_num}-log.txt"
            if log_file.exists():
                parsed = parse_log_timing(log_file.read_text())
                if parsed:
                    runs.append(parsed)

    # Also try log files directly if still empty
    if not runs:
        for f in sorted(result_dir.glob("run-*-log.txt")):
            parsed = parse_log_timing(f.read_text())
            if parsed:
                runs.append(parsed)

    return runs


def parse_log_timing(log_text: str) -> dict | None:
    """Parse T0-T5 timing from chaos experiment log output."""
    data = {}
    for line in log_text.splitlines():
        line = line.strip()
        if "T0 (fault injected):" in line:
            val = line.split(":")[-1].strip()
            if val.isdigit():
                data["t0"] = int(val)
        elif "T1 (alert pending):" in line:
            val = line.split(":")[-1].strip()
            data["t1"] = int(val) if val.isdigit() else None
        elif "T2 (alert firing):" in line:
            val = line.split(":")[-1].strip()
            data["t2"] = int(val) if val.isdigit() else None
        elif "T0→T1" in line and ":" in line:
            val = line.split(":")[-1].strip().rstrip("s")
            if val.lstrip("-").isdigit():
                data["delta_t0_t1"] = int(val)
        elif "T0→T2" in line and ":" in line:
            val = line.split(":")[-1].strip().rstrip("s")
            if val.lstrip("-").isdigit():
                data["delta_t0_t2"] = int(val)
        elif "T1→T2" in line and ":" in line:
            val = line.split(":")[-1].strip().rstrip("s")
            if val.lstrip("-").isdigit():
                data["delta_t1_t2"] = int(val)
        elif "T0→T5" in line and ":" in line:
            val = line.split(":")[-1].strip().rstrip("s")
            if val.lstrip("-").isdigit():
                data["delta_t0_t5"] = int(val)
        elif "RESULT: PASS" in line:
            data["outcome"] = "remediated"
        elif "RESULT: INCOMPLETE" in line:
            data["outcome"] = "incomplete"
    return data if data.get("delta_t0_t5") is not None else None


def compute_stats(values: list[int | float]) -> dict:
    """Compute summary statistics."""
    if not values:
        return {"n": 0, "mean": None, "median": None, "std": None, "min": None, "max": None}
    s = stdev(values) if len(values) > 1 else 0.0
    return {
        "n": len(values),
        "mean": round(mean(values), 1),
        "median": round(median(values), 1),
        "std": round(s, 1),
        "min": min(values),
        "max": max(values),
    }


def load_resources(result_dir: Path) -> dict:
    """Load pre/post resource snapshots."""
    resources = {}
    for label in ["pre", "post"]:
        f = result_dir / f"resources-{label}.json"
        if f.exists():
            try:
                resources[label] = json.loads(f.read_text())
            except json.JSONDecodeError:
                pass
    return resources


def print_single_summary(result_dir: Path):
    """Print summary for a single mesh mode."""
    runs = load_run_data(result_dir)
    print(f"\nLoaded {len(runs)} runs from {result_dir}")

    if not runs:
        print("  No valid timing data found.")
        return

    success = sum(1 for r in runs if r.get("outcome") in ("remediated", "true_negative"))
    false_pos = sum(1 for r in runs if r.get("outcome") == "false_positive")
    false_neg = sum(1 for r in runs if r.get("outcome") == "false_negative")
    print(f"  Successful outcomes: {success}/{len(runs)}")
    if false_pos:
        print(f"  False positives: {false_pos}")
    if false_neg:
        print(f"  False negatives: {false_neg}")
    print()

    deltas = [
        ("delta_t0_t1", "T0->T1 (detection latency)"),
        ("delta_t0_t2", "T0->T2 (alert firing)"),
        ("delta_t1_t2", "T1->T2 (for-clause wait)"),
        ("delta_t0_t5", "T0->T5 (total remediation)"),
    ]

    for key, label in deltas:
        vals = [r[key] for r in runs if r.get(key) is not None]
        stats = compute_stats(vals)
        if stats["mean"] is not None:
            print(f"  {label}:")
            print(f"    mean={stats['mean']}s  median={stats['median']}s  std={stats['std']}s  range=[{stats['min']}, {stats['max']}]  n={stats['n']}")


def print_comparison(sidecar_dir: Path, ambient_dir: Path):
    """Print side-by-side comparison table for thesis."""
    sidecar_runs = load_run_data(sidecar_dir)
    ambient_runs = load_run_data(ambient_dir)

    print()
    print("=" * 78)
    print("  THESIS EXPERIMENT RESULTS — Sidecar vs Ambient Comparison")
    print("=" * 78)

    s_success = sum(1 for r in sidecar_runs if r.get("outcome") in ("remediated", "true_negative"))
    a_success = sum(1 for r in ambient_runs if r.get("outcome") in ("remediated", "true_negative"))
    print(f"\n  Sidecar: {len(sidecar_runs)} runs ({s_success} successful)")
    print(f"  Ambient: {len(ambient_runs)} runs ({a_success} successful)")

    deltas = [
        ("delta_t0_t1", "T0->T1 (detection)"),
        ("delta_t0_t2", "T0->T2 (alert firing)"),
        ("delta_t1_t2", "T1->T2 (for-clause)"),
        ("delta_t0_t5", "T0->T5 (total remed.)"),
    ]

    print()
    print(f"  {'Metric':<24} {'Stat':>4}  {'Sidecar':>12}  {'Ambient':>12}")
    print("  " + "-" * 56)

    for key, label in deltas:
        s_vals = [r[key] for r in sidecar_runs if r.get(key) is not None]
        a_vals = [r[key] for r in ambient_runs if r.get(key) is not None]
        s = compute_stats(s_vals)
        a = compute_stats(a_vals)

        if s["mean"] is None and a["mean"] is None:
            continue

        s_mean = f"{s['mean']:.1f}s" if s["mean"] is not None else "N/A"
        a_mean = f"{a['mean']:.1f}s" if a["mean"] is not None else "N/A"
        s_med = f"{s['median']:.1f}s" if s["median"] is not None else "N/A"
        a_med = f"{a['median']:.1f}s" if a["median"] is not None else "N/A"
        s_std = f"{s['std']:.1f}s" if s["std"] is not None else "N/A"
        a_std = f"{a['std']:.1f}s" if a["std"] is not None else "N/A"
        s_range = f"{s['min']}-{s['max']}s" if s["min"] is not None else "N/A"
        a_range = f"{a['min']}-{a['max']}s" if a["min"] is not None else "N/A"

        print(f"  {label:<24} {'n':>4}  {s.get('n', 0):>12}  {a.get('n', 0):>12}")
        print(f"  {'':24} {'mean':>4}  {s_mean:>12}  {a_mean:>12}")
        print(f"  {'':24} {'med':>4}  {s_med:>12}  {a_med:>12}")
        print(f"  {'':24} {'std':>4}  {s_std:>12}  {a_std:>12}")
        print(f"  {'':24} {'rng':>4}  {s_range:>12}  {a_range:>12}")
        print()

    # Resource comparison
    s_res = load_resources(sidecar_dir)
    a_res = load_resources(ambient_dir)
    if s_res.get("pre") or a_res.get("pre"):
        print("  Resource Usage (pre-experiment baseline):")
        print("  " + "-" * 56)
        for mode_label, res in [("Sidecar", s_res), ("Ambient", a_res)]:
            pre = res.get("pre", {})
            pods = pre.get("istio_system", [])
            if pods:
                print(f"\n  {mode_label} — istio-system:")
                for p in pods:
                    print(f"    {p.get('pod', '?'):<36} {p.get('cpu_millicores', '?'):>8}  {p.get('memory_mib', '?'):>8}")
            app_pods = pre.get("app_pods", [])
            if app_pods:
                ns = pre.get("app_namespace", "?")
                print(f"  {mode_label} — {ns}:")
                for p in app_pods:
                    print(f"    {p.get('pod', '?'):<36} {p.get('cpu_millicores', '?'):>8}  {p.get('memory_mib', '?'):>8}")

    # Export CSV
    csv_path = sidecar_dir.parent / "comparison.csv"
    export_csv(csv_path, sidecar_runs, ambient_runs)
    print(f"\n  CSV exported to: {csv_path}")
    print()


def export_csv(csv_path: Path, sidecar_runs: list[dict], ambient_runs: list[dict]):
    """Export all run data to CSV."""
    with open(csv_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "mesh_mode", "run", "outcome",
            "delta_t0_t1", "delta_t0_t2", "delta_t1_t2", "delta_t0_t5",
        ])
        for i, r in enumerate(sidecar_runs, 1):
            writer.writerow([
                "sidecar", i, r.get("outcome", ""),
                r.get("delta_t0_t1"), r.get("delta_t0_t2"),
                r.get("delta_t1_t2"), r.get("delta_t0_t5"),
            ])
        for i, r in enumerate(ambient_runs, 1):
            writer.writerow([
                "ambient", i, r.get("outcome", ""),
                r.get("delta_t0_t1"), r.get("delta_t0_t2"),
                r.get("delta_t1_t2"), r.get("delta_t0_t5"),
            ])


def main():
    if len(sys.argv) < 2:
        print("Usage:")
        print("  analyze-results.py <result-dir>                    # Single mode summary")
        print("  analyze-results.py <sidecar-dir> <ambient-dir>     # Comparison")
        sys.exit(1)

    if len(sys.argv) >= 3:
        print_comparison(Path(sys.argv[1]), Path(sys.argv[2]))
    else:
        print_single_summary(Path(sys.argv[1]))


if __name__ == "__main__":
    main()
