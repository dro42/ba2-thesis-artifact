# Analysis

Statistical comparison of sidecar vs. ambient experiment batches and figure generation for the thesis Results chapter.

## Setup

```bash
cd analysis
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Tested with Python 3.11 and 3.12 on macOS and Linux.

## Run on the Bundled Examples

The repo ships one full 10-run batch per mode under `../examples/results/`. To regenerate the per-mode summary, the cross-mode comparison, and all figures:

```bash
python thesis_stats.py all \
  ../examples/results/sidecar/20260403-123733 \
  ../examples/results/ambient/20260403-184055
```

## Subcommands

The statistical methods (Mann-Whitney U with Bonferroni correction, Clopper-Pearson exact intervals at zero events, bootstrap with 10⁴ resamples, Holm cross-check) are described in thesis §3.9 (Statistical Methods); this file documents how to invoke them. `thesis_stats.py` is a small CLI with subcommands; the main one used in the thesis is `all`:

| Subcommand | What it does |
|---|---|
| `summary <batch-dir>` | Per-batch descriptive statistics (mean, median, IQR, min, max for every timing field). |
| `compare <sidecar-batch> <ambient-batch>` | Two-sample tests (Mann-Whitney U with Bonferroni correction across the timing fields). |
| `plot <sidecar-batch> <ambient-batch>` | Box and violin plots of the timing distributions, error rate distributions, and rollout-phase outcome counts. |
| `all <sidecar-batch> <ambient-batch>` | Runs `summary`, `compare`, `plot` in sequence. |

Output figures land in `analysis/output/` by default.

## What the Figures Show

- **`timing-box.pdf`**: Box plots of `t0_to_t1` (alert detection latency) and `t0_to_t2` (fault-to-firing latency) for both modes. The thesis Results chapter cites these directly.
- **`timing-violin.pdf`**: Violin plot of the same data, showing the distribution shape.
- **`error-rate-distribution.pdf`**: Distribution of `metrics_snapshot.stable_error_rate` per mode.
- **`outcome-bars.pdf`**: Stacked bar chart of `outcome` (true_negative / remediated / false_positive / false_negative / incomplete) per mode.
- **`comparison.csv`**: The flat dataset used to draw all of the above; useful if you prefer your own plotting.

## Reproducibility Notes

- The script uses `locale.setlocale(...)` for German decimal formatting in the figures (comma decimal). Set `LC_NUMERIC=C` if you want US-style commas (or `LC_NUMERIC=de_AT.UTF-8` for the original thesis output).
- All seeds are deterministic; running the script twice on the same data produces byte-identical figure files.
- The Mann-Whitney implementation is `scipy.stats.mannwhitneyu(..., alternative='two-sided', method='asymptotic')`. With n=10+10 the exact method is also tractable and produces near-identical p-values.
