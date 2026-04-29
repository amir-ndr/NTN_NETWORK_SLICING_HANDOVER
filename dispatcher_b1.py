"""
B1 Dispatcher: fixed mono-chain selection for NTN 5G handover.

Always selects the same AMF, SMF, UPF instance index regardless of their
current load or latency. This is the "no-optimization" baseline: an operator
has provisioned one fixed chain and never adapts it.

Fixed chain: AMF[2] (8ms mean) + SMF[2] (6ms mean) + UPF[2] (3ms mean)
             → 17ms mean chain latency (middle-tier, intentionally suboptimal)

Contrast with:
  B2 (dispatcher.py)    — random selection, high variance
  B3 (dispatcher_b3.py) — Bregman online, converges to best chain (~3.5ms)

Protocol: 4-byte big-endian length prefix + UTF-8 JSON body.

Usage:
    python3 dispatcher_b1.py [--port 9000]
"""

import socket, struct, json, threading, time, argparse
from nf_chain import PolyChain, QueueTracker, AMF_MU_MS, SMF_MU_MS, UPF_MU_MS

HOST = "127.0.0.1"
DEFAULT_PORT = 9000

# ── Fixed chain indices ───────────────────────────────────────────────────────
# AMF[2]=8ms, SMF[2]=6ms, UPF[2]=3ms  →  mean total ≈ 17ms
# (middle tier — not the worst, not the best)
FIXED_AMF = 2
FIXED_SMF = 2
FIXED_UPF = 2


def recv_msg(conn: socket.socket) -> str:
    header = b""
    while len(header) < 4:
        chunk = conn.recv(4 - len(header))
        if not chunk:
            return ""
        header += chunk
    length = struct.unpack(">I", header)[0]
    if length == 0 or length > 1024 * 1024:
        return ""
    body = b""
    while len(body) < length:
        chunk = conn.recv(length - len(body))
        if not chunk:
            return ""
        body += chunk
    return body.decode("utf-8")


def send_msg(conn: socket.socket, msg: str) -> None:
    data = msg.encode("utf-8")
    conn.sendall(struct.pack(">I", len(data)) + data)


def handle_client(conn: socket.socket, addr, chain: PolyChain,
                  stats: dict, lock: threading.Lock,
                  qt_amf: QueueTracker, qt_smf: QueueTracker,
                  qt_upf: QueueTracker) -> None:
    try:
        raw = recv_msg(conn)
        if not raw:
            return

        req = json.loads(raw)
        ue_id = req.get("ueId", -1)
        sst   = req.get("sliceSst", 1)

        # ── Fixed selection — always the same chain (lock protects chain state) ─
        with lock:
            total_ms, amf_ms, smf_ms, upf_ms = chain.process_chain(
                FIXED_AMF, FIXED_SMF, FIXED_UPF
            )
            stats["t"] += 1
            t = stats["t"]

            # Sidecar log: per-NF breakdown for bar plot
            with open("/home/amirndr/5g-lab/chain_log_b1.csv", "a") as f:
                f.write(f"{amf_ms:.3f},{smf_ms:.3f},{upf_ms:.3f}\n")

            # Queue backlog: advance all 3 trackers then snapshot all 15 depths
            # Format: t,amf_idx,smf_idx,upf_idx,amf0..4,smf0..4,upf0..4
            qt_amf.step(FIXED_AMF)
            qt_smf.step(FIXED_SMF)
            qt_upf.step(FIXED_UPF)
            bl_row = ([t, FIXED_AMF, FIXED_SMF, FIXED_UPF]
                      + qt_amf.state()
                      + qt_smf.state()
                      + qt_upf.state())
            with open("/home/amirndr/5g-lab/backlog_log_b1.csv", "a") as f:
                f.write(",".join(f"{v:.4f}" for v in bl_row) + "\n")

        # Simulate chain processing time outside lock so other threads can proceed
        time.sleep(total_ms / 1000.0)

        reply = {
            "status":         "OK",
            "policy":         "fixed",
            "selectedAmf":    "127.0.0.5",
            "selectedAmfIdx": FIXED_AMF,
            "selectedSmfIdx": FIXED_SMF,
            "selectedUpfIdx": FIXED_UPF,
            "chainLatencyMs": round(total_ms, 3),
            "amfLatencyMs":   round(amf_ms, 3),
            "smfLatencyMs":   round(smf_ms, 3),
            "upfLatencyMs":   round(upf_ms, 3),
        }
        send_msg(conn, json.dumps(reply))

        print(f"  [t={t:3d}] ue={ue_id} "
              f"chain=AMF[{FIXED_AMF}]+SMF[{FIXED_SMF}]+UPF[{FIXED_UPF}]  "
              f"total={total_ms:.1f}ms "
              f"(amf={amf_ms:.1f} smf={smf_ms:.1f} upf={upf_ms:.1f})",
              flush=True)

    except Exception as e:
        print(f"  [ERR] {e}", flush=True)
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = parser.parse_args()

    chain  = PolyChain()
    stats  = {"t": 0}
    lock   = threading.Lock()
    qt_amf = QueueTracker(AMF_MU_MS)
    qt_smf = QueueTracker(SMF_MU_MS)
    qt_upf = QueueTracker(UPF_MU_MS)

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((HOST, args.port))
    server.listen(64)

    print(f"Dispatcher [FIXED/B1] listening on {HOST}:{args.port}")
    print(f"  Fixed chain: AMF[{FIXED_AMF}] ({chain.amf[FIXED_AMF].mu_ms}ms mean)"
          f" + SMF[{FIXED_SMF}] ({chain.smf[FIXED_SMF].mu_ms}ms mean)"
          f" + UPF[{FIXED_UPF}] ({chain.upf[FIXED_UPF].mu_ms}ms mean)")
    print(f"  Expected chain latency: ~{chain.amf[FIXED_AMF].mu_ms + chain.smf[FIXED_SMF].mu_ms + chain.upf[FIXED_UPF].mu_ms:.1f}ms mean")
    print(f"  Optimal would be AMF[0]+SMF[0]+UPF[0] = "
          f"{chain.amf[0].mu_ms + chain.smf[0].mu_ms + chain.upf[0].mu_ms:.1f}ms mean")
    print()

    while True:
        conn, addr = server.accept()
        threading.Thread(
            target=handle_client,
            args=(conn, addr, chain, stats, lock, qt_amf, qt_smf, qt_upf),
            daemon=True,
        ).start()


if __name__ == "__main__":
    main()
