"""
B2 Dispatcher: random poly-chain selection for NTN 5G handover.

Architecture:
    gnb2 (XnTask) → this server → PolyChain (AMF/SMF/UPF selection) → reply to gnb2

Protocol: 4-byte big-endian length prefix + UTF-8 JSON body.
This matches the wire format in UERANSIM/src/gnb/xn/task.cpp ContactDispatcher().

Chain:  Dispatcher → selects AMF[i] from Slice 1 (5 AMF instances)
                   → selects SMF[j] from Slice 2 (5 SMF instances)
                   → selects UPF[k] from Slice 3 (5 UPF instances)

For B2 (this file): all selections are uniform random.
The dispatcher sleeps for the simulated chain processing time so that gnb2's
measured pswLatencyMs accurately reflects the chain's contribution to HO latency.

Usage:
    python3 dispatcher.py [--port 9000]
"""

import socket, struct, json, threading, time, sys, argparse
from nf_chain import PolyChain, QueueTracker, AMF_MU_MS, SMF_MU_MS, UPF_MU_MS

HOST = "127.0.0.1"
DEFAULT_PORT = 9000
POLICY = "random"   # B2


def recv_msg(conn: socket.socket) -> str:
    """Receive one length-prefixed JSON message."""
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
    """Send one length-prefixed JSON message."""
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
        sst      = req.get("sliceSst", 1)
        ue_id    = req.get("ueId", -1)
        req_type = req.get("type", "")

        # ── Select + process (lock protects chain state and stats counter) ────
        with lock:
            if POLICY == "random":
                amf_idx, smf_idx, upf_idx = chain.random_select()
            else:
                raise ValueError(f"Unknown policy: {POLICY}")

            total_ms, amf_ms, smf_ms, upf_ms = chain.process_chain(
                amf_idx, smf_idx, upf_idx
            )
            stats["t"] += 1
            t = stats["t"]

            # Sidecar log: per-NF breakdown for bar plot
            with open("/home/amirndr/5g-lab/chain_log_b2.csv", "a") as f:
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
            with open("/home/amirndr/5g-lab/backlog_log_b2.csv", "a") as f:
                f.write(",".join(f"{v:.4f}" for v in bl_row) + "\n")

        # Simulate chain processing time outside lock
        time.sleep(total_ms / 1000.0)

        # ── Build reply ───────────────────────────────────────────────────────
        reply = {
            "status":         "OK",
            "policy":         POLICY,
            "selectedAmf":    "127.0.0.5",   # real Open5GS AMF (single instance in testbed)
            "selectedAmfIdx": amf_idx,
            "selectedSmfIdx": smf_idx,
            "selectedUpfIdx": upf_idx,
            "chainLatencyMs": round(total_ms, 3),
            "amfLatencyMs":   round(amf_ms, 3),
            "smfLatencyMs":   round(smf_ms, 3),
            "upfLatencyMs":   round(upf_ms, 3),
        }
        send_msg(conn, json.dumps(reply))

        print(f"  [t={t:3d}] ue={ue_id} sst={sst} "
              f"chain=AMF[{amf_idx}]+SMF[{smf_idx}]+UPF[{upf_idx}] "
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

    print(f"Dispatcher [{POLICY.upper()}] listening on {HOST}:{args.port}")
    print(f"  Slice 1 — AMF × {len(chain.amf)}: "
          f"mean service times {[inst.mu_ms for inst in chain.amf]} ms")
    print(f"  Slice 2 — SMF × {len(chain.smf)}: "
          f"mean service times {[inst.mu_ms for inst in chain.smf]} ms")
    print(f"  Slice 3 — UPF × {len(chain.upf)}: "
          f"mean service times {[inst.mu_ms for inst in chain.upf]} ms")

    while True:
        conn, addr = server.accept()
        threading.Thread(
            target=handle_client,
            args=(conn, addr, chain, stats, lock, qt_amf, qt_smf, qt_upf),
            daemon=True,
        ).start()


if __name__ == "__main__":
    main()
