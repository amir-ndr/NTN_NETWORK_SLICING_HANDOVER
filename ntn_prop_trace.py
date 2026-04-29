#!/usr/bin/env python3
"""
NTN Propagation Delay Trace Generator — Starlink Orbital Mechanics.

Two modes:
  1. REAL mode  : loads live Starlink TLEs from a local .tle file (use if you
                  have downloaded 'starlink.tle' from CelesTrak manually).
  2. SYNTHETIC mode (default): models LEO constellation geometry using real
                  Starlink orbital parameters (altitude, inclination, period).
                  Produces realistic, time-varying d(t) traces without network
                  access. Used by Phandover-style papers when trace files are
                  pre-computed from offline constellation data [24][25].

Orbital model (Starlink shell 1, Group 1):
  - Altitude  : h = 550 km
  - Inclination: 53°  (covers most mid-latitudes)
  - Min elevation threshold: 25° (Starlink service spec)
  - Speed of light: c = 299.792 km/ms
  - Ground station feeder link modelled separately (nearest GS geometry)

Propagation model:
  d_access(t) = slant_range(el(t)) / c     [one-way, ms]
  d_feeder(t) = slant_range_feeder(el(t)) / c  [one-way, ms]
  prop_rtt(t) = 2 × (d_access + d_feeder)  [full round-trip, ms]

Output: ntn_prop_delay_trace.csv
  Columns: round, time_s, sat_id, elevation_deg,
           d_access_ms, d_feeder_ms, prop_rtt_ms, ho_event

Usage:
    python3 ntn_prop_trace.py [--rounds 50] [--interval 10] [--tle starlink.tle]
"""

import argparse
import csv
import math
import os
import numpy as np

# ── Physical constants ────────────────────────────────────────────────────────
R_E        = 6371.0    # Earth radius (km)
C_KM_MS    = 299.792   # Speed of light (km/ms)
GM         = 3.986e5   # Gravitational parameter (km³/s²)

# ── Starlink shell 1 parameters ───────────────────────────────────────────────
H_KM          = 550.0        # orbital altitude (km)
R_SAT         = R_E + H_KM   # orbital radius (km)
INCL_DEG      = 53.0         # inclination
ELEV_MIN_DEG  = 25.0         # min service elevation (Starlink spec)

# Orbital period (s)
T_ORBIT_S = 2 * math.pi * math.sqrt(R_SAT**3 / GM)   # ≈ 5828s ≈ 97.1 min

# ── Ground station (nearest Starlink gateway to rural Montana UE) ─────────────
# Cheyenne WY — closest major Starlink gateway to the simulated UE
GS_OFFSET_KM = 650.0    # approximate UE-to-GS horizontal distance (km)
# At GS_OFFSET_KM separation and satellite at altitude H_KM,
# feeder link slant range is computed geometrically per round.

OUT_CSV = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "ntn_prop_delay_trace.csv")


# ── Geometry helpers ──────────────────────────────────────────────────────────

def slant_range_km(el_deg: float) -> float:
    """One-way slant range from UE to satellite (km) at elevation angle el_deg.

    Derived from the triangle (Earth centre, UE, satellite):
      R_sat² = R_E² + r² + 2·R_E·r·sin(el)
    Solving for r (slant range) gives the standard formula.
    """
    el = math.radians(el_deg)
    # r = sqrt(R_sat² - R_E²·cos²(el)) - R_E·sin(el)
    return math.sqrt(R_SAT**2 - (R_E * math.cos(el))**2) - R_E * math.sin(el)


def feeder_slant_km(el_deg: float, gs_offset_km: float = GS_OFFSET_KM) -> float:
    """Approximate feeder link slant range (satellite ↔ ground station, km).

    The ground station is gs_offset_km away from the UE on the ground.
    We compute the satellite's slant range as seen from the GS by treating
    the GS-UE-satellite geometry with the satellite at elevation el_deg over
    the UE (conservative approximation; actual GS elevation to sat is similar).
    """
    # Satellite position in 2-D (UE at origin, altitude H_KM):
    # At el_deg over UE: sat_x = r·cos(el), sat_y = H_KM
    r = slant_range_km(el_deg)
    el = math.radians(el_deg)
    sat_x = r * math.cos(el)   # horizontal distance from UE to sat ground track
    sat_y = H_KM               # altitude

    # GS is gs_offset_km from UE on the ground
    dx = sat_x - gs_offset_km
    dist = math.sqrt(dx**2 + sat_y**2)
    return dist


def elevation_during_pass(t_s: float, t_rise: float, t_set: float,
                           el_max_deg: float) -> float:
    """Elevation angle (degrees) at time t_s during a satellite pass.

    Uses a sinusoidal profile: el = el_max × sin(π × (t - t_rise) / T_pass)
    This matches the true shape for a straight overhead pass and is a good
    approximation for off-centre passes with the correct el_max.
    """
    if t_s < t_rise or t_s > t_set:
        return 0.0
    T_pass = t_set - t_rise
    phase  = math.pi * (t_s - t_rise) / T_pass
    return el_max_deg * math.sin(phase)


# ── Satellite pass schedule ───────────────────────────────────────────────────

def generate_pass_schedule(n_rounds: int, interval_s: int,
                            rng: np.random.Generator):
    """Generate a sequence of realistic Starlink satellite passes.

    In a dense LEO constellation (Starlink has >6000 sats), a new satellite
    becomes usable before the previous one sets — the UE always sees at least
    one satellite above 25°. We model the handover chain:
      pass 1 → pass 2 → pass 3 → …

    Each pass has:
      - random peak elevation drawn from uniform [35°, 80°] (skips very low
        and directly overhead passes, which are less common for a given UE)
      - pass duration derived from orbital mechanics + elevation geometry
      - inter-pass gap: 0s (dense constellation assumption — no outage)
    """
    passes = []
    t_cursor = 0.0
    needed_s = n_rounds * interval_s + 60   # slight buffer

    while t_cursor < needed_s:
        el_max = rng.uniform(35.0, 78.0)    # peak elevation (°)

        # True half-angle from nadir at el_max:
        # cos(nadir_half) = R_E / R_sat × cos(el_max)  [Earth-centre angle]
        nadir_half_rad = math.acos(
            max(-1, min(1, (R_E / R_SAT) * math.cos(math.radians(el_max))))
        )
        # At threshold el_min, the corresponding nadir half-angle:
        nadir_min_rad = math.acos(
            max(-1, min(1, (R_E / R_SAT) * math.cos(math.radians(ELEV_MIN_DEG))))
        )
        # Angular duration of visible arc (Earth-centred) for THIS pass:
        arc_rad = 2.0 * (nadir_min_rad - math.acos(
            max(-1, min(1, (R_E / R_SAT) * math.cos(math.radians(el_max))))
        ))
        # Convert arc to time (fraction of orbital period)
        T_pass_s = (arc_rad / (2 * math.pi)) * T_ORBIT_S
        # Ensure minimum pass length
        T_pass_s = max(T_pass_s, 200.0)

        t_rise = t_cursor
        t_set  = t_cursor + T_pass_s

        # Assign a satellite ID (unique per pass)
        sat_id = len(passes) + 1

        passes.append({
            "sat_id":    sat_id,
            "el_max":    el_max,
            "t_rise":    t_rise,
            "t_set":     t_set,
            "T_pass_s":  T_pass_s,
        })

        # Next satellite rises before this one sets (overlap = 20-60s)
        overlap_s  = rng.uniform(20.0, 60.0)
        t_cursor   = t_set - overlap_s   # next sat starts serving before HO

    return passes


def serving_satellite(t_s: float, passes: list):
    """Return the highest-elevation satellite at time t_s."""
    best_pass = None
    best_el   = ELEV_MIN_DEG - 1.0

    for p in passes:
        el = elevation_during_pass(t_s, p["t_rise"], p["t_set"], p["el_max"])
        if el >= ELEV_MIN_DEG and el > best_el:
            best_el   = el
            best_pass = p

    return best_pass, best_el


# ── Real TLE mode (requires local starlink.tle) ───────────────────────────────

def try_real_tle_mode(n_rounds, interval_s, tle_path):
    """Attempt to use real Skyfield TLEs. Returns rows list or None."""
    try:
        from skyfield.api import load, wgs84
    except ImportError:
        return None

    if not os.path.exists(tle_path):
        return None

    print(f"  [REAL TLE] Loading {tle_path}...")
    ts         = load.timescale()
    satellites = load.tle_file(tle_path)
    if not satellites:
        return None

    print(f"  Loaded {len(satellites)} satellites.")

    UE_LAT, UE_LON, UE_ALT = 46.8797, -110.3626, 1000.0
    GS_LAT, GS_LON          = 41.140, -104.820    # Cheyenne WY gateway

    ue_pos = wgs84.latlon(UE_LAT, UE_LON, elevation_m=UE_ALT)
    gs_pos = wgs84.latlon(GS_LAT, GS_LON)

    t_start = ts.now()
    rows    = []
    prev_name = None
    n_ho   = 0
    collected, step_s = 0, 0

    while collected < n_rounds:
        t = ts.tt_jd(t_start.tt + step_s / 86400.0)
        step_s += interval_s

        best_sat = None; best_el = -90.0; best_dist = None
        for sat in satellites:
            topo = (sat - ue_pos).at(t)
            alt, _, dist = topo.altaz()
            if alt.degrees > ELEV_MIN_DEG and alt.degrees > best_el:
                best_el = alt.degrees; best_sat = sat; best_dist = dist.km

        if best_sat is None:
            continue

        gs_topo = (best_sat - gs_pos).at(t)
        _, _, gs_dist = gs_topo.altaz()

        d_access = best_dist / C_KM_MS
        d_feeder = gs_dist.km  / C_KM_MS
        prop_rtt = 2.0 * (d_access + d_feeder)

        ho = 0
        if prev_name and best_sat.name != prev_name:
            ho = 1; n_ho += 1
        prev_name = best_sat.name
        collected += 1

        rows.append({
            "round": collected,
            "time_s": step_s - interval_s,
            "sat_id": best_sat.name,
            "elevation_deg": round(best_el, 2),
            "d_access_ms":   round(d_access, 3),
            "d_feeder_ms":   round(d_feeder, 3),
            "prop_rtt_ms":   round(prop_rtt, 3),
            "ho_event":      ho,
        })

    print(f"  [REAL TLE] Generated {n_rounds} rounds, {n_ho} satellite HOs.")
    return rows


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--rounds",   type=int, default=100)
    parser.add_argument("--interval", type=int, default=10,
                        help="Seconds between HO rounds (default 10)")
    parser.add_argument("--tle", default="starlink.tle",
                        help="Path to local Starlink TLE file (optional)")
    parser.add_argument("--seed", type=int, default=42,
                        help="RNG seed for synthetic mode (default 42)")
    args = parser.parse_args()

    N_ROUNDS      = args.rounds
    INTERVAL_S    = args.interval
    tle_path      = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                 args.tle)

    print("NTN Propagation Delay Trace Generator")
    print(f"  Starlink shell 1: h={H_KM}km, incl={INCL_DEG}°, T_orbit={T_ORBIT_S/60:.1f}min")
    print(f"  Elevation threshold: {ELEV_MIN_DEG}°")
    print(f"  Rounds: {N_ROUNDS}  |  Interval: {INTERVAL_S}s")
    print()

    # ── Try real TLE mode first ───────────────────────────────────────────────
    rows = try_real_tle_mode(N_ROUNDS, INTERVAL_S, tle_path)

    if rows is None:
        # ── Synthetic mode ────────────────────────────────────────────────────
        print("  [SYNTHETIC] Using Starlink orbital mechanics (no TLE file found).")
        print(f"  Seed: {args.seed}  |  slant range model: ITU-R P.619")
        print()

        rng     = np.random.default_rng(args.seed)
        passes  = generate_pass_schedule(N_ROUNDS, INTERVAL_S, rng)

        rows       = []
        prev_sat   = None
        n_ho       = 0

        print(f"  {'Round':>5}  {'Sat':>4}  {'Elev°':>6}  "
              f"{'d_access':>10}  {'d_feeder':>10}  {'RTT':>8}  HO?")
        print("  " + "─" * 65)

        for rd in range(1, N_ROUNDS + 1):
            t_s = (rd - 1) * INTERVAL_S

            p, el = serving_satellite(t_s, passes)
            if p is None:
                el = ELEV_MIN_DEG   # edge case: use minimum (should not happen)
                p  = passes[0]

            d_access = slant_range_km(el)  / C_KM_MS
            d_feeder = feeder_slant_km(el) / C_KM_MS
            prop_rtt = 2.0 * (d_access + d_feeder)

            ho = 0
            if prev_sat is not None and p["sat_id"] != prev_sat:
                ho = 1; n_ho += 1
            prev_sat = p["sat_id"]

            rows.append({
                "round":        rd,
                "time_s":       t_s,
                "sat_id":       f"STARLINK-S1-{p['sat_id']:04d}",
                "elevation_deg": round(el, 2),
                "d_access_ms":   round(d_access, 3),
                "d_feeder_ms":   round(d_feeder, 3),
                "prop_rtt_ms":   round(prop_rtt, 3),
                "ho_event":      ho,
            })

            ho_tag = "  <-- HO" if ho else ""
            print(f"  {rd:>5}  {p['sat_id']:>4}  {el:>6.1f}°  "
                  f"{d_access:>8.2f}ms  {d_feeder:>8.2f}ms  "
                  f"{prop_rtt:>6.2f}ms{ho_tag}")

        print(f"\n  Satellite HOs: {n_ho} within {N_ROUNDS} rounds")

    # ── Write CSV ─────────────────────────────────────────────────────────────
    fields = ["round", "time_s", "sat_id", "elevation_deg",
              "d_access_ms", "d_feeder_ms", "prop_rtt_ms", "ho_event"]

    with open(OUT_CSV, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)

    print(f"\n  Saved → {OUT_CSV}")

    # ── Summary ───────────────────────────────────────────────────────────────
    rtts     = [r["prop_rtt_ms"]  for r in rows]
    accesses = [r["d_access_ms"]  for r in rows]
    feeders  = [r["d_feeder_ms"]  for r in rows]

    print(f"\n{'─'*58}")
    print(f"  NTN Propagation Summary  ({N_ROUNDS} rounds, Starlink h={H_KM}km)")
    print(f"{'─'*58}")
    print(f"  d_access one-way : "
          f"min={min(accesses):.2f}ms  max={max(accesses):.2f}ms  "
          f"mean={np.mean(accesses):.2f}ms")
    print(f"  d_feeder one-way : "
          f"min={min(feeders):.2f}ms  max={max(feeders):.2f}ms  "
          f"mean={np.mean(feeders):.2f}ms")
    print(f"  prop_rtt (total) : "
          f"min={min(rtts):.2f}ms  max={max(rtts):.2f}ms  "
          f"mean={np.mean(rtts):.2f}ms")
    print(f"{'─'*58}")
    print()
    print("  To use real Starlink TLEs instead:")
    print("  1. Download from CelesTrak (browser):")
    print("     https://celestrak.org/NORAD/elements/gp.php?GROUP=starlink&FORMAT=tle")
    print(f"  2. Save as: {tle_path}")
    print("  3. Re-run: python3 ntn_prop_trace.py")


if __name__ == "__main__":
    main()
