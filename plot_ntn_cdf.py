#!/usr/bin/env python3
"""
NTN Handover Latency CDF — terrestrial vs NTN comparison.

For each baseline:
    L_terrestrial(t) = total from xn_ho_latency_bX.csv  (col 4)
    L_NTN(t)         = L_terrestrial(t) + prop_rtt(t)   [from ntn_prop_delay_trace.csv]

Layout: single panel, 6 lines (3 baselines × 2: dashed=terrestrial, solid=NTN)
Saves: ntn_cdf_handover.pdf
"""

import os
import csv
import numpy as np
import matplotlib
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D

matplotlib.rcParams.update({
    "font.size": 12,
    "axes.labelsize": 13,
    "legend.fontsize": 10,
    "lines.linewidth": 2,
    "axes.spines.top":   False,
    "axes.spines.right": False,
})

LAB = "/home/amirndr/5g-lab"

BASELINES = [
    {"label": "B1 — Fixed Mono-Chain",
     "csv": f"{LAB}/xn_ho_latency_b1.csv",
     "color": "#1565C0"},
    {"label": "B2 — Random Selection",
     "csv": f"{LAB}/xn_ho_latency_b2.csv",
     "color": "#C62828"},
    {"label": "B3 — Bregman Online",
     "csv": f"{LAB}/xn_ho_latency_b3.csv",
     "color": "#2E7D32"},
]

TOTAL_COL = 4   # column index for total latency in xn_ho_latency_bX.csv


def load_prop_rtt(path):
    rtts = []
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            rtts.append(float(row["prop_rtt_ms"]))
    return np.array(rtts)


prop_path = f"{LAB}/ntn_prop_delay_trace.csv"
if not os.path.exists(prop_path):
    print("ERROR: ntn_prop_delay_trace.csv not found — run ntn_prop_trace.py first.")
    exit(1)
prop_rtt = load_prop_rtt(prop_path)

fig, ax = plt.subplots(figsize=(8, 5))

print(f"\n{'Baseline':<28}  {'Terr. p50':>10} {'Terr. p90':>10}  "
      f"{'NTN  p50':>10} {'NTN  p90':>10}  {'Δ mean':>8}")
print("─" * 82)

for bl in BASELINES:
    if not os.path.exists(bl["csv"]):
        print(f"  [SKIP] {bl['csv']} not found")
        continue

    data = np.loadtxt(bl["csv"], delimiter=",")
    if data.ndim == 1:
        data = data.reshape(1, -1)

    terr = data[:, TOTAL_COL].astype(float)

    # Align with prop trace (take min length)
    n = min(len(terr), len(prop_rtt))
    terr_aligned = terr[:n]
    ntn          = terr_aligned + prop_rtt[:n]

    # CDF
    terr_s = np.sort(terr_aligned)
    ntn_s  = np.sort(ntn)
    cdf    = np.arange(1, n + 1) / n * 100

    ax.plot(terr_s, cdf, color=bl["color"], ls="--", lw=1.6, alpha=0.55)
    ax.plot(ntn_s,  cdf, color=bl["color"], ls="-",  lw=2.0,
            label=bl["label"])

    delta = ntn.mean() - terr_aligned.mean()
    print(f"  {bl['label']:<26}  "
          f"{np.percentile(terr_aligned,50):>8.1f}ms {np.percentile(terr_aligned,90):>8.1f}ms  "
          f"{np.percentile(ntn,50):>8.1f}ms {np.percentile(ntn,90):>8.1f}ms  "
          f"+{delta:>6.1f}ms")

mean_prop = prop_rtt.mean()

# ── Legend ────────────────────────────────────────────────────────────────────
baseline_handles = [
    Line2D([0], [0], color=bl["color"], lw=2.0, label=bl["label"])
    for bl in BASELINES if os.path.exists(bl["csv"])
]
style_handles = [
    Line2D([0], [0], color="gray", ls="--", lw=1.6, label="Terrestrial (no NTN)"),
    Line2D([0], [0], color="gray", ls="-",  lw=2.0,
           label=f"NTN (+ {mean_prop:.1f}ms prop RTT)"),
]
ax.legend(handles=baseline_handles + style_handles,
          loc="lower right", framealpha=0.92, fontsize=9.5)

ax.set_xlabel("Handover Latency (ms)")
ax.set_ylabel("CDF (%)")
ax.set_ylim(0, 101)
ax.set_xlim(left=0)
ax.set_title(
    "NTN Handover Latency CDF — Starlink h=550km\n"
    f"Dashed: terrestrial   Solid: +NTN propagation (mean RTT = {mean_prop:.1f}ms)",
    fontsize=10,
)
ax.grid(True, alpha=0.25, lw=0.6)

plt.tight_layout()
out = "ntn_cdf_handover.pdf"
plt.savefig(out, dpi=300, bbox_inches="tight")
print(f"\nSaved → {out}")
