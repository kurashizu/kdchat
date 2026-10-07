"""Which sync tier the KuraDot / Klaude avatar uses (full / standard / lite), from the OSC config files VRChat writes on
this computer (one JSON per avatar with its parameter names). Read only, no OSC traffic.

VRChat writes the file of an avatar when you first wear it, so the newest file that has display parameters is the
avatar set up most recently; a user who switches between avatars of different tiers picks the tier by hand."""
import glob
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "kd_display"))
from kd.config import Config            # noqa: E402


def osc_dir() -> str | None:
    """VRChat's OSC folder: KDCHAT_VRC_OSC_DIR, else %LOCALAPPDATA%\\..\\LocalLow\\VRChat\\VRChat\\OSC (Windows)"""
    d = os.environ.get("KDCHAT_VRC_OSC_DIR")
    if d:
        return d
    la = os.environ.get("LOCALAPPDATA")
    if la:
        return os.path.join(os.path.dirname(la.rstrip("\\/")), "LocalLow", "VRChat", "VRChat", "OSC")
    return None


def detect() -> dict | None:
    """-> {"tier", "avatar", "name"} of the newest avatar file with display parameters, or None"""
    d = osc_dir()
    if not d or not os.path.isdir(d):
        return None
    files = glob.glob(os.path.join(d, "usr_*", "Avatars", "*.json"))
    for path in sorted(files, key=lambda p: os.path.getmtime(p), reverse=True):
        try:
            with open(path, encoding="utf-8-sig") as f:
                j = json.load(f)
        except (OSError, ValueError):
            continue
        tier = Config.tier_of(p.get("name") for p in j.get("parameters", []) if isinstance(p, dict))
        if tier:
            return {"tier": tier, "avatar": j.get("id", ""), "name": j.get("name", "")}
    return None
