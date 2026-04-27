#!/usr/bin/env python3
"""
5G Handover Monitor — file trigger + active reattachment verification
Touch /tmp/degrade_signal to trigger handover.
File is auto-removed after handover fires.
"""
import subprocess, time, re, sys, logging, os
from dataclasses import dataclass
from typing import Optional

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s",
                    datefmt="%H:%M:%S")
log = logging.getLogger("ho-monitor")

@dataclass
class Config:
    gnb1_name: str = "UERANSIM-gnb-999-70-1"
    gnb2_name: str = "UERANSIM-gnb-999-70-2"
    nr_cli:    str = "./build/nr-cli"

    bad_readings_needed: int   = 2
    poll_interval_sec:   float = 5.0
    cooldown_sec:        float = 5.0
    reattach_timeout:    int   = 12    # × 5s = 60s max wait

    trigger_file: str = "/tmp/degrade_signal"

cfg = Config()

class State:
    bad_count = 0
    ho_count  = 0

state = State()

def run(cmd, timeout=10):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout, r.stderr
    except subprocess.TimeoutExpired:
        return -1, "", "timeout"
    except FileNotFoundError as e:
        return -1, "", str(e)

def find_serving_gnb() -> Optional[tuple]:
    for gnb in [cfg.gnb1_name, cfg.gnb2_name]:
        rc, out, _ = run([cfg.nr_cli, gnb, "--exec", "ue-list"])
        if rc == 0 and out.strip():
            ids = re.findall(r'\d+', out)
            if ids:
                ue_id = ids[0]
                target = cfg.gnb2_name if gnb == cfg.gnb1_name else cfg.gnb1_name
                return gnb, target, ue_id
    return None

def measure_quality() -> tuple:
    if os.path.exists(cfg.trigger_file):
        return 9999.0, 100.0
    return 0.1, 0.0

def trigger_handover(serving: str, target: str, ue_id: str) -> bool:
    log.info(f"Releasing UE[{ue_id}] from {serving}")
    rc, out, err = run([cfg.nr_cli, serving,
                        "--exec", f"ue-release {ue_id}"], timeout=15)
    if rc != 0:
        log.error(f"Release failed: {err.strip()}")
        return False

    log.info("UE released — removing trigger file")
    if os.path.exists(cfg.trigger_file):
        os.remove(cfg.trigger_file)

    log.info(f"Waiting for UE to reattach to {target}...")
    for attempt in range(cfg.reattach_timeout):
        time.sleep(5)
        rc2, out2, _ = run([cfg.nr_cli, target, "--exec", "ue-list"])
        if rc2 == 0 and out2.strip():
            log.info(f"✓ UE confirmed on {target} after {(attempt+1)*5}s")
            return True
        log.info(f"  Still waiting... ({(attempt+1)*5}s)")

    log.error(f"UE did not reattach to {target} within {cfg.reattach_timeout*5}s")
    return False

def main():
    log.info("=== Handover Monitor started ===")
    log.info(f"gNB1={cfg.gnb1_name}  gNB2={cfg.gnb2_name}")
    log.info("Trigger handover:  touch /tmp/degrade_signal")
    log.info("File auto-removed after handover fires")

    while True:
        serving_info = find_serving_gnb()
        if serving_info is None:
            log.warning("UE not found on any gNB — waiting...")
            time.sleep(cfg.poll_interval_sec)
            continue

        serving, target, ue_id = serving_info
        avg_rtt, loss = measure_quality()
        bad = avg_rtt > 100.0 or loss > 40.0

        if bad:
            state.bad_count += 1
            log.warning(f"[BAD {state.bad_count}/{cfg.bad_readings_needed}] "
                        f"serving={serving}")
            if state.bad_count >= cfg.bad_readings_needed:
                if trigger_handover(serving, target, ue_id):
                    state.ho_count += 1
                    state.bad_count = 0
                    log.info(f"Handover #{state.ho_count} complete. "
                             f"Cooling down {cfg.cooldown_sec}s...")
                    time.sleep(cfg.cooldown_sec)
                else:
                    state.bad_count = 0
        else:
            if state.bad_count > 0:
                log.info(f"Signal restored  serving={serving}")
            else:
                log.info(f"[OK] serving={serving}")
            state.bad_count = 0

        time.sleep(cfg.poll_interval_sec)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log.info(f"\nStopped. Total handovers: {state.ho_count}")
        sys.exit(0)