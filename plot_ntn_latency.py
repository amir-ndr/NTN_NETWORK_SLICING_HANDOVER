#!/usr/bin/env python3
"""
NTN Total Handover Latency — Composition Plot.

Combines:
  - chain_log_bX.csv  : NF chain cost per round (AMF+SMF+UPF, ms) — from dispatchers
  - ntn_prop_delay_trace.csv : real propagation RTT per round — from Skyfield

Total NTN HO latency (per round):
    L_total(t) = c_chain(t)  +  prop_rtt(t)
                 ^^^^^^^^^       ^^^^^^^^^^^
               controllable     fixed by physics
               (B3 optimises)   (same for all baselines)

Layout (2 rows):
  Row 0 (left):  Total NTN latency over rounds — all 3 baselines + propagation floor
  Row 0 (right): Stacked breakdown — prop_rtt (shared) vs NF chain contribution
  Row 1 (left):  Cumulative regret with NTN costs vs new c* = c_chain* + mean(prop_rtt)
  Row 1 (right): Propagation RTT trace — shows time-varying satellite geometry

Saves: ntn_latency_exp.pdf
"""

import os
import numpy as np
import matplotlib
import matplotlib.pyplot as plt
import csv

matplotlib.rcParams.update({
    "font.size":       11,
    "axes.labelsize":  12,
    "axes.titlesize":  12,
    "legend.fontsize":  9,
    "axes.spines.top":   False,
    "axes.spines.right": False,
})

LAB = "/home/amirndr/5g-lab"

# Optimal NF chain (known by construction): AMF[0]+SMF[0]+UPF[0] = 3.5ms
C_CHAIN_STAR = 2.0 + 1.0 + 0.5

BASELINES = [
    {"label": "B1 — Fixed Mono-Chain", "file": f"{LAB}/chain_log_b1.csv",
     "color": "#1565C0", "lw": 2.0},
    {"label": "B2 — Random Selection", "file": f"{LAB}/chain_log_b2.csv",
     "color": "#C62828", "lw": 2.0},
    {"label": "B3 — Bregman Online",   "file": f"{LAB}/chain_log_b3.csv",
     "color": "#2E7D32", "lw": 2.2},
]


def load_chain_costs(path):
    if not os.path.exists(path):
        return None
    d = np.loadtxt(path, delimiter=",")
    if d.ndim == 1:
        d = d.reshape(1, -1)
    return d[:, 0] + d[:, 1] + d[:, 2]   # amf + smf + upf


def load_prop_trace(path):
    if not os.path.exists(path):
        print(f"  [ERROR] {path} not found — run ntn_prop_trace.py first.")
        return None
    rtts = []
    ho_events = []
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rtts.append(float(row["prop_rtt_ms"]))
            ho_events.append(int(row["ho_event"]))
    return np.array(rtts), np.array(ho_events)


# ── Load data ─────────────────────────────────────────────────────────────────
prop_result = load_prop_trace(f"{LAB}/ntn_prop_delay_trace.csv")
if prop_result is None:
    exit(1)
prop_rtt, ho_events = prop_result
T = len(prop_rtt)
t_axis = np.arange(1, T + 1)

mean_prop_rtt = float(np.mean(prop_rtt))
C_STAR_NTN    = C_CHAIN_STAR + mean_prop_rtt   # NTN optimal = best chain + mean propagation

# ── Figure ────────────────────────────────────────────────────────────────────
fig, axes = plt.subplots(2, 2, figsize=(14, 10))
fig.suptitle(
    "NTN Handover Latency — Starlink Constellation Trace (h=550km)\n"
    r"$L_{\rm total}(t) = c_{\rm chain}(t)$  [controllable]"
    r"  $+$  $d_{\rm prop}(t)$  [physics, fixed]",
    fontsize=11, fontweight="bold",
)

ax_total   = axes[0, 0]   # total NTN latency per round
ax_stack   = axes[0, 1]   # stacked breakdown
ax_regret  = axes[1, 0]   # cumulative regret (NTN)
ax_prop    = axes[1, 1]   # propagation RTT trace

# ── (0,0): Total NTN latency ──────────────────────────────────────────────────
for bl in BASELINES:
    costs = load_chain_costs(bl["file"])
    if costs is None:
        continue
    n = min(len(costs), T)
    total = costs[:n] + prop_rtt[:n]
    ax_total.plot(t_axis[:n], total, color=bl["color"], lw=bl["lw"],
                  label=bl["label"], alpha=0.85)

# Propagation floor (same for all baselines)
ax_total.fill_between(t_axis, 0, prop_rtt,
                       color="#FFA000", alpha=0.18, label="Propagation RTT floor")
ax_total.axhline(mean_prop_rtt, color="#FFA000", lw=1.0, ls="--", alpha=0.7,
                 label=f"Mean prop RTT = {mean_prop_rtt:.1f}ms")

# Mark satellite handover events
for i, ho in enumerate(ho_events):
    if ho:
        ax_total.axvline(i + 1, color="gray", lw=0.8, ls=":", alpha=0.5)

ax_total.set_title("Total NTN HO Latency  $L_{\\rm total}(t)$", pad=5)
ax_total.set_xlabel("Handover Round  $t$")
ax_total.set_ylabel("Total Latency  (ms)")
ax_total.legend(fontsize=8.5, framealpha=0.9)
ax_total.grid(axis="y", alpha=0.22, lw=0.6)

# ── (0,1): Stacked breakdown — prop vs NF chain ───────────────────────────────
bar_labels   = [bl["label"].split(" — ")[0] for bl in BASELINES]
bar_colors   = [bl["color"] for bl in BASELINES]
mean_chains  = []

for bl in BASELINES:
    costs = load_chain_costs(bl["file"])
    mean_chains.append(float(np.mean(costs[:T])) if costs is not None else 0.0)

x = np.arange(len(BASELINES))
width = 0.5

bars_prop  = ax_stack.bar(x, mean_prop_rtt, width, label="Propagation RTT",
                          color="#FFA000", alpha=0.75)
bars_chain = ax_stack.bar(x, mean_chains, width, bottom=mean_prop_rtt,
                          label="NF Chain Cost  (controllable)",
                          color=bar_colors, alpha=0.85)

for xi, (chain_ms, total_ms) in enumerate(
        zip(mean_chains, [mean_prop_rtt + c for c in mean_chains])):
    ax_stack.text(xi, total_ms + 0.5, f"{total_ms:.1f}ms",
                  ha="center", fontsize=9, fontweight="bold")
    ax_stack.text(xi, mean_prop_rtt + chain_ms / 2,
                  f"NF: {chain_ms:.1f}ms", ha="center", fontsize=8, color="white",
                  fontweight="bold")

ax_stack.axhline(mean_prop_rtt, color="#FFA000", lw=1.0, ls="--", alpha=0.8)
ax_stack.text(len(BASELINES) - 0.1, mean_prop_rtt + 0.3,
              f"prop floor\n{mean_prop_rtt:.1f}ms", fontsize=8, color="#E65100")

ax_stack.set_title("Mean Latency Breakdown  (NF Chain vs Propagation)", pad=5)
ax_stack.set_ylabel("Mean Latency  (ms)")
ax_stack.set_xticks(x)
ax_stack.set_xticklabels(bar_labels, fontsize=10)
ax_stack.legend(fontsize=9, framealpha=0.9)
ax_stack.grid(axis="y", alpha=0.22, lw=0.6)

# ── (1,0): Cumulative regret (NTN) ───────────────────────────────────────────
for bl in BASELINES:
    costs = load_chain_costs(bl["file"])
    if costs is None:
        continue
    n = min(len(costs), T)
    total      = costs[:n] + prop_rtt[:n]
    cum_regret = np.cumsum(total - C_STAR_NTN)
    ax_regret.plot(t_axis[:n], cum_regret,
                   color=bl["color"], lw=bl["lw"], label=bl["label"])
    ax_regret.annotate(f"{cum_regret[-1]:.0f}ms",
                       xy=(n, cum_regret[-1]),
                       xytext=(4, 0), textcoords="offset points",
                       fontsize=9, color=bl["color"], va="center")

# O(√T) reference scaled to B3
costs_b3 = load_chain_costs(f"{LAB}/chain_log_b3.csv")
if costs_b3 is not None:
    n3  = min(len(costs_b3), T)
    R_b3 = float(np.cumsum(costs_b3[:n3] + prop_rtt[:n3] - C_STAR_NTN)[-1])
    t_ref = np.linspace(1, n3, 300)
    sqrt_ref = R_b3 * np.sqrt(t_ref) / np.sqrt(n3)
    ax_regret.plot(t_ref, sqrt_ref, color="#2E7D32", lw=1.1, ls="--", alpha=0.5,
                   label=r"$O(\sqrt{T})$ reference")

ax_regret.axhline(0, color="black", lw=0.8, alpha=0.4)
ax_regret.set_title(
    f"Cumulative NTN Regret  "
    r"$R(T) = \sum_t [L_{\rm total}(t) - c^*_{\rm NTN}]$"
    f"\n$c^*_{{\\rm NTN}}$ = {C_CHAIN_STAR:.1f} + {mean_prop_rtt:.1f} = "
    f"{C_STAR_NTN:.1f}ms",
    pad=5, fontsize=10,
)
ax_regret.set_xlabel("Handover Round  $t$")
ax_regret.set_ylabel("Cumulative Regret  (ms)")
ax_regret.legend(fontsize=8.5, framealpha=0.9)
ax_regret.grid(axis="y", alpha=0.22, lw=0.6)

# ── (1,1): Propagation RTT trace ──────────────────────────────────────────────
ax_prop.plot(t_axis, prop_rtt, color="#FFA000", lw=1.8, label="Prop RTT (2×access+feeder)")
ax_prop.fill_between(t_axis, prop_rtt.min(), prop_rtt,
                     color="#FFA000", alpha=0.18)
ax_prop.axhline(mean_prop_rtt, color="#E65100", lw=1.0, ls="--",
                label=f"Mean = {mean_prop_rtt:.1f}ms")

# Mark satellite handover events on prop trace
ho_marked = False
for i, ho in enumerate(ho_events):
    if ho:
        label = "Satellite HO" if not ho_marked else None
        ax_prop.axvline(i + 1, color="gray", lw=0.9, ls=":", alpha=0.6, label=label)
        ho_marked = True

ax_prop.set_title("Propagation RTT  $d_{\\rm prop}(t)$ — Starlink Constellation Trace",
                  pad=5)
ax_prop.set_xlabel("Handover Round  $t$")
ax_prop.set_ylabel("Prop RTT  (ms)")
ax_prop.legend(fontsize=8.5, framealpha=0.9)
ax_prop.grid(axis="y", alpha=0.22, lw=0.6)

plt.tight_layout()

out = "ntn_latency_exp.pdf"
plt.savefig(out, dpi=300, bbox_inches="tight")
print(f"Saved → {out}")

# ── Summary table ──────────────────────────────────────────────────────────────
print(f"\n  Mean prop RTT        : {mean_prop_rtt:.2f} ms")
print(f"  c* NTN (chain+prop)  : {C_STAR_NTN:.2f} ms\n")
print(f"{'Baseline':<28} {'Mean NF cost':>13} {'Mean total':>12}"
      f" {'Final R(T)':>12} {'Growth'}")
print("-" * 80)
for bl in BASELINES:
    costs = load_chain_costs(bl["file"])
    if costs is None:
        continue
    n           = min(len(costs), T)
    mean_nf     = float(np.mean(costs[:n]))
    mean_total  = mean_nf + mean_prop_rtt
    R_final     = float(np.cumsum(costs[:n] + prop_rtt[:n] - C_STAR_NTN)[-1])
    R_half      = float(np.cumsum((costs[:n//2] + prop_rtt[:n//2] - C_STAR_NTN))[-1])
    ratio       = R_final / R_half if R_half > 0 else 99
    growth      = "O(√T) sublinear" if ratio < 1.65 else "O(T) linear"
    print(f"  {bl['label']:<26} {mean_nf:>11.1f}ms {mean_total:>10.1f}ms"
          f" {R_final:>10.0f}ms  {growth}")

n_ho = int(ho_events.sum())
print(f"\n  Satellite handovers in trace: {n_ho} / {T} rounds")
print(f"  NF chain optimisation (B3 vs B1): "
      f"{float(np.mean(load_chain_costs(f'{LAB}/chain_log_b1.csv')[:T])):.1f}ms → "
      f"{float(np.mean(load_chain_costs(f'{LAB}/chain_log_b3.csv')[:T])):.1f}ms NF cost")
print(f"  B3 reduces controllable component by "
      f"{float(np.mean(load_chain_costs(f'{LAB}/chain_log_b1.csv')[:T])) - float(np.mean(load_chain_costs(f'{LAB}/chain_log_b3.csv')[:T])):.1f}ms/round"
      f" even with {mean_prop_rtt:.1f}ms propagation floor.")
