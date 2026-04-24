#!/usr/bin/env python3
"""
Xn endpoint stub — simulates the target gNB's Xn interface.
Listens for XnHandoverRequest from the source gNB, logs it, and replies OK.

Usage:
    python3 xn_server.py [--host 127.0.0.2] [--port 38422]
"""
import argparse
import json
import socket
import struct
import threading
import time


def recv_msg(conn):
    raw = conn.recv(4)
    if len(raw) < 4:
        return None
    length = struct.unpack("!I", raw)[0]
    data = b""
    while len(data) < length:
        chunk = conn.recv(length - len(data))
        if not chunk:
            return None
        data += chunk
    return data.decode()


def send_msg(conn, payload: str):
    data = payload.encode()
    conn.sendall(struct.pack("!I", len(data)) + data)


def handle_client(conn, addr):
    print(f"[Xn] Connection from {addr}")
    try:
        msg = recv_msg(conn)
        if not msg:
            return
        req = json.loads(msg)
        print(f"[Xn] XnHandoverRequest received: {json.dumps(req, indent=2)}")

        ue_id   = req.get("ueId", -1)
        sst     = req.get("sliceSst", 1)
        src_gnb = req.get("sourceGnb", "?")

        # Simulate resource allocation delay (configurable)
        time.sleep(0.002)  # 2ms

        resp = json.dumps({
            "type": "XnHandoverAck",
            "ueId": ue_id,
            "sliceSst": sst,
            "status": "OK",
            "targetCell": "0x000000020"
        })
        send_msg(conn, resp)
        print(f"[Xn] XnHandoverAck sent for UE {ue_id} from {src_gnb}")
    except Exception as e:
        print(f"[Xn] Error: {e}")
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.2")
    parser.add_argument("--port", type=int, default=38422)
    args = parser.parse_args()

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind((args.host, args.port))
        s.listen(10)
        print(f"[Xn] Listening on {args.host}:{args.port}")
        while True:
            conn, addr = s.accept()
            threading.Thread(target=handle_client, args=(conn, addr), daemon=True).start()


if __name__ == "__main__":
    main()
