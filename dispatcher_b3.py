"""
B3 Dispatcher: Bregman online poly-chain selection for NTN 5G handover.

Implements Algorithm 1 from the paper:
  - Exploration: multiplicative-weight update (Bregman / EXP3) at each layer
  - Cost relay:  L_UPF → L_SMF = smf + L_UPF → L_AMF = amf + L_SMF (Eq. 2)
  - Each layer's selector updates on its subtree cost (end-to-end feedback)

Chain structure:
  Dispatcher → AMF[i] (Slice 1, 5 instances)
             → SMF[j] (Slice 2, 5 instances)
             → UPF[k] (Slice 3, 5 instances)

Protocol: 4-byte big-endian length prefix + UTF-8 JSON body.

Usage:
    python3 dispatcher_b3.py [--port 9000] [--eta 0.1]
"""

import socket, struct, json, threading, time, sys, argparse
from nf_chain import PolyChain, BregmanPolyChain, QueueTracker, N_INSTANCES, AMF_MU_MS, SMF_MU_MS, UPF_MU_MS

HOST = "127.0.0.1"
DEFAULT_PORT = 9000


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


def handle_client(conn: socket.socket, addr, bregman: BregmanPolyChain,
                  lock: threading.Lock, stats: dict,
                  qt_amf: QueueTracker, qt_smf: QueueTracker,
                  qt_upf: QueueTracker) -> None:
    try:
        raw = recv_msg(conn)
        if not raw:
            return

        req = json.loads(raw)
        ue_id = req.get("ueId", -1)
        sst   = req.get("sliceSst", 1)

        # ── Bregman select + process + update (thread-safe) ──────────────────
        with lock:
            (total_ms, amf_ms, smf_ms, upf_ms,
             amf_idx, smf_idx, upf_idx) = bregman.select_and_process()

            stats["t"] += 1
            t = stats["t"]
            # Snapshot current selection probabilities for logging
            p_amf = bregman.disp_selector.probabilities()
            p_smf = bregman.amf_selector.probabilities()
            p_upf = bregman.smf_selector.probabilities()

            # Sidecar log: per-NF breakdown for bar plot
            with open("/home/amirndr/5g-lab/chain_log_b3.csv", "a") as f:
                f.write(f"{amf_ms:.3f},{smf_ms:.3f},{upf_ms:.3f}\n")

            # Queue backlog: advance all 3 trackers then snapshot all 15 depths
            # Format: t,amf_idx,smf_idx,upf_idx,amf0..4,smf0..4,upf0..4
            qt_amf.step(amf_idx)
            qt_smf.step(smf_idx)
            qt_upf.step(upf_idx)
            bl_row = ([t, amf_idx, smf_idx, upf_idx]
                      + qt_amf.state()
                      + qt_smf.state()
                      + qt_upf.state())
            with open("/home/amirndr/5g-lab/backlog_log_b3.csv", "a") as f:
                f.write(",".join(f"{v:.4f}" for v in bl_row) + "\n")

        # Simulate the actual chain processing delay so gnb2's pswMs reflects it
        time.sleep(total_ms / 1000.0)

        reply = {
            "status":         "OK",
            "policy":         "bregman",
            "selectedAmf":    "127.0.0.5",
            "selectedAmfIdx": amf_idx,
            "selectedSmfIdx": smf_idx,
            "selectedUpfIdx": upf_idx,
            "chainLatencyMs": round(total_ms, 3),
            "amfLatencyMs":   round(amf_ms, 3),
            "smfLatencyMs":   round(smf_ms, 3),
            "upfLatencyMs":   round(upf_ms, 3),
        }
        send_msg(conn, json.dumps(reply))

        # ── Console log ───────────────────────────────────────────────────────
        top_amf = p_amf.index(max(p_amf))
        top_smf = p_smf.index(max(p_smf))
        top_upf = p_upf.index(max(p_upf))
        print(f"  [t={t:3d}] ue={ue_id} "
              f"chain=AMF[{amf_idx}]+SMF[{smf_idx}]+UPF[{upf_idx}] "
              f"total={total_ms:.1f}ms "
              f"| top: AMF[{top_amf}]({p_amf[top_amf]:.2f}) "
              f"SMF[{top_smf}]({p_smf[top_smf]:.2f}) "
              f"UPF[{top_upf}]({p_upf[top_upf]:.2f})",
              flush=True)

    except Exception as e:
        print(f"  [ERR] {e}", flush=True)
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--eta",  type=float, default=0.1,
                        help="Bregman learning rate (default 0.1)")
    args = parser.parse_args()

    chain   = PolyChain()
    bregman = BregmanPolyChain(chain, eta=args.eta)
    lock    = threading.Lock()
    stats   = {"t": 0}
    qt_amf  = QueueTracker(AMF_MU_MS)
    qt_smf  = QueueTracker(SMF_MU_MS)
    qt_upf  = QueueTracker(UPF_MU_MS)

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((HOST, args.port))
    server.listen(64)

    print(f"Dispatcher [BREGMAN/B3] listening on {HOST}:{args.port}  eta={args.eta}")
    print(f"  Slice 1 — AMF × {N_INSTANCES}: "
          f"mean latencies {[inst.mu_ms for inst in chain.amf]} ms")
    print(f"  Slice 2 — SMF × {N_INSTANCES}: "
          f"mean latencies {[inst.mu_ms for inst in chain.smf]} ms")
    print(f"  Slice 3 — UPF × {N_INSTANCES}: "
          f"mean latencies {[inst.mu_ms for inst in chain.upf]} ms")
    print(f"  Optimal chain: AMF[0]+SMF[0]+UPF[0] = "
          f"{chain.amf[0].mu_ms+chain.smf[0].mu_ms+chain.upf[0].mu_ms:.1f}ms mean")
    print()

    while True:
        conn, addr = server.accept()
        threading.Thread(
            target=handle_client,
            args=(conn, addr, bregman, lock, stats, qt_amf, qt_smf, qt_upf),
            daemon=True,
        ).start()


if __name__ == "__main__":
    main()
