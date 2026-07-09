"""Minimal Source RCON protocol client -- just enough to send console
commands (like `tellraw`) to the Minecraft server. RCON is bound to
127.0.0.1 only and the port isn't forwarded on the router, so this never
leaves the box."""
import json
import os
import socket
import struct

RCON_HOST = "127.0.0.1"
RCON_PORT = 25575

SERVERDATA_AUTH = 3
SERVERDATA_EXECCOMMAND = 2


def _send_packet(sock: socket.socket, request_id: int, pkt_type: int, payload: str) -> None:
    body = payload.encode("utf-8") + b"\x00\x00"
    packet = struct.pack("<iii", 4 + 4 + len(body), request_id, pkt_type) + body
    sock.sendall(packet)


def _read_packet(sock: socket.socket) -> tuple[int, int, str]:
    raw_len = sock.recv(4)
    if len(raw_len) < 4:
        raise ConnectionError("RCON connection closed unexpectedly")
    length = struct.unpack("<i", raw_len)[0]
    data = b""
    while len(data) < length:
        chunk = sock.recv(length - len(data))
        if not chunk:
            raise ConnectionError("RCON connection closed unexpectedly")
        data += chunk
    request_id, pkt_type = struct.unpack("<ii", data[:8])
    payload = data[8:-2].decode("utf-8", errors="replace")
    return request_id, pkt_type, payload


def rcon_command(command: str, timeout: float = 5.0) -> str:
    password = os.environ.get("RCON_PASSWORD", "")
    with socket.create_connection((RCON_HOST, RCON_PORT), timeout=timeout) as sock:
        _send_packet(sock, 1, SERVERDATA_AUTH, password)
        request_id, _, _ = _read_packet(sock)
        if request_id == -1:
            raise PermissionError("RCON authentication failed")

        _send_packet(sock, 2, SERVERDATA_EXECCOMMAND, command)
        _, _, payload = _read_packet(sock)
        return payload


def tellraw_component(target: str, component: dict) -> None:
    payload = json.dumps(component, ensure_ascii=False)
    rcon_command(f"tellraw {target} {payload}")


def tellraw(player_name: str, text: str, color: str = "yellow", bold: bool = True) -> None:
    tellraw_component(player_name, {"text": text, "color": color, "bold": bold})
