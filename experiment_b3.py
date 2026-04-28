#!/usr/bin/env python3
"""
B3 experiment: Bregman online poly-chain dispatcher. Runs N Xn handovers,
writes latencies to xn_ho_latency_b3.csv.

Prerequisites — run in separate terminals BEFORE this script:
  sudo ./build/nr-gnb -c config/gnb1.yaml
  sudo ./build/nr-gnb -c config/gnb2_b3.yaml    ← same as B2 (dispatcher enabled)
  python3 dispatcher_b3.py                        ← B3 Bregman dispatcher

Run:
  sudo python3 experiment_b3.py [N]   (default N=50)
"""

import subprocess, time, sys, os, shutil, threading, queue, re

if os.geteuid() != 0:
    sys.exit("Run with sudo: sudo python3 experiment_b3.py [N]")

UERANSIM   = os.path.dirname(os.path.abspath(__file__)) + "/UERANSIM"
GNB1_NAME  = "UERANSIM-gnb-999-70-1"
N          = int(sys.argv[1]) if len(sys.argv) > 1 else 50
CSV_LIVE   = "/home/amirndr/5g-lab/xn_ho_latency.csv"
CSV_OUT    = "/home/amirndr/5g-lab/xn_ho_latency_b3.csv"

open(CSV_LIVE, "w").close()


def drain_stdout(proc, q):
    for line in iter(proc.stdout.readline, ""):
        q.put(line)
    q.put(None)


def wait_for_line(proc, keyword, timeout_s):
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
        if line is None:
            return False
        if keyword in line:
            return True


def get_ue_id(retries=5, delay=0.4):
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
        ue.terminate(); ue.wait()
        failed += 1
        time.sleep(3)
        continue

    ue_id = get_ue_id()
    if ue_id is None:
        print("FAILED (could not find UE in gnb1 ue-list)")
        ue.terminate(); ue.wait()
        failed += 1
        time.sleep(3)
        continue

    print(f"registered (ue-id={ue_id}). Triggering HO...", end=" ", flush=True)
    time.sleep(0.3)

    subprocess.run(
        [f"{UERANSIM}/build/nr-cli", GNB1_NAME,
         "--exec", f"xn-handover {ue_id} 127.0.0.2 38422 1"],
        capture_output=True, text=True,
    )

    # B3: Bregman dispatcher adds chain latency (should converge to fast chain)
    time.sleep(4)

    ue.terminate(); ue.wait()

    if csv_row_count() <= rows_before:
        print("FAILED (no CSV row — handover did not complete in C++)")
        failed += 1
        time.sleep(6)
        continue

    ok += 1
    print(f"done  ({ok} collected so far)")
    time.sleep(6)

shutil.copy(CSV_LIVE, CSV_OUT)

print(f"\nFinished: {ok} successful, {failed} failed.")
print(f"Results → {CSV_OUT}")
