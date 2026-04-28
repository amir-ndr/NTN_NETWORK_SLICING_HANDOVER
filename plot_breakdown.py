#!/usr/bin/env python3
"""
Stacked bar plot: mean latency breakdown per baseline (B1, B2, B3).

Segments per bar (bottom to top):
  AMF processing  — from chain_log_bX.csv (col 0)
  SMF processing  — from chain_log_bX.csv (col 1)
  UPF processing  — from chain_log_bX.csv (col 2)
  NGAP PathSwitch — ue_switch_ms from xn_ho_latency_bX.csv (col 2)
  Xn + Release    — residual: total_ms − (chain + ngap)

Usage:
    python3 plot_breakdown.py
"""

import os
import numpy as np
import matplotlib.pyplot as plt
import matplotlib

matplotlib.rcParams.update({
    "font.size": 12,
    "axes.labelsize": 13,
    "axes.titlesize": 13,
    "legend.fontsize": 10,
})

LAB = "/home/amirndr/5g-lab"

BASELINES = [
    {
        "label":    "B1\nFixed mono-chain",
        "main_csv": f"{LAB}/xn_ho_latency_b1.csv",
        "chain_csv": f"{LAB}/chain_log_b1.csv",
        "color_amf": "#1565C0",
        "color_smf": "#1E88E5",
        "color_upf": "#64B5F6",
    },
    {
        "label":    "B2\nRandom selection",
        "main_csv": f"{LAB}/xn_ho_latency_b2.csv",
        "chain_csv": f"{LAB}/chain_log_b2.csv",
        "color_amf": "#BF360C",
        "color_smf": "#E64A19",
        "color_upf": "#FF8A65",
    },
    {
        "label":    "B3\nBregman online",
        "main_csv": f"{LAB}/xn_ho_latency_b3.csv",
        "chain_csv": f"{LAB}/chain_log_b3.csv",
        "color_amf": "#1B5E20",
        "color_smf": "#388E3C",
        "color_upf": "#81C784",
    },
]

# Shared colours for NGAP and Xn+Release (same across baselines)
COLOR_NGAP    = "#7B1FA2"
COLOR_OVERHEAD = "#9E9E9E"


def load(main_csv, chain_csv):
    """Return (amf, smf, upf, ngap, xn_rel) mean arrays, or None if missing."""
    if not os.path.exists(main_csv) or not os.path.exists(chain_csv):
        return None

    main  = np.loadtxt(main_csv,  delimiter=",")
    chain = np.loadtxt(chain_csv, delimiter=",")

    if main.size == 0 or chain.size == 0:
        return None
    if main.ndim == 1:
        main = main.reshape(1, -1)
    if chain.ndim == 1:
        chain = chain.reshape(1, -1)

    # Align row counts (take the minimum in case of partial runs)
    n = min(len(main), len(chain))
    main, chain = main[:n], chain[:n]

    amf_ms   = chain[:, 0]
    smf_ms   = chain[:, 1]
    upf_ms   = chain[:, 2]
    ngap_ms  = main[:, 2].astype(float)          # ue_switch_ms
    total_ms = main[:, 4].astype(float)
    chain_total = amf_ms + smf_ms + upf_ms
    xn_rel_ms = np.maximum(total_ms - chain_total - ngap_ms, 0)

    return (amf_ms.mean(), smf_ms.mean(), upf_ms.mean(),
            ngap_ms.mean(), xn_rel_ms.mean())


fig, ax = plt.subplots(figsize=(8, 5))

x        = np.arange(len(BASELINES))
bar_w    = 0.5
labels_x = [b["label"] for b in BASELINES]

bottoms = np.zeros(len(BASELINES))
legend_handles = []

for seg_name, seg_idx, color_key, shared_color in [
    ("AMF processing",  0, "color_amf",  None),
    ("SMF processing",  1, "color_smf",  None),
    ("UPF processing",  2, "color_upf",  None),
    ("NGAP PathSwitch", 3, None,          COLOR_NGAP),
    ("Xn + Release",    4, None,          COLOR_OVERHEAD),
]:
    values = []
    colors = []
    for b in BASELINES:
        data = load(b["main_csv"], b["chain_csv"])
        values.append(data[seg_idx] if data else 0.0)
        colors.append(b[color_key] if color_key else shared_color)

    values = np.array(values)

    # Draw each bar segment individually (different colours per baseline)
    for i, (v, c) in enumerate(zip(values, colors)):
        bar = ax.bar(x[i], v, bar_w, bottom=bottoms[i], color=c,
                     edgecolor="white", linewidth=0.5)
    bottoms += values

    # One legend entry per segment using the first baseline's colour
    legend_handles.append(
        plt.Rectangle((0, 0), 1, 1,
                       color=colors[0] if color_key else shared_color,
                       label=seg_name)
    )

# ── Annotate total on top of each bar ────────────────────────────────────────
for i, b in enumerate(BASELINES):
    data = load(b["main_csv"], b["chain_csv"])
    if data:
        total = sum(data)
        ax.text(x[i], bottoms[i] + 0.5, f"{total:.1f}ms",
                ha="center", va="bottom", fontsize=10, fontweight="bold")

ax.set_xticks(x)
ax.set_xticklabels(labels_x)
ax.set_ylabel("Mean Latency (ms)")
ax.set_title("Handover Latency Breakdown by NF Component")
ax.set_ylim(0, bottoms.max() * 1.18)
ax.legend(handles=legend_handles, loc="upper right", framealpha=0.9)
ax.grid(axis="y", alpha=0.3)
plt.tight_layout()

out = "breakdown_handover.pdf"
plt.savefig(out, dpi=300)
print(f"Saved → {out}")

# ── Print table ───────────────────────────────────────────────────────────────
print(f"\n{'Baseline':<22} {'AMF':>7} {'SMF':>7} {'UPF':>7} {'NGAP':>7} {'Xn+Rel':>7} {'Total':>8}")
print("-" * 65)
for b in BASELINES:
    data = load(b["main_csv"], b["chain_csv"])
    if data:
        label = b["label"].replace("\n", " ")
        print(f"{label:<22} {data[0]:>7.1f} {data[1]:>7.1f} {data[2]:>7.1f} "
              f"{data[3]:>7.1f} {data[4]:>7.1f} {sum(data):>8.1f}")

plt.show()
