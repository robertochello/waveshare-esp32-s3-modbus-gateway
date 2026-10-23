#!/usr/bin/env python3
"""Read-only Modbus TCP smoke test for Waveshare ESP32-S3 gateway.

Usage: python tools/modbus_tcp_probe.py 192.168.101.5
"""
import argparse
import socket
import struct

def receive_exact(conn: socket.socket, size: int) -> bytes:
    result = bytearray()
    while len(result) < size:
        chunk = conn.recv(size - len(result))
        if not chunk:
            raise ConnectionError("Connection closed before a full Modbus response")
        result.extend(chunk)
    return bytes(result)

def request(conn: socket.socket, txid: int, unit: int, function: int,
            start: int, count: int) -> bytes:
    pdu = struct.pack(">BHH", function, start, count)
    conn.sendall(struct.pack(">HHHB", txid, 0, len(pdu) + 1, unit) + pdu)
    hdr = receive_exact(conn, 7)
    reply_txid, protocol, payload_length, reply_unit = struct.unpack(">HHHB", hdr)
    if (reply_txid, protocol, reply_unit) != (txid, 0, unit):
        raise ValueError("Unexpected MBAP transaction/protocol/unit identifier")
    if payload_length < 2 or payload_length > 254:
        raise ValueError("Invalid MBAP length in reply")
    reply = receive_exact(conn, payload_length - 1)
    if reply[0] == function | 0x80:
        raise ValueError(f"Modbus exception on FC{function:02d}: {reply[1]:02X}")
    if reply[0] != function:
        raise ValueError(f"Unexpected function in reply: {reply[0]}")
    return reply

def read_bits(conn: socket.socket, txid: int, unit: int, function: int,
              start: int, count: int) -> list[int]:
    pdu = request(conn, txid, unit, function, start, count)
    expected_bytes = (count + 7) // 8
    if len(pdu) != 2 + expected_bytes or pdu[1] != expected_bytes:
        raise ValueError("Invalid bit response length")
    return [(pdu[2 + i // 8] >> (i % 8)) & 1 for i in range(count)]

def read_regs(conn: socket.socket, txid: int, unit: int,
              start: int, count: int) -> list[int]:
    pdu = request(conn, txid, unit, 3, start, count)
    if len(pdu) != 2 + count * 2 or pdu[1] != count * 2:
        raise ValueError("Invalid register response length")
    return list(struct.unpack(">" + "H" * count, pdu[2:]))

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("host", help="Device IPv4 address")
    parser.add_argument("--port", type=int, default=502)
    parser.add_argument("--unit", type=int, default=1)
    parser.add_argument("--timeout", type=float, default=3.0)
    args = parser.parse_args()
    if not 0 <= args.unit <= 255:
        parser.error("--unit must be in 0..255")

    # Reuse one connection for every request to exercise TCP session handling.
    with socket.create_connection((args.host, args.port), args.timeout) as conn:
        conn.settimeout(args.timeout)
        for cycle in range(1, 4):
            txid = cycle * 10
            di = read_bits(conn, txid, args.unit, 2, 0, 8)
            do = read_bits(conn, txid + 1, args.unit, 1, 0, 8)
            holding = read_regs(conn, txid + 2, args.unit, 0, 2)
            di_mask = sum(bit << i for i, bit in enumerate(di))
            print(f"Poll {cycle}: DI={di} DO={do} HR0={holding[0]} HR1={holding[1]}")
            if di_mask != holding[0]:
                print("NOTE: DI changed between reads or register map differs")
    print("Modbus TCP read-only smoke test completed")

if __name__ == "__main__":
    main()
