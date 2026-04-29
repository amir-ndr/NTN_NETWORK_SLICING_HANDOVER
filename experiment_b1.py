#!/usr/bin/env python3
"""
B1 experiment: fixed mono-chain dispatcher. Runs N Xn handovers,
writes latencies to xn_ho_latency_b1.csv.

All three baselines (B1/B2/B3) use the same dispatcher framework so the
comparison is fair. B1 always picks AMF[2]+SMF[2]+UPF[2] (fixed, middle-tier).

Prerequisites — run in separate terminals BEFORE this script:
  sudo ./build/nr-gnb -c config/gnb1.yaml
  sudo ./build/nr-gnb -c config/gnb2_b1.yaml   ← dispatcher-enabled config
  python3 dispatcher_b1.py                       ← B1 fixed mono-chain dispatcher

Run:
  sudo python3 experiment_b1.py [N]   (default N=50)
"""

import subprocess, time, sys, os, shutil, threading, queue, re

if os.geteuid() != 0:
    sys.exit("Run with sudo: sudo python3 experiment_b1.py [N]")

UERANSIM   = os.path.dirname(os.path.abspath(__file__)) + "/UERANSIM"
GNB1_NAME  = "UERANSIM-gnb-999-70-1"
N          = int(sys.argv[1]) if len(sys.argv) > 1 else 50
CSV_LIVE   = "/home/amirndr/5g-lab/xn_ho_latency.csv"
CSV_OUT    = "/home/amirndr/5g-lab/xn_ho_latency_b1.csv"

open(CSV_LIVE, "w").close()
open("/home/amirndr/5g-lab/chain_log_b1.csv", "w").close()
open("/home/amirndr/5g-lab/backlog_log_b1.csv", "w").close()

def drain_stdout(proc, q):
    """Read all stdout lines into a queue; put None on EOF."""
    for line in iter(proc.stdout.readline, ""):
        q.put(line)
    q.put(None)

def wait_for_line(proc, keyword, timeout_s):
    """Return True if keyword appears in proc stdout within timeout_s seconds."""
    q = queue.Queue()
    t = threading.Thread(target=drain_stdout, args=(proc, q), daemon=True)
    t.start()
    deadline = time.time() + timeout_s
    while True:
        remaining = deadline - time.time()
        if remaining <= 0:
            return False
        try:
            line = q.get(timeout=remaining)
        except queue.Empty:
            return False
        if line is None:          # EOF — process exited
            return False
        if keyword in line:
            return True

def get_ue_id(retries=5, delay=0.4):
    """Query gnb1's ue-list and return the first ue-id, or None."""
    for _ in range(retries):
        r = subprocess.run(
            [f"{UERANSIM}/build/nr-cli", GNB1_NAME, "--exec", "ue-list"],
            capture_output=True, text=True, timeout=5,
        )
        m = re.search(r"ue-id:\s*(\d+)", r.stdout)
        if m:
            return int(m.group(1))
        time.sleep(delay)
    return None

def csv_row_count():
    """Count non-empty rows in the CSV."""
    try:
        with open(CSV_LIVE) as f:
            return sum(1 for line in f if line.strip())
    except FileNotFoundError:
        return 0

ok = 0
failed = 0

for i in range(N):
    print(f"[{i+1:3d}/{N}] Starting UE...", end=" ", flush=True)

    rows_before = csv_row_count()

    ue = subprocess.Popen(
        [f"{UERANSIM}/build/nr-ue", "-c", f"{UERANSIM}/config/ue1.yaml"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )

    registered = wait_for_line(ue, "PDU Session establishment is successful", timeout_s=15)

    if not registered:
        print("FAILED (registration timeout)")
        ue.terminate()
        ue.wait()
        failed += 1
        time.sleep(3)
        continue

    # Get the actual UE context ID assigned by gnb1 (increments each run)
    ue_id = get_ue_id()
    if ue_id is None:
        print("FAILED (could not find UE in gnb1 ue-list)")
        ue.terminate()
        ue.wait()
        failed += 1
        time.sleep(3)
        continue

    print(f"registered (ue-id={ue_id}). Triggering HO...", end=" ", flush=True)
    time.sleep(0.3)  # brief settle

    subprocess.run(
        [f"{UERANSIM}/build/nr-cli", GNB1_NAME,
         "--exec", f"xn-handover {ue_id} 127.0.0.2 38422 1"],
        capture_output=True, text=True,
    )

    # B1 dispatcher adds ~17ms chain latency; give enough time for HO + CSV write
    time.sleep(4)

    ue.terminate()
    ue.wait()

    # Verify the handover actually produced a CSV row
    if csv_row_count() <= rows_before:
        print("FAILED (no CSV row written — handover did not complete in C++)")
        failed += 1
        time.sleep(6)
        continue

    ok += 1
    print(f"done  ({ok} collected so far)")

    # Wait for the 5s block window to expire + AMF/gnb2 context cleanup
    time.sleep(6)

shutil.copy(CSV_LIVE, CSV_OUT)

print(f"\nFinished: {ok} successful, {failed} failed.")
print(f"Results → {CSV_OUT}")
