"""Talk to a running OpenWave over the session bus.

Anything that lives in OpenWave's own state -- which microphone in a group is
live, a cell's send, a source's trim -- has to be changed by OpenWave itself.
Its Mixer reads that state once at construction and rewrites the whole file on
every save, so a value written here from outside is discarded the moment a
slider moves. The USB device is the same story: the firmware serves one
process at a time and the GUI holds the handle.

GApplication already exports org.gtk.Actions on com.github.openwave, so there
is no protocol to invent: OpenWave registers actions, this calls them.

Everything here degrades quietly when OpenWave is not running. A deck key
whose target is closed should do nothing, not crash the plugin.
"""

import json
import subprocess

BUS_NAME = "com.github.openwave"
OBJECT_PATH = "/com/github/openwave"
_TIMEOUT = 3


def _gdbus(method, *args):
    argv = [
        "gdbus", "call", "--session",
        "--dest", BUS_NAME, "--object-path", OBJECT_PATH,
        "--method", f"org.gtk.Actions.{method}", *args,
    ]
    try:
        result = subprocess.run(
            argv, capture_output=True, text=True, timeout=_TIMEOUT,
        )
    except (FileNotFoundError, subprocess.SubprocessError):
        return None
    return result.stdout if result.returncode == 0 else None


def available():
    """True when a running OpenWave is exporting its actions."""
    return _gdbus("List") is not None


def actions():
    out = _gdbus("List")
    if not out:
        return []
    # (['switch-group', 'source-groups'],)
    return [
        piece.strip().strip("'\"")
        for piece in out.strip().lstrip("([").rstrip("],)").split(",")
        if piece.strip()
    ]


def activate(name, *variants):
    """Activate an action. `variants` are GVariant literals, e.g. "<'Mic'>"."""
    params = "[" + ",".join(variants) + "]"
    return _gdbus("Activate", name, params, "{}") is not None


def switch_group(group):
    """Hand a microphone group over to its next source."""
    escaped = group.replace("\\", "\\\\").replace("'", "\\'")
    return activate("switch-group", f"<'{escaped}'>")


def source_groups():
    """Group names worth switching between, straight from OpenWave.

    Activate first so OpenWave refreshes the state, then read it back:
    org.gtk.Actions.Activate has no reply, but Describe returns the state, and
    that is the pair the action was built around.
    """
    activate("source-groups")
    out = _gdbus("Describe", "source-groups")
    if not out:
        return []
    # ((true, signature '', [<['Mic', 'Guest']>]),)
    names = []
    depth = 0
    for token in out.replace("[", " [ ").replace("]", " ] ").split():
        if token == "[":
            depth += 1
        elif token == "]":
            depth -= 1
        elif depth >= 2 and token.strip(",").startswith("'"):
            names.append(token.strip(",").strip("'"))
    return names
