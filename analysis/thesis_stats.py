#!/usr/bin/env python3
"""
thesis_stats.py — Statistical analysis and visualization for BA2 thesis experiments.

Compares Istio sidecar vs ambient mesh canary deployment timing, reliability,
and metric completeness. Generates publication-ready plots and LaTeX tables.

Usage:
  python3 thesis_stats.py all <sidecar-dir> <ambient-dir> [--output-dir DIR] [--latex-dir DIR]
  python3 thesis_stats.py latency <sidecar-dir> <ambient-dir> [--output FILE] [--latex FILE]
  python3 thesis_stats.py reliability <sidecar-dir> <ambient-dir> [--output FILE] [--latex FILE]
  python3 thesis_stats.py completeness <sidecar-dir> <ambient-dir> [--output FILE] [--latex FILE]
  python3 thesis_stats.py resources <sidecar-dir> <ambient-dir> [--output FILE]
  python3 thesis_stats.py summary <sidecar-dir> <ambient-dir>  # Console-only overview

Dependencies: numpy, scipy, matplotlib, seaborn, pandas
  pip install numpy scipy matplotlib seaborn pandas
"""

import argparse
import json
import locale
import sys
from pathlib import Path
from typing import Optional

import matplotlib
matplotlib.use("Agg")  # Non-interactive backend
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
import numpy as np
import pandas as pd
import seaborn as sns
from scipy import stats as sp_stats

# Austrian/German number notation: comma decimal, dot thousands. Applied to
# matplotlib axes via axes.formatter.use_locale; in-figure text annotations
# must call _de() explicitly because f-strings bypass the axis formatter.
for _loc in ("de_AT.UTF-8", "de_DE.UTF-8", "de_AT", "de_DE"):
    try:
        locale.setlocale(locale.LC_NUMERIC, _loc)
        break
    except locale.Error:
        continue


def _de(val: float, decimals: int = 1) -> str:
    """Format a number with comma decimal and dot thousands separator."""
    return locale.format_string(f"%.{decimals}f", val, grouping=True)


def _de_percent_formatter(decimals: int = 0):
    """matplotlib FuncFormatter rendering '<de-formatted value> %'."""
    return ticker.FuncFormatter(lambda v, _: f"{_de(v, decimals)} %")


# ---------------------------------------------------------------------------
# Publication style
# ---------------------------------------------------------------------------

def setup_plot_style():
    """Configure matplotlib for thesis-quality figures."""
    plt.rcParams.update({
        "font.family": "serif",
        "font.size": 9,
        "axes.labelsize": 10,
        "axes.titlesize": 10,
        "xtick.labelsize": 8,
        "ytick.labelsize": 8,
        "legend.fontsize": 8,
        "figure.dpi": 300,
        "savefig.dpi": 300,
        "savefig.bbox": "tight",
        "savefig.pad_inches": 0.05,
        "axes.grid": True,
        "grid.alpha": 0.3,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.formatter.use_locale": True,
    })
    sns.set_palette("colorblind")


# ---------------------------------------------------------------------------
# Data loading (mirrors analyze-results.py logic)
# ---------------------------------------------------------------------------

def load_run_data(result_dir: Path) -> list[dict]:
    """Load timing data from a batch results directory."""
    runs = []

    # Try structured JSON artifacts first
    for f in sorted(result_dir.glob("run-*-timing.json")):
        try:
            data = json.loads(f.read_text())
            run = {
                "source": str(f),
                "mesh_mode": data.get("mesh_mode", result_dir.parent.name),
                "outcome": data.get("outcome", "unknown"),
            }
            # Timing deltas
            deltas = data.get("deltas_seconds", {})
            run["delta_t0_t1"] = deltas.get("t0_to_t1")
            run["delta_t0_t2"] = deltas.get("t0_to_t2")
            run["delta_t1_t2"] = deltas.get("t1_to_t2")
            run["delta_t0_t5"] = deltas.get("t0_to_t5")

            # Raw timestamps (for completeness checks)
            timing = data.get("timing", {})
            run["t0"] = timing.get("t0_fault_injected")
            run["t1"] = timing.get("t1_alert_pending")
            run["t2"] = timing.get("t2_alert_firing")
            run["t4"] = timing.get("t4_failover_workflow") or timing.get("t4_failover_epoch")
            run["t5"] = timing.get("t5_collection")

            # Metric snapshots
            snap = data.get("metrics_snapshot", {})
            run["stable_error_rate"] = snap.get("stable_error_rate")
            run["stable_p99_latency_ms"] = snap.get("stable_p99_latency_ms")
            run["canary_error_rate"] = snap.get("canary_error_rate")
            run["canary_p99_latency_ms"] = snap.get("canary_p99_latency_ms")

            runs.append(run)
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            print(f"  Warning: could not parse {f}: {e}", file=sys.stderr)

    # Fallback: parse log files
    if not runs:
        for f in sorted(result_dir.glob("run-*-log.txt")):
            parsed = _parse_log_timing(f.read_text())
            if parsed:
                parsed["source"] = str(f)
                parsed["mesh_mode"] = result_dir.parent.name
                runs.append(parsed)

    return runs


def _parse_log_timing(log_text: str) -> Optional[dict]:
    """Parse T0-T5 timing from chaos experiment log output."""
    data: dict = {}
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


def runs_to_dataframe(sidecar_runs: list[dict], ambient_runs: list[dict]) -> pd.DataFrame:
    """Convert run lists to a single DataFrame with a 'mode' column."""
    rows = []
    for i, r in enumerate(sidecar_runs, 1):
        row = {**r, "mode": "sidecar", "run_num": i}
        rows.append(row)
    for i, r in enumerate(ambient_runs, 1):
        row = {**r, "mode": "ambient", "run_num": i}
        rows.append(row)
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Statistical helpers
# ---------------------------------------------------------------------------

def clopper_pearson_ci(successes: int, total: int, alpha: float = 0.05) -> tuple[float, float]:
    """Exact binomial (Clopper-Pearson) confidence interval."""
    if total == 0:
        return (0.0, 1.0)
    lo = sp_stats.beta.ppf(alpha / 2, successes, total - successes + 1) if successes > 0 else 0.0
    hi = sp_stats.beta.ppf(1 - alpha / 2, successes + 1, total - successes) if successes < total else 1.0
    return (lo, hi)


def mann_whitney_test(a: list[float], b: list[float]) -> dict:
    """Run Mann-Whitney U test with rank-biserial effect size."""
    a_arr, b_arr = np.array(a), np.array(b)
    if len(a_arr) < 2 or len(b_arr) < 2:
        return {"U": None, "p": None, "r": None, "interpretation": "insufficient data"}

    result = sp_stats.mannwhitneyu(a_arr, b_arr, alternative="two-sided")
    n1, n2 = len(a_arr), len(b_arr)
    # Rank-biserial correlation: r = 1 - (2U)/(n1*n2)
    r = 1 - (2 * result.statistic) / (n1 * n2)

    # Interpret
    p = result.pvalue
    if p < 0.001:
        sig = "***"
    elif p < 0.01:
        sig = "**"
    elif p < 0.05:
        sig = "*"
    else:
        sig = "ns"

    r_abs = abs(r)
    if r_abs < 0.3:
        effect = "small"
    elif r_abs < 0.5:
        effect = "medium"
    else:
        effect = "large"

    return {
        "U": result.statistic,
        "p": p,
        "sig": sig,
        "r": r,
        "effect_size": effect,
        "n1": n1,
        "n2": n2,
        "interpretation": f"U={result.statistic:.1f}, p={p:.4f} {sig}, r={r:.3f} ({effect} effect)",
    }


def bootstrap_median_diff(a: list[float], b: list[float], n_boot: int = 10000,
                           alpha: float = 0.05, seed: int = 42) -> dict:
    """Bootstrap 95% CI for median(a) - median(b)."""
    rng = np.random.default_rng(seed)
    a_arr, b_arr = np.array(a), np.array(b)
    if len(a_arr) < 2 or len(b_arr) < 2:
        return {"median_diff": None, "ci_lo": None, "ci_hi": None}

    diffs = np.empty(n_boot)
    for i in range(n_boot):
        a_sample = rng.choice(a_arr, size=len(a_arr), replace=True)
        b_sample = rng.choice(b_arr, size=len(b_arr), replace=True)
        diffs[i] = np.median(a_sample) - np.median(b_sample)

    ci_lo = float(np.percentile(diffs, 100 * alpha / 2))
    ci_hi = float(np.percentile(diffs, 100 * (1 - alpha / 2)))
    observed = float(np.median(a_arr) - np.median(b_arr))
    return {"median_diff": observed, "ci_lo": ci_lo, "ci_hi": ci_hi}


def descriptive_stats(values: list[float]) -> dict:
    """Compute descriptive statistics for a list of values."""
    if not values:
        return {"n": 0, "mean": None, "median": None, "std": None, "iqr": None,
                "min": None, "max": None, "q1": None, "q3": None}
    arr = np.array(values)
    q1, q3 = float(np.percentile(arr, 25)), float(np.percentile(arr, 75))
    return {
        "n": len(values),
        "mean": float(np.mean(arr)),
        "median": float(np.median(arr)),
        "std": float(np.std(arr, ddof=1)) if len(values) > 1 else 0.0,
        "iqr": q3 - q1,
        "min": float(np.min(arr)),
        "max": float(np.max(arr)),
        "q1": q1,
        "q3": q3,
    }


# ---------------------------------------------------------------------------
# RQ1: Reliability
# ---------------------------------------------------------------------------

def analyze_reliability(df: pd.DataFrame, output_path: Optional[str] = None,
                        latex_path: Optional[str] = None):
    """Analyze remediation success rates and false positive/negative rates."""
    print("\n" + "=" * 70)
    print("  RQ1: Remediation Reliability")
    print("=" * 70)

    results = {}
    for mode in ["sidecar", "ambient"]:
        subset = df[df["mode"] == mode]
        n = len(subset)
        success = subset["outcome"].isin(["remediated", "true_negative"]).sum()
        failure = n - success
        rate = success / n if n > 0 else 0
        ci_lo, ci_hi = clopper_pearson_ci(success, n)

        # False negative: fault injected but not detected (outcome != remediated)
        fn_rate = failure / n if n > 0 else 0
        fn_ci = clopper_pearson_ci(failure, n)

        results[mode] = {
            "n": n, "success": int(success), "failure": int(failure),
            "success_rate": rate,
            "ci_lo": ci_lo, "ci_hi": ci_hi,
            "fn_rate": fn_rate, "fn_ci_lo": fn_ci[0], "fn_ci_hi": fn_ci[1],
        }

        print(f"\n  {mode.capitalize()}:")
        print(f"    Runs:         {n}")
        print(f"    Remediated:   {success}/{n} ({rate*100:.1f}%)")
        print(f"    Success rate: {rate*100:.1f}% [{ci_lo*100:.1f}%, {ci_hi*100:.1f}%]")
        print(f"    FN rate:      {fn_rate*100:.1f}% [{fn_ci[0]*100:.1f}%, {fn_ci[1]*100:.1f}%]")

    # Fisher's exact test comparing success rates
    s = results["sidecar"]
    a = results["ambient"]
    if s["n"] > 0 and a["n"] > 0:
        table = [[s["success"], s["failure"]], [a["success"], a["failure"]]]
        _, fisher_p = sp_stats.fisher_exact(table)
        sig = "***" if fisher_p < 0.001 else "**" if fisher_p < 0.01 else "*" if fisher_p < 0.05 else "ns"
        print(f"\n  Fisher's exact test: p={fisher_p:.4f} {sig}")
        if fisher_p >= 0.05:
            print("  -> No statistically significant difference in success rates.")
        else:
            print("  -> Statistically significant difference in success rates.")

    # Plot
    if output_path:
        setup_plot_style()
        fig, ax = plt.subplots(figsize=(3.5, 2.8))
        modes = ["Sidecar", "Ambient"]
        rates = [results["sidecar"]["success_rate"] * 100, results["ambient"]["success_rate"] * 100]
        ci_lo = [results["sidecar"]["ci_lo"] * 100, results["ambient"]["ci_lo"] * 100]
        ci_hi = [results["sidecar"]["ci_hi"] * 100, results["ambient"]["ci_hi"] * 100]
        yerr_lo = [r - lo for r, lo in zip(rates, ci_lo)]
        yerr_hi = [hi - r for r, hi in zip(rates, ci_hi)]

        colors = sns.color_palette("colorblind", 2)
        bars = ax.bar(modes, rates, color=colors, width=0.5, edgecolor="black", linewidth=0.5)
        ax.errorbar(modes, rates, yerr=[yerr_lo, yerr_hi], fmt="none", ecolor="black",
                     capsize=5, capthick=1, linewidth=1)
        ax.set_ylabel("Success Rate (%)")
        ax.set_ylim(0, 110)
        ax.yaxis.set_major_formatter(_de_percent_formatter(0))

        for bar, rate in zip(bars, rates):
            ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 3,
                    f"{_de(rate)} %", ha="center", va="bottom", fontsize=8)

        plt.tight_layout()
        plt.savefig(output_path)
        plt.close()
        print(f"\n  Plot saved: {output_path}")

    # LaTeX table
    if latex_path:
        _write_reliability_latex(results, fisher_p if s["n"] > 0 and a["n"] > 0 else None, latex_path)
        print(f"  LaTeX saved: {latex_path}")

    return results


def _write_reliability_latex(results: dict, fisher_p: Optional[float], path: str):
    """Write RQ1 reliability LaTeX table."""
    lines = [
        r"\begin{table}[htbp]",
        r"  \centering",
        r"  \caption{Remediation reliability comparison (Clopper-Pearson 95\% CI).}",
        r"  \label{tab:rq1-reliability}",
        r"  \begin{tabular}{lcccc}",
        r"    \toprule",
        r"    Mode & Runs & Success Rate & 95\% CI & FN Rate \\",
        r"    \midrule",
    ]
    for mode in ["sidecar", "ambient"]:
        r = results[mode]
        lines.append(
            f"    {mode.capitalize()} & {r['n']} & {r['success_rate']*100:.1f}\\% "
            f"& [{r['ci_lo']*100:.1f}\\%, {r['ci_hi']*100:.1f}\\%] "
            f"& {r['fn_rate']*100:.1f}\\% \\\\"
        )
    lines.append(r"    \bottomrule")
    lines.append(r"  \end{tabular}")
    if fisher_p is not None:
        sig = "p < 0.001" if fisher_p < 0.001 else f"p = {fisher_p:.3f}"
        lines.append(f"  \\\\\\footnotesize{{Fisher's exact test: {sig}}}")
    lines.append(r"\end{table}")
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text("\n".join(lines) + "\n")


# ---------------------------------------------------------------------------
# RQ2: Latency comparison
# ---------------------------------------------------------------------------

DELTA_LABELS = {
    "delta_t0_t1": ("T0\\textrightarrow T1", "Detection latency"),
    "delta_t0_t2": ("T0\\textrightarrow T2", "Alert firing"),
    "delta_t1_t2": ("T1\\textrightarrow T2", "For-clause wait"),
    "delta_t0_t5": ("T0\\textrightarrow T5", "Total remediation"),
}

DELTA_LABELS_PLAIN = {
    "delta_t0_t1": "T0->T1 (detection)",
    "delta_t0_t2": "T0->T2 (alert firing)",
    "delta_t1_t2": "T1->T2 (for-clause)",
    "delta_t0_t5": "T0->T5 (total)",
}


def analyze_latency(df: pd.DataFrame, output_path: Optional[str] = None,
                    latex_path: Optional[str] = None):
    """Compare timing deltas between sidecar and ambient."""
    print("\n" + "=" * 70)
    print("  RQ2: Detection Latency Comparison")
    print("=" * 70)

    results = {}
    for key, label in DELTA_LABELS_PLAIN.items():
        s_vals = df.loc[(df["mode"] == "sidecar") & df[key].notna(), key].astype(float).tolist()
        a_vals = df.loc[(df["mode"] == "ambient") & df[key].notna(), key].astype(float).tolist()

        s_desc = descriptive_stats(s_vals)
        a_desc = descriptive_stats(a_vals)
        mw = mann_whitney_test(s_vals, a_vals)
        boot = bootstrap_median_diff(s_vals, a_vals)

        results[key] = {
            "label": label,
            "sidecar": s_desc,
            "ambient": a_desc,
            "mann_whitney": mw,
            "bootstrap": boot,
        }

        print(f"\n  {label}:")
        print(f"    Sidecar (n={s_desc['n']}): median={_fmt(s_desc['median'])}s, "
              f"IQR=[{_fmt(s_desc['q1'])}, {_fmt(s_desc['q3'])}], "
              f"mean={_fmt(s_desc['mean'])}+/-{_fmt(s_desc['std'])}s")
        print(f"    Ambient (n={a_desc['n']}): median={_fmt(a_desc['median'])}s, "
              f"IQR=[{_fmt(a_desc['q1'])}, {_fmt(a_desc['q3'])}], "
              f"mean={_fmt(a_desc['mean'])}+/-{_fmt(a_desc['std'])}s")
        if mw["p"] is not None:
            print(f"    Mann-Whitney: {mw['interpretation']}")
        if boot["median_diff"] is not None:
            print(f"    Bootstrap median diff (sidecar - ambient): "
                  f"{boot['median_diff']:.1f}s [{boot['ci_lo']:.1f}, {boot['ci_hi']:.1f}]")

    # Warn about small samples
    for key in results:
        for mode in ["sidecar", "ambient"]:
            n = results[key][mode]["n"]
            if 0 < n < 5:
                print(f"\n  WARNING: {mode} {DELTA_LABELS_PLAIN[key]} has only n={n} — "
                      f"results may be unreliable.")

    # Plot: box plots with strip overlay
    if output_path:
        _plot_latency(df, results, output_path)
        print(f"\n  Plot saved: {output_path}")

    if latex_path:
        _write_latency_latex(results, latex_path)
        print(f"  LaTeX saved: {latex_path}")

    return results


def _plot_latency(df: pd.DataFrame, results: dict, output_path: str):
    """Generate box + strip plot for latency comparison."""
    setup_plot_style()

    # Focus on the 3 most interesting deltas (skip T1->T2 which is the fixed for-clause)
    keys = ["delta_t0_t1", "delta_t0_t2", "delta_t0_t5"]
    labels = [DELTA_LABELS_PLAIN[k].split("(")[0].strip() for k in keys]

    fig, axes = plt.subplots(1, len(keys), figsize=(7.0, 2.8), sharey=False)
    if len(keys) == 1:
        axes = [axes]

    colors = sns.color_palette("colorblind", 2)
    mode_order = ["sidecar", "ambient"]

    for ax, key, label in zip(axes, keys, labels):
        plot_data = df[df[key].notna()][["mode", key]].copy()
        if plot_data.empty:
            ax.set_title(label)
            ax.text(0.5, 0.5, "No data", transform=ax.transAxes, ha="center", va="center")
            continue

        sns.boxplot(data=plot_data, x="mode", y=key, hue="mode", order=mode_order,
                    hue_order=mode_order, palette=colors, width=0.5, ax=ax,
                    fliersize=0, linewidth=0.8, legend=False)
        sns.stripplot(data=plot_data, x="mode", y=key, order=mode_order,
                      color="black", size=3, alpha=0.6, jitter=0.15, ax=ax)
        ax.set_xlabel("")
        ax.set_ylabel("Time (s)")
        ax.set_title(label)
        ax.set_xticks([0, 1])
        ax.set_xticklabels(["Sidecar", "Ambient"])

        # Add significance annotation
        mw = results[key]["mann_whitney"]
        if mw["p"] is not None and mw["p"] < 0.05:
            y_max = plot_data[key].max()
            ax.annotate(mw["sig"], xy=(0.5, y_max * 1.05), ha="center", fontsize=9, fontweight="bold")

    plt.tight_layout()
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(output_path)
    plt.close()


def _write_latency_latex(results: dict, path: str):
    """Write RQ2 latency comparison LaTeX table."""
    lines = [
        r"\begin{table}[htbp]",
        r"  \centering",
        r"  \caption{Timing chain comparison: sidecar vs.\ ambient (seconds). Mann-Whitney U test with rank-biserial $r$.}",
        r"  \label{tab:rq2-latency}",
        r"  \begin{tabular}{lccccccc}",
        r"    \toprule",
        r"    & \multicolumn{2}{c}{Sidecar} & \multicolumn{2}{c}{Ambient} & & & \\",
        r"    \cmidrule(lr){2-3} \cmidrule(lr){4-5}",
        r"    Metric & Median & IQR & Median & IQR & $U$ & $p$ & $r$ \\",
        r"    \midrule",
    ]
    for key in ["delta_t0_t1", "delta_t0_t2", "delta_t1_t2", "delta_t0_t5"]:
        r = results[key]
        tex_label = DELTA_LABELS[key][0]
        s, a = r["sidecar"], r["ambient"]
        mw = r["mann_whitney"]

        s_med = f"{s['median']:.1f}" if s["median"] is not None else "--"
        s_iqr = f"{s['iqr']:.1f}" if s["iqr"] is not None else "--"
        a_med = f"{a['median']:.1f}" if a["median"] is not None else "--"
        a_iqr = f"{a['iqr']:.1f}" if a["iqr"] is not None else "--"
        u_str = f"{mw['U']:.1f}" if mw["U"] is not None else "--"
        p_str = _fmt_p(mw["p"]) if mw["p"] is not None else "--"
        r_str = f"{mw['r']:.3f}" if mw["r"] is not None else "--"

        lines.append(
            f"    ${tex_label}$ & {s_med} & {s_iqr} & {a_med} & {a_iqr} & {u_str} & {p_str} & {r_str} \\\\"
        )

    lines.extend([
        r"    \bottomrule",
        r"  \end{tabular}",
        r"\end{table}",
    ])
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text("\n".join(lines) + "\n")


# ---------------------------------------------------------------------------
# RQ3: Metric completeness
# ---------------------------------------------------------------------------

def analyze_completeness(df: pd.DataFrame, output_path: Optional[str] = None,
                         latex_path: Optional[str] = None):
    """Analyze metric completeness per mode."""
    print("\n" + "=" * 70)
    print("  RQ3: Metric Completeness")
    print("=" * 70)

    timing_fields = ["t0", "t1", "t2", "t4", "t5"]
    metric_fields = ["stable_error_rate", "stable_p99_latency_ms"]

    results = {}
    for mode in ["sidecar", "ambient"]:
        subset = df[df["mode"] == mode]
        n = len(subset)
        if n == 0:
            results[mode] = {"n": 0, "timing_complete": 0, "metrics_complete": 0, "overall": 0}
            continue

        # Timing completeness: all T0-T5 present and non-null
        timing_ok = subset[timing_fields].notna().all(axis=1).sum()
        timing_rate = timing_ok / n

        # Metric snapshot completeness
        metrics_ok = subset[metric_fields].notna().all(axis=1).sum()
        metrics_rate = metrics_ok / n

        # Overall: weighted average
        overall = 0.6 * timing_rate + 0.4 * metrics_rate

        timing_ci = clopper_pearson_ci(int(timing_ok), n)
        metrics_ci = clopper_pearson_ci(int(metrics_ok), n)

        results[mode] = {
            "n": n,
            "timing_complete": int(timing_ok),
            "timing_rate": timing_rate,
            "timing_ci": timing_ci,
            "metrics_complete": int(metrics_ok),
            "metrics_rate": metrics_rate,
            "metrics_ci": metrics_ci,
            "overall": overall,
        }

        print(f"\n  {mode.capitalize()} (n={n}):")
        print(f"    Timing completeness:  {timing_ok}/{n} ({timing_rate*100:.1f}%) "
              f"[{timing_ci[0]*100:.1f}%, {timing_ci[1]*100:.1f}%]")
        print(f"    Metrics completeness: {metrics_ok}/{n} ({metrics_rate*100:.1f}%) "
              f"[{metrics_ci[0]*100:.1f}%, {metrics_ci[1]*100:.1f}%]")
        print(f"    Overall score:        {overall*100:.1f}%")

    # Fisher's exact for timing completeness comparison
    s, a = results.get("sidecar", {}), results.get("ambient", {})
    if s.get("n", 0) > 0 and a.get("n", 0) > 0:
        table = [
            [s["timing_complete"], s["n"] - s["timing_complete"]],
            [a["timing_complete"], a["n"] - a["timing_complete"]],
        ]
        _, fisher_p = sp_stats.fisher_exact(table)
        sig = "***" if fisher_p < 0.001 else "**" if fisher_p < 0.01 else "*" if fisher_p < 0.05 else "ns"
        print(f"\n  Fisher's exact (timing): p={fisher_p:.4f} {sig}")

    if output_path:
        _plot_completeness(results, output_path)
        print(f"\n  Plot saved: {output_path}")

    if latex_path:
        _write_completeness_latex(results, latex_path)
        print(f"  LaTeX saved: {latex_path}")

    return results


def _plot_completeness(results: dict, output_path: str):
    """Generate stacked bar chart for completeness."""
    setup_plot_style()
    fig, ax = plt.subplots(figsize=(3.5, 2.8))

    modes = ["Sidecar", "Ambient"]
    timing_rates = [results.get("sidecar", {}).get("timing_rate", 0) * 100,
                    results.get("ambient", {}).get("timing_rate", 0) * 100]
    metrics_rates = [results.get("sidecar", {}).get("metrics_rate", 0) * 100,
                     results.get("ambient", {}).get("metrics_rate", 0) * 100]

    x = np.arange(len(modes))
    width = 0.35
    colors = sns.color_palette("colorblind", 2)

    ax.bar(x - width / 2, timing_rates, width, label="Timing chain", color=colors[0], edgecolor="black", linewidth=0.5)
    ax.bar(x + width / 2, metrics_rates, width, label="Metric snapshots", color=colors[1], edgecolor="black", linewidth=0.5)

    ax.set_ylabel("Completeness (%)")
    ax.set_xticks(x)
    ax.set_xticklabels(modes)
    ax.set_ylim(0, 110)
    ax.yaxis.set_major_formatter(_de_percent_formatter(0))
    ax.legend(loc="lower right")

    plt.tight_layout()
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(output_path)
    plt.close()


def _write_completeness_latex(results: dict, path: str):
    """Write RQ3 completeness LaTeX table."""
    lines = [
        r"\begin{table}[htbp]",
        r"  \centering",
        r"  \caption{Metric completeness comparison (Clopper-Pearson 95\% CI).}",
        r"  \label{tab:rq3-completeness}",
        r"  \begin{tabular}{lcccc}",
        r"    \toprule",
        r"    Mode & Timing & 95\% CI & Metrics & Overall \\",
        r"    \midrule",
    ]
    for mode in ["sidecar", "ambient"]:
        r = results.get(mode, {})
        if r.get("n", 0) == 0:
            lines.append(f"    {mode.capitalize()} & -- & -- & -- & -- \\\\")
            continue
        t_ci = r.get("timing_ci", (0, 0))
        lines.append(
            f"    {mode.capitalize()} & {r['timing_rate']*100:.1f}\\% "
            f"& [{t_ci[0]*100:.1f}\\%, {t_ci[1]*100:.1f}\\%] "
            f"& {r['metrics_rate']*100:.1f}\\% & {r['overall']*100:.1f}\\% \\\\"
        )
    lines.extend([
        r"    \bottomrule",
        r"  \end{tabular}",
        r"\end{table}",
    ])
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text("\n".join(lines) + "\n")


# ---------------------------------------------------------------------------
# Resource comparison
# ---------------------------------------------------------------------------

_CPU_UNITS = {"n": 1e-6, "u": 1e-3, "m": 1.0, "": 1000.0}  # → millicores
_MEM_UNITS = {  # → MiB
    "Ki": 1 / 1024, "Mi": 1.0, "Gi": 1024.0, "Ti": 1024.0 * 1024.0,
    "K": 1000 / (1024 * 1024), "M": 1_000_000 / (1024 * 1024),
    "G": 1_000_000_000 / (1024 * 1024), "": 1 / (1024 * 1024),
}


def _parse_cpu(val) -> float:
    """Parse Kubernetes CPU quantity to millicores. Accepts '8m', '0.5', 8, etc."""
    if isinstance(val, (int, float)):
        return float(val) * 1000.0  # bare number = cores
    if not val:
        return 0.0
    s = str(val).strip()
    for suffix, factor in _CPU_UNITS.items():
        if suffix and s.endswith(suffix):
            try:
                return float(s[: -len(suffix)]) * factor
            except ValueError:
                return 0.0
    try:
        return float(s) * 1000.0
    except ValueError:
        return 0.0


def _parse_mem(val) -> float:
    """Parse Kubernetes memory quantity to MiB. Accepts '154Mi', '1Gi', 154, etc."""
    if isinstance(val, (int, float)):
        return float(val) / (1024 * 1024)  # bare number = bytes
    if not val:
        return 0.0
    s = str(val).strip()
    # Match longest suffix first (Ki/Mi/Gi/Ti before K/M/G/T).
    for suffix in ("Ki", "Mi", "Gi", "Ti", "K", "M", "G", "T"):
        if s.endswith(suffix):
            try:
                return float(s[: -len(suffix)]) * _MEM_UNITS[suffix]
            except ValueError:
                return 0.0
    try:
        return float(s) * _MEM_UNITS[""]
    except ValueError:
        return 0.0


def _istio_system_pods(snapshot: dict) -> list[dict]:
    """Return the istio-system pods from a resources-{pre,post}.json snapshot."""
    pods = snapshot.get("pods")
    if pods is None:
        # Legacy/alternative schema fallback.
        return snapshot.get("istio_system", [])
    return [p for p in pods if p.get("namespace") == "istio-system"]


def analyze_resources(sidecar_dir: Path, ambient_dir: Path, output_path: Optional[str] = None):
    """Compare resource usage between modes."""
    print("\n" + "=" * 70)
    print("  Resource Overhead Comparison")
    print("=" * 70)

    s_res = load_resources(sidecar_dir)
    a_res = load_resources(ambient_dir)

    for mode_label, res in [("Sidecar", s_res), ("Ambient", a_res)]:
        pre = res.get("pre", {})
        print(f"\n  {mode_label} — istio-system (pre-experiment):")
        pods = _istio_system_pods(pre)
        if not pods:
            print("    No data available.")
            continue
        total_cpu = 0.0
        total_mem = 0.0
        for p in pods:
            name = p.get("name") or p.get("pod", "?")
            cpu_m = _parse_cpu(p.get("cpu", p.get("cpu_millicores", 0)))
            mem_mi = _parse_mem(p.get("memory", p.get("memory_mib", 0)))
            total_cpu += cpu_m
            total_mem += mem_mi
            print(f"    {name:<48} CPU: {cpu_m:>6.1f}m  Mem: {mem_mi:>7.1f}Mi")
        print(f"    {'TOTAL':<48} CPU: {total_cpu:>6.1f}m  Mem: {total_mem:>7.1f}Mi")

    if output_path and (s_res.get("pre") or a_res.get("pre")):
        _plot_resources(s_res, a_res, output_path)
        print(f"\n  Plot saved: {output_path}")


def _plot_resources(s_res: dict, a_res: dict, output_path: str):
    """Generate resource comparison bar chart."""
    setup_plot_style()

    def extract_totals(res: dict) -> tuple[float, float]:
        pods = _istio_system_pods(res.get("pre", {}))
        cpu = sum(_parse_cpu(p.get("cpu", p.get("cpu_millicores", 0))) for p in pods)
        mem = sum(_parse_mem(p.get("memory", p.get("memory_mib", 0))) for p in pods)
        return cpu, mem

    s_cpu, s_mem = extract_totals(s_res)
    a_cpu, a_mem = extract_totals(a_res)

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(5.0, 2.8))
    colors = sns.color_palette("colorblind", 2)
    modes = ["Sidecar", "Ambient"]

    cpu_bars = ax1.bar(modes, [s_cpu, a_cpu], color=colors, width=0.5, edgecolor="black", linewidth=0.5)
    ax1.set_ylabel("CPU (millicores)")
    ax1.set_title("Control plane CPU")
    ax1.set_ylim(0, max(s_cpu, a_cpu) * 1.18 if max(s_cpu, a_cpu) > 0 else 1)
    for bar, val in zip(cpu_bars, [s_cpu, a_cpu]):
        ax1.text(bar.get_x() + bar.get_width() / 2, bar.get_height(),
                 f"{_de(val, 0)} m", ha="center", va="bottom", fontsize=8)

    mem_bars = ax2.bar(modes, [s_mem, a_mem], color=colors, width=0.5, edgecolor="black", linewidth=0.5)
    ax2.set_ylabel("Memory (MiB)")
    ax2.set_title("Control plane memory")
    ax2.set_ylim(0, max(s_mem, a_mem) * 1.18 if max(s_mem, a_mem) > 0 else 1)
    for bar, val in zip(mem_bars, [s_mem, a_mem]):
        ax2.text(bar.get_x() + bar.get_width() / 2, bar.get_height(),
                 f"{_de(val, 0)} MiB", ha="center", va="bottom", fontsize=8)

    plt.tight_layout()
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(output_path)
    plt.close()


# ---------------------------------------------------------------------------
# Summary (console only)
# ---------------------------------------------------------------------------

def print_summary(df: pd.DataFrame, sidecar_dir: Path, ambient_dir: Path):
    """Print a complete console summary without generating files."""
    analyze_reliability(df)
    analyze_latency(df)
    analyze_completeness(df)
    analyze_resources(sidecar_dir, ambient_dir)


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def _fmt(val) -> str:
    if val is None:
        return "N/A"
    return f"{val:.1f}"


def _fmt_p(p: float) -> str:
    if p < 0.001:
        return "< 0.001"
    return f"{p:.3f}"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="BA2 thesis statistical analysis: Istio sidecar vs ambient canary deployments"
    )
    parser.add_argument("command", choices=["all", "latency", "reliability", "completeness", "resources", "summary"],
                        help="Analysis to run")
    parser.add_argument("sidecar_dir", type=Path, help="Path to sidecar batch results directory")
    parser.add_argument("ambient_dir", type=Path, help="Path to ambient batch results directory")
    parser.add_argument("--output", "-o", type=str, default=None, help="Output plot path (PDF/PNG)")
    parser.add_argument("--latex", "-l", type=str, default=None, help="Output LaTeX table path")
    parser.add_argument("--output-dir", type=str, default=None, help="Output directory for all plots (used with 'all')")
    parser.add_argument("--latex-dir", type=str, default=None, help="Output directory for all LaTeX tables (used with 'all')")

    args = parser.parse_args()

    # Load data
    sidecar_runs = load_run_data(args.sidecar_dir)
    ambient_runs = load_run_data(args.ambient_dir)
    print(f"Loaded {len(sidecar_runs)} sidecar runs, {len(ambient_runs)} ambient runs.")

    if not sidecar_runs and not ambient_runs:
        print("ERROR: No data found in either directory.", file=sys.stderr)
        sys.exit(1)

    df = runs_to_dataframe(sidecar_runs, ambient_runs)

    if args.command == "summary":
        print_summary(df, args.sidecar_dir, args.ambient_dir)

    elif args.command == "reliability":
        analyze_reliability(df, output_path=args.output, latex_path=args.latex)

    elif args.command == "latency":
        analyze_latency(df, output_path=args.output, latex_path=args.latex)

    elif args.command == "completeness":
        analyze_completeness(df, output_path=args.output, latex_path=args.latex)

    elif args.command == "resources":
        analyze_resources(args.sidecar_dir, args.ambient_dir, output_path=args.output)

    elif args.command == "all":
        out_dir = Path(args.output_dir) if args.output_dir else None
        tex_dir = Path(args.latex_dir) if args.latex_dir else None

        analyze_reliability(
            df,
            output_path=str(out_dir / "rq1_reliability.pdf") if out_dir else None,
            latex_path=str(tex_dir / "rq1_reliability.tex") if tex_dir else None,
        )
        analyze_latency(
            df,
            output_path=str(out_dir / "rq2_latency.pdf") if out_dir else None,
            latex_path=str(tex_dir / "rq2_latency.tex") if tex_dir else None,
        )
        analyze_completeness(
            df,
            output_path=str(out_dir / "rq3_completeness.pdf") if out_dir else None,
            latex_path=str(tex_dir / "rq3_completeness.tex") if tex_dir else None,
        )
        analyze_resources(
            args.sidecar_dir, args.ambient_dir,
            output_path=str(out_dir / "resource_comparison.pdf") if out_dir else None,
        )


if __name__ == "__main__":
    main()
