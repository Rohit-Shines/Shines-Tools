from __future__ import annotations

from dataclasses import dataclass
import socket
import ssl
import threading
from typing import Callable

from .parser import HL7Parser

VT = b"\x0b"
FS_CR = b"\x1c\x0d"


@dataclass(frozen=True)
class MLLPResponse:
    raw: str
    bytes_sent: int
    bytes_received: int


def frame_message(raw: str) -> bytes:
    payload = raw.replace("\n", "\r").encode("utf-8")
    return VT + payload + FS_CR


def unframe_message(data: bytes) -> str:
    payload = data
    if payload.startswith(VT):
        payload = payload[1:]
    if payload.endswith(FS_CR):
        payload = payload[:-2]
    elif payload.endswith(b"\x1c"):
        payload = payload[:-1]
    return payload.decode("utf-8", errors="replace")


def send_message(host: str, port: int, raw: str, timeout: float = 10.0, use_tls: bool = False) -> MLLPResponse:
    framed = frame_message(raw)
    base = socket.create_connection((host, port), timeout=timeout)
    connection: socket.socket
    if use_tls:
        context = ssl.create_default_context()
        connection = context.wrap_socket(base, server_hostname=host)
    else:
        connection = base
    with connection:
        connection.settimeout(timeout)
        connection.sendall(framed)
        chunks: list[bytes] = []
        while True:
            chunk = connection.recv(65536)
            if not chunk:
                break
            chunks.append(chunk)
            if FS_CR in b"".join(chunks):
                break
    response = b"".join(chunks)
    return MLLPResponse(unframe_message(response), len(framed), len(response))


def build_aa_ack(raw: str) -> str:
    try:
        message = HL7Parser.parse_message(raw)
        field = message.delimiters.field
        enc = message.delimiters.encoding_characters
        control = message.control_id or "UNKNOWN"
        sending_app = message.value_at("MSH-5") or "HL7_SHINES"
        sending_fac = message.value_at("MSH-6") or "LOCAL"
        receiving_app = message.value_at("MSH-3") or "UNKNOWN"
        receiving_fac = message.value_at("MSH-4") or "UNKNOWN"
        version = message.value_at("MSH-12") or "2.5.1"
    except Exception:
        field, enc, control, sending_app, sending_fac, receiving_app, receiving_fac, version = "|", "^~\\&", "UNKNOWN", "HL7_SHINES", "LOCAL", "UNKNOWN", "UNKNOWN", "2.5.1"
    from datetime import datetime
    ts = datetime.now().astimezone().strftime("%Y%m%d%H%M%S%z")
    ack_control = f"ACK{datetime.now().strftime('%H%M%S%f')[:10]}"
    return (
        f"MSH{field}{enc}{field}{sending_app}{field}{sending_fac}{field}{receiving_app}{field}{receiving_fac}{field}{ts}{field}{field}ACK^A01^ACK{field}{ack_control}{field}P{field}{version}\r"
        f"MSA{field}AA{field}{control}{field}Message accepted by HL7 Shines"
    )


class MLLPListener:
    def __init__(self, host: str, port: int, on_message: Callable[[str], None], on_log: Callable[[str], None]):
        self.host = host
        self.port = port
        self.on_message = on_message
        self.on_log = on_log
        self._socket: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._stopping = threading.Event()

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def start(self) -> None:
        if self.running:
            return
        self._stopping.clear()
        self._thread = threading.Thread(target=self._run, name="HL7Shines-MLLP", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stopping.set()
        if self._socket:
            try:
                self._socket.close()
            except OSError:
                pass
        self._socket = None

    def _run(self) -> None:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
                self._socket = server
                server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                server.bind((self.host, self.port))
                server.listen(5)
                server.settimeout(0.5)
                self.on_log(f"Listening on {self.host}:{self.port}")
                while not self._stopping.is_set():
                    try:
                        client, address = server.accept()
                    except socket.timeout:
                        continue
                    except OSError:
                        break
                    threading.Thread(target=self._handle_client, args=(client, address), daemon=True).start()
        except Exception as exc:
            self.on_log(f"Listener error: {exc}")
        finally:
            self._socket = None
            self.on_log("Listener stopped")

    def _handle_client(self, client: socket.socket, address: tuple) -> None:
        with client:
            client.settimeout(10)
            chunks: list[bytes] = []
            while True:
                try:
                    chunk = client.recv(65536)
                except socket.timeout:
                    break
                if not chunk:
                    break
                chunks.append(chunk)
                if FS_CR in b"".join(chunks):
                    break
            payload = b"".join(chunks)
            raw = unframe_message(payload)
            self.on_log(f"Received {len(payload)} bytes from {address[0]}:{address[1]}")
            self.on_message(raw)
            ack = frame_message(build_aa_ack(raw))
            client.sendall(ack)
            self.on_log(f"Returned AA ACK ({len(ack)} bytes)")
