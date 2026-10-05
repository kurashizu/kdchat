"""The machine's LAN addresses, for the "open on your phone" link and QR code."""
from __future__ import annotations

import ipaddress
import socket
from typing import Optional

# adapters that are not the LAN a phone is on (VMs, containers, VPNs, tunnels)
VIRTUAL = ("docker", "veth", "br-", "virbr", "vmnet", "vmware", "virtualbox", "vboxnet", "vethernet", "hyper-v",
           "wsl", "tailscale", "zerotier", "wireguard", "wg", "tun", "tap", "utun", "ppp", "ipsec", "nordlynx",
           "hamachi", "radmin", "loopback", "lo", "awdl", "llw", "bridge", "anpi", "gif", "stf")


def _primary_ipv4() -> Optional[str]:
    """the address of the interface with the default route (no packet is sent)"""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("192.0.2.1", 9))                  # TEST-NET-1: never routed anywhere, just picks the interface
        return s.getsockname()[0]
    except OSError:
        return None
    finally:
        s.close()


def _usable(ip: str) -> bool:
    try:
        a = ipaddress.IPv4Address(ip)
    except ValueError:
        return False
    return not (a.is_loopback or a.is_link_local or a.is_multicast or a.is_unspecified
                or a in ipaddress.IPv4Network("100.64.0.0/10")              # CGNAT: Tailscale & co
                or a in ipaddress.IPv4Network("198.18.0.0/15"))             # benchmark / some VPN clients


def _virtual(name: str) -> bool:
    n = name.lower()
    return any(n.startswith(v) or v in n for v in VIRTUAL if len(v) > 3) or \
        any(n.startswith(v) for v in VIRTUAL if len(v) <= 3)


def lan_ipv4() -> list[str]:
    """LAN IPv4 addresses, the default-route one first. Empty list if there is none."""
    out: list[str] = []
    primary = _primary_ipv4()
    if primary and _usable(primary):
        out.append(primary)
    try:
        import psutil
        stats = psutil.net_if_stats()
        for name, addrs in psutil.net_if_addrs().items():
            if _virtual(name) or (name in stats and not stats[name].isup):
                continue
            for a in addrs:
                if a.family == socket.AF_INET and _usable(a.address) and a.address not in out \
                        and ipaddress.IPv4Address(a.address).is_private:
                    out.append(a.address)
    except Exception:                                   # noqa: BLE001  psutil missing / no permission
        pass
    return out


def urls(listen_host: str, port: int) -> list[str]:
    """the URLs a phone on the LAN can open"""
    if listen_host in ("0.0.0.0", "", "::"):
        hosts = lan_ipv4()
    elif listen_host in ("127.0.0.1", "localhost"):
        hosts = []
    else:
        hosts = [listen_host]
    return [f"http://{h}:{port}/" for h in hosts]
