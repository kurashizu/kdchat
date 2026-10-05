"""Minimal OSC over UDP (no dependencies): int / float / bool messages and bundles, plus an optional listener for
VRChat's /avatar/change."""
import socket, struct, threading


def _pad(b):
    return b + b"\0" * (4 - len(b) % 4)


def message(addr, value):
    if isinstance(value, bool):
        return _pad(addr.encode()) + _pad(b",T" if value else b",F")
    if isinstance(value, int):
        return _pad(addr.encode()) + _pad(b",i") + struct.pack(">i", value)
    return _pad(addr.encode()) + _pad(b",f") + struct.pack(">f", float(value))


def bundle(msgs):
    out = b"#bundle\0" + struct.pack(">Q", 1)
    for m in msgs:
        out += struct.pack(">i", len(m)) + m
    return out


def parse(data):
    """-> list of (addr, [args]) (bundles flattened)"""
    if data.startswith(b"#bundle\0"):
        out, i = [], 16
        while i + 4 <= len(data):
            n = struct.unpack(">i", data[i:i + 4])[0]
            out += parse(data[i + 4:i + 4 + n]); i += 4 + n
        return out
    e = data.index(b"\0")
    addr = data[:e].decode(errors="replace")
    i = (e + 4) & ~3
    e2 = data.index(b"\0", i)
    tags = data[i + 1:e2].decode()
    i = (e2 + 4) & ~3
    args = []
    for t in tags:
        if t == "i":
            args.append(struct.unpack(">i", data[i:i + 4])[0]); i += 4
        elif t == "f":
            args.append(struct.unpack(">f", data[i:i + 4])[0]); i += 4
        elif t == "s":
            e3 = data.index(b"\0", i); args.append(data[i:e3].decode(errors="replace")); i = (e3 + 4) & ~3
        elif t in "TF":
            args.append(t == "T")
    return [(addr, args)]


class Sender:
    def __init__(self, host="127.0.0.1", port=9000, use_bundle=True):
        self.addr = (host, port)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.use_bundle = use_bundle

    def send(self, items):
        """items: list of (address, value), sent in this order"""
        msgs = [message(a, v) for a, v in items]
        if self.use_bundle:
            self.sock.sendto(bundle(msgs), self.addr)
        else:
            for m in msgs:
                self.sock.sendto(m, self.addr)


class Listener(threading.Thread):
    """calls on_message(addr, args) for everything VRChat sends (default port 9001)"""
    def __init__(self, port, on_message, host="127.0.0.1"):
        super().__init__(daemon=True)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind((host, port))
        self.on_message = on_message

    def run(self):
        while True:
            data, _ = self.sock.recvfrom(65536)
            try:
                for addr, args in parse(data):
                    self.on_message(addr, args)
            except (ValueError, struct.error):
                pass
