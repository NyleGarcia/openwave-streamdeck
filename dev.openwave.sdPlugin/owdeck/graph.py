"""Reading and writing the PipeWire graph, via the tools everyone has.

No bindings, no build step: pactl and wpctl ship with PipeWire and are already
on the path. The cost is a subprocess per operation, which a dial turn can
afford at the rate a human turns one.
"""

import json
import subprocess

_TIMEOUT = 3


def _run(argv, timeout=_TIMEOUT):
    try:
        result = subprocess.run(
            argv, capture_output=True, text=True, timeout=timeout,
        )
    except (FileNotFoundError, subprocess.SubprocessError):
        return None
    return result.stdout if result.returncode == 0 else None


def node_id(node_name):
    """Resolve a node.name to a live id.

    Resolved on every use, never cached. Node ids are reassigned whenever a
    node reappears -- and OpenWave's sinks are destroyed and recreated
    whenever its mixes are installed -- so a cached id silently addresses
    whatever took that number next.

    Where a name somehow resolves twice, the highest object.serial wins: that
    is the most recently created, which is the one the rest of the graph is
    wired to.
    """
    out = _run(["pw-dump"], timeout=5)
    if not out:
        return None
    try:
        objects = json.loads(out)
    except json.JSONDecodeError:
        return None
    best, best_serial = None, -1
    for obj in objects:
        props = (obj.get("info") or {}).get("props") or {}
        if props.get("node.name") != node_name:
            continue
        try:
            serial = int(props.get("object.serial", 0))
        except (TypeError, ValueError):
            serial = 0
        if serial >= best_serial:
            best, best_serial = obj.get("id"), serial
    return best


def sinks():
    """Every sink's (volume 0..1 or None, muted), by name, from one call.

    One pactl for the whole graph rather than three per sink: the deck reads
    every dial several times a second, and a subprocess per field per dial is
    a process storm on pipewire-pulse. JSON rather than the text listing,
    whose field labels are translated. Volume is the first channel's, which
    is what `pactl get-sink-volume` leads with. {} when pactl cannot be read,
    which reads as every sink being gone.
    """
    out = _run(["pactl", "-f", "json", "list", "sinks"])
    if not out:
        return {}
    try:
        listing = json.loads(out)
    except json.JSONDecodeError:
        return {}
    found = {}
    for sink in listing if isinstance(listing, list) else []:
        if not isinstance(sink, dict) or not sink.get("name"):
            continue
        volume = None
        channels = sink.get("volume")
        if isinstance(channels, dict) and channels:
            first = next(iter(channels.values()))
            try:
                volume = int(str(first["value_percent"]).rstrip("%")) / 100.0
            except (KeyError, TypeError, ValueError):
                volume = None
        found[sink["name"]] = (volume, bool(sink.get("mute")))
    return found


def set_volume(name, value):
    value = max(0.0, min(1.0, float(value)))
    _run(["pactl", "set-sink-volume", name, f"{round(value * 100)}%"])
    return value


def get_mute(name):
    out = _run(["pactl", "get-sink-mute", name])
    if not out:
        return None
    return "yes" in out.lower()


def set_mute(name, muted):
    _run(["pactl", "set-sink-mute", name, "1" if muted else "0"])


def toggle_mute(name):
    _run(["pactl", "set-sink-mute", name, "toggle"])
    return get_mute(name)


def default_sink():
    out = _run(["pactl", "get-default-sink"])
    return out.strip() if out else None


def alsa_get(card, numid):
    """Read an ALSA control's integer value, or None."""
    out = _run(["amixer", "-c", str(card), "cget", f"numid={numid}"])
    if not out:
        return None
    for line in out.splitlines():
        if ": values=" in line:
            try:
                return int(line.split("=")[-1].split(",")[0])
            except ValueError:
                return None
    return None


def alsa_set(card, numid, value):
    _run(["amixer", "-c", str(card), "cset", f"numid={numid}", str(value)])
