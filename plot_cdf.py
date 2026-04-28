#!/usr/bin/env python3
"""
Plot CDF(%) vs Latency(ms) for one or more baselines.

Usage:
  python3 plot_cdf.py                        # B1 only
  python3 plot_cdf.py b1.csv b2.csv b3.csv  # overlay all three
"""

import sys, os
import numpy as np
import matplotlib.pyplot as plt
import matplotlib

matplotlib.rcParams.update({
    "font.size": 12,
    "axes.labelsize": 13,
    "legend.fontsize": 11,
    "lines.linewidth": 2,
})

# ── Input files ──────────────────────────────────────────────────────────────
# Each CSV row: sst, prep_psw_ms, ue_switch_ms, release_ms, total_ms
TOTAL_COL = 4   # 0-indexed column for total HO latency

if len(sys.argv) > 1:
    files = sys.argv[1:]
else:
    files = ["/home/amirndr/5g-lab/xn_ho_latency.csv"]

labels = {
    "/home/amirndr/5g-lab/xn_ho_latency.csv":    "B1 – Mono-chain (no dispatcher)",
    "/home/amirndr/5g-lab/xn_ho_latency_b2.csv": "B2 – Random selection",
    "/home/amirndr/5g-lab/xn_ho_latency_b3.csv": "B3 – Bregman online",
}
styles = [
    {"color": "#2196F3", "linestyle": "-"},
    {"color": "#FF5722", "linestyle": "--"},
    {"color": "#4CAF50", "linestyle": "-."},
]

fig, ax = plt.subplots(figsize=(7, 4.5))

for idx, fpath in enumerate(files):
    if not os.path.exists(fpath):
        print(f"Warning: {fpath} not found, skipping.")
        continue

    data = np.loadtxt(fpath, delimiter=",")
    if data.size == 0:
        print(f"Warning: {fpath} is empty, skipping.")
        continue
    if data.ndim == 1:
        data = data.reshape(1, -1)

    total_ms = data[:, TOTAL_COL].astype(float)
    total_ms.sort()
    cdf = np.arange(1, len(total_ms) + 1) / len(total_ms) * 100

    label = labels.get(fpath, os.path.basename(fpath))
    style = styles[idx % len(styles)]
    ax.plot(total_ms, cdf, label=label, **style)

    # Print summary stats
    print(f"{label}")
    print(f"  n={len(total_ms)}  mean={total_ms.mean():.1f}ms  "
          f"p50={np.percentile(total_ms,50):.1f}ms  "
          f"p90={np.percentile(total_ms,90):.1f}ms  "
          f"p99={np.percentile(total_ms,99):.1f}ms")

ax.set_xlabel("Handover Latency (ms)")
ax.set_ylabel("CDF (%)")
ax.set_ylim(0, 101)
ax.set_xlim(left=0)
ax.grid(True, alpha=0.3)
ax.legend(loc="lower right")
plt.tight_layout()

out = "cdf_handover.pdf"
plt.savefig(out, dpi=300)
print(f"\nSaved → {out}")
plt.show()
