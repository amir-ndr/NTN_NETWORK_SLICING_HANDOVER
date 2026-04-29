#!/usr/bin/env python3
"""
NTN Stacked Bar — mean latency breakdown per baseline, same style as
plot_breakdown.py but with a 6th segment: NTN Propagation RTT.

Segments (bottom → top):
  AMF processing   — chain_log_bX.csv col 0
  SMF processing   — chain_log_bX.csv col 1
  UPF processing   — chain_log_bX.csv col 2
  NGAP PathSwitch  — xn_ho_latency_bX.csv col 2
  Xn + Release     — residual: total − chain − ngap
  NTN Propagation  — mean prop_rtt from ntn_prop_delay_trace.csv [NEW]

Saves: ntn_breakdown_handover.pdf
"""

import os
import csv
import numpy as np
import matplotlib
import matplotlib.pyplot as plt

matplotlib.rcParams.update({
    "font.size": 12,
    "axes.labelsize": 13,
    "axes.titlesize": 13,
    "legend.fontsize": 10,
    "axes.spines.top":   False,
    "axes.spines.right": False,
})

LAB = "/home/amirndr/5g-lab"

BASELINES = [
    {
        "label":     "B1\nFixed mono-chain",
        "main_csv":  f"{LAB}/xn_ho_latency_b1.csv",
        "chain_csv": f"{LAB}/chain_log_b1.csv",
        "color_amf": "#1565C0",
        "color_smf": "#1E88E5",
        "color_upf": "#64B5F6",
    },
    {
        "label":     "B2\nRandom selection",
        "main_csv":  f"{LAB}/xn_ho_latency_b2.csv",
        "chain_csv": f"{LAB}/chain_log_b2.csv",
        "color_amf": "#BF360C",
        "color_smf": "#E64A19",
        "color_upf": "#FF8A65",
    },
    {
        "label":     "B3\nBregman online",
        "main_csv":  f"{LAB}/xn_ho_latency_b3.csv",
        "chain_csv": f"{LAB}/chain_log_b3.csv",
        "color_amf": "#1B5E20",
        "color_smf": "#388E3C",
        "color_upf": "#81C784",
    },
]

COLOR_NGAP  = "#7B1FA2"
COLOR_XN    = "#9E9E9E"
COLOR_PROP  = "#E65100"   # orange — NTN propagation segment


def load_breakdown(main_csv, chain_csv):
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
    n = min(len(main), len(chain))
    main, chain = main[:n], chain[:n]

    amf  = chain[:, 0].mean()
    smf  = chain[:, 1].mean()
    upf  = chain[:, 2].mean()
    ngap = main[:, 2].astype(float).mean()
    total = main[:, 4].astype(float).mean()
    xn   = max(total - (amf + smf + upf + ngap), 0.0)
    return amf, smf, upf, ngap, xn


def load_mean_prop_rtt(path):
    rtts = []
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            rtts.append(float(row["prop_rtt_ms"]))
    return float(np.mean(rtts))


prop_path = f"{LAB}/ntn_prop_delay_trace.csv"
if not os.path.exists(prop_path):
    print("ERROR: ntn_prop_delay_trace.csv not found — run ntn_prop_trace.py first.")
    exit(1)
mean_prop_rtt = load_mean_prop_rtt(prop_path)

fig, ax = plt.subplots(figsize=(8, 5))

x     = np.arange(len(BASELINES))
bar_w = 0.5
bottoms = np.zeros(len(BASELINES))
legend_handles = []

# ── Segments 1-5: same as original breakdown ──────────────────────────────────
for seg_name, seg_idx, color_key, shared_color in [
    ("AMF processing",  0, "color_amf", None),
    ("SMF processing",  1, "color_smf", None),
    ("UPF processing",  2, "color_upf", None),
    ("NGAP PathSwitch", 3, None, COLOR_NGAP),
    ("Xn + Release",    4, None, COLOR_XN),
]:
    values = []
    colors = []
    for b in BASELINES:
        data = load_breakdown(b["main_csv"], b["chain_csv"])
        values.append(data[seg_idx] if data else 0.0)
        colors.append(b[color_key] if color_key else shared_color)
    values = np.array(values)

    for i, (v, c) in enumerate(zip(values, colors)):
        ax.bar(x[i], v, bar_w, bottom=bottoms[i],
               color=c, edgecolor="white", linewidth=0.5)
    bottoms += values

    legend_handles.append(plt.Rectangle(
        (0, 0), 1, 1,
        color=colors[0] if color_key else shared_color,
        label=seg_name,
    ))

# ── Segment 6: NTN Propagation (same value for all baselines) ────────────────
for i in range(len(BASELINES)):
    ax.bar(x[i], mean_prop_rtt, bar_w, bottom=bottoms[i],
           color=COLOR_PROP, edgecolor="white", linewidth=0.5,
           hatch="//", alpha=0.85)
bottoms += mean_prop_rtt

legend_handles.append(plt.Rectangle(
    (0, 0), 1, 1, color=COLOR_PROP,
    label=f"NTN Propagation RTT  ({mean_prop_rtt:.1f}ms mean)",
))

# ── Total annotations ─────────────────────────────────────────────────────────
for i, b in enumerate(BASELINES):
    data = load_breakdown(b["main_csv"], b["chain_csv"])
    if data:
        ntn_total = sum(data) + mean_prop_rtt
        ax.text(x[i], bottoms[i] + 0.4, f"{ntn_total:.1f}ms",
                ha="center", va="bottom", fontsize=10, fontweight="bold")

# ── Terrestrial total reference line (dashed, per baseline) ──────────────────
for i, b in enumerate(BASELINES):
    data = load_breakdown(b["main_csv"], b["chain_csv"])
    if data:
        terr_total = sum(data)
        ax.plot([x[i] - bar_w/2, x[i] + bar_w/2],
                [terr_total, terr_total],
                color="black", lw=1.2, ls="--", alpha=0.6)

legend_handles.append(plt.Line2D(
    [0], [0], color="black", lw=1.2, ls="--", alpha=0.7,
    label="Terrestrial total (no NTN)",
))

ax.set_xticks(x)
ax.set_xticklabels([b["label"] for b in BASELINES])
ax.set_ylabel("Mean Latency (ms)")
ax.set_title(
    "NTN Handover Latency Breakdown — Starlink h=550km\n"
    "Hatched top segment = NTN propagation RTT (physics, uncontrollable)",
    fontsize=10,
)
ax.set_ylim(0, bottoms.max() * 1.20)
ax.legend(handles=legend_handles, loc="upper right",
          framealpha=0.92, fontsize=9.5)
ax.grid(axis="y", alpha=0.25, lw=0.6)

plt.tight_layout()
out = "ntn_breakdown_handover.pdf"
plt.savefig(out, dpi=300, bbox_inches="tight")
print(f"Saved → {out}")

# ── Summary table ─────────────────────────────────────────────────────────────
print(f"\n  Mean NTN Propagation RTT: {mean_prop_rtt:.2f} ms\n")
print(f"{'Baseline':<22} {'AMF':>6} {'SMF':>6} {'UPF':>6} "
      f"{'NGAP':>6} {'Xn+Rel':>7} {'Prop':>6} {'NTN Total':>10}")
print("─" * 75)
for b in BASELINES:
    data = load_breakdown(b["main_csv"], b["chain_csv"])
    if data:
        label = b["label"].replace("\n", " ")
        print(f"  {label:<20} {data[0]:>6.1f} {data[1]:>6.1f} {data[2]:>6.1f} "
              f"{data[3]:>6.1f} {data[4]:>7.1f} {mean_prop_rtt:>6.1f} "
              f"{sum(data)+mean_prop_rtt:>10.1f}ms")
