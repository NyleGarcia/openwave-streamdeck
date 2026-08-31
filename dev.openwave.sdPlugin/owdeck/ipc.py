"""Talk to a running OpenWave over the session bus.

Anything that lives in OpenWave's own state -- which microphone in a group is
live, a source's trim, its mute -- has to be changed by OpenWave itself. Its
Mixer holds the same dict the window does and rewrites sources.json whole on
every save, so a value written here from outside is discarded the moment a
slider moves. The USB device is the same story: the firmware serves one
process at a time and the GUI holds the handle.

GApplication already exports org.gtk.Actions on com.github.openwave, so there
is no protocol to invent: OpenWave registers actions, this calls them.

Two transports, because neither is always available. GObject introspection is
preferred -- it hands back real GVariants, so a JSON snapshot survives the
round trip with its quoting intact, which parsing `gdbus` output does not
reliably manage. When gi is missing (a stripped interpreter, a different
runtime) the gdbus fallback still covers the fire-and-forget calls that carry
no payload worth parsing.

Everything degrades quietly when OpenWave is not running: a deck key whose
target is closed should do nothing, not take the plugin down with it.
"""

import json
import logging
import subprocess

BUS_NAME = "com.github.openwave"
OBJECT_PATH = "/com/github/openwave"
IFACE = "org.gtk.Actions"
_TIMEOUT = 3

log = logging.getLogger("openwave-deck.ipc")

try:
    import gi
    gi.require_version("Gio", "2.0")
    from gi.repository import Gio, GLib
    _HAVE_GI = True
except (ImportError, ValueError):                          # pragma: no cover
    _HAVE_GI = False

_proxy = None


def _get_proxy():
    """A bus proxy, made once and reused, or None if OpenWave is not there.

    Cached because building one costs a round trip and the deck redraws on a
    timer; dropped whenever a call fails, so a restarted OpenWave is picked up
    on the next attempt rather than being unreachable until the plugin is.
    """
    global _proxy
    if not _HAVE_GI:
        return None
    if _proxy is not None:
        return _proxy
    try:
        _proxy = Gio.DBusProxy.new_for_bus_sync(
            Gio.BusType.SESSION,
            Gio.DBusProxyFlags.DO_NOT_AUTO_START
            | Gio.DBusProxyFlags.DO_NOT_LOAD_PROPERTIES,
            None, BUS_NAME, OBJECT_PATH, IFACE, None,
        )
    except GLib.Error:
        return None
    # DO_NOT_AUTO_START still yields a proxy for an absent name; the owner is
    # what says whether anyone is actually listening.
    if _proxy.get_name_owner() is None:
        _proxy = None
    return _proxy


def _call(method, parameters):
    global _proxy
    proxy = _get_proxy()
    if proxy is None:
        return None
    try:
        return proxy.call_sync(
            method, parameters, Gio.DBusCallFlags.NO_AUTO_START,
            _TIMEOUT * 1000, None,
        )
    except GLib.Error as exc:
        log.debug("%s failed: %s", method, exc)
        _proxy = None
        return None


def _gdbus(method, *args):
    """Fallback transport for calls whose reply we do not need to read."""
    argv = [
        "gdbus", "call", "--session",
        "--dest", BUS_NAME, "--object-path", OBJECT_PATH,
        "--method", f"{IFACE}.{method}", *args,
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
    if _HAVE_GI:
        return _get_proxy() is not None
    return _gdbus("List") is not None


def actions():
    """The action names OpenWave currently offers."""
    if _HAVE_GI:
        reply = _call("List", None)
        return list(reply.unpack()[0]) if reply else []
    out = _gdbus("List")
    if not out:
        return []
    return [
        piece.strip().strip("'\"")
        for piece in out.strip().lstrip("([").rstrip("],)").split(",")
        if piece.strip()
    ]


def activate(name, parameter=None, literal=None):
    """Activate an action.

    `parameter` is a GVariant for the gi path; `literal` its textual form for
    the gdbus fallback. Both are given because the two transports cannot share
    a representation, and an action that works only when gi happens to be
    importable is worse than one that works twice over.
    """
    if _HAVE_GI:
        args = [parameter] if parameter is not None else []
        reply = _call(
            "Activate", GLib.Variant("(sava{sv})", (name, args, {})),
        )
        return reply is not None
    params = f"[{literal}]" if literal else "[]"
    return _gdbus("Activate", name, params, "{}") is not None


def _state(name):
    """An action's state, after asking it to refresh.

    org.gtk.Actions.Activate has no reply, but Describe returns the state and
    Changed fires when it moves, so refresh-then-read is the pair these
    actions were built around.
    """
    activate(name)
    if _HAVE_GI:
        reply = _call("Describe", GLib.Variant("(s)", (name,)))
        if reply is None:
            return None
        enabled, _hint, state = reply.unpack()[0]
        return state[0] if state else None
    return None


def _quote(text):
    return str(text).replace("\\", "\\\\").replace("'", "\\'")


def switch_group(group):
    """Hand a microphone group over to its next microphone."""
    escaped = group.replace("\\", "\\\\").replace("'", "\\'")
    parameter = GLib.Variant("s", group) if _HAVE_GI else None
    return activate("switch-group", parameter, f"<'{escaped}'>")


def set_source_level(source_id, level):
    """Set a source's trim, 0..1."""
    level = max(0.0, min(1.0, float(level)))
    parameter = (GLib.Variant("(sd)", (source_id, level)) if _HAVE_GI
                 else None)
    escaped = source_id.replace("\\", "\\\\").replace("'", "\\'")
    return activate(
        "set-source-level", parameter, f"<('{escaped}', {level!r})>",
    )


def toggle_source_mute(source_id):
    escaped = source_id.replace("\\", "\\\\").replace("'", "\\'")
    parameter = GLib.Variant("s", source_id) if _HAVE_GI else None
    return activate("toggle-source-mute", parameter, f"<'{escaped}'>")


def set_cell_level(source_id, mix_id, level):
    """Set how much of one source a single mix receives -- a matrix cell."""
    level = max(0.0, min(1.0, float(level)))
    parameter = (GLib.Variant("(ssd)", (source_id, mix_id, level))
                 if _HAVE_GI else None)
    return activate(
        "set-cell-level", parameter,
        f"<('{_quote(source_id)}', '{_quote(mix_id)}', {level!r})>",
    )


def toggle_cell_mute(source_id, mix_id):
    parameter = (GLib.Variant("(ss)", (source_id, mix_id))
                 if _HAVE_GI else None)
    return activate(
        "toggle-cell-mute", parameter,
        f"<('{_quote(source_id)}', '{_quote(mix_id)}')>",
    )


def snapshot():
    """Every source's name, level, mute and group, or None if unreachable.

    One call rather than one per field: a button has to draw all of it at
    once, and reading it piecemeal would let the parts disagree mid-read.
    """
    raw = _state("snapshot")
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def source_groups():
    """Group names worth switching between."""
    data = snapshot()
    if data is not None:
        return list(data.get("groups") or [])
    state = _state("source-groups")
    return list(state) if state else []


def scenes():
    """{scene id: display name} OpenWave currently stores, {} when closed.

    The `scenes` action publishes its answer as state, exactly like
    snapshot: activate to refresh, describe to read.
    """
    raw = _state("scenes")
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def apply_scene(scene_id):
    """Recall a scene: every trim, send, mute, output, master and device
    setting it holds. Entries naming things since removed are skipped by
    OpenWave — recalling an old scene is never dangerous."""
    parameter = GLib.Variant("s", scene_id) if _HAVE_GI else None
    return activate("apply-scene", parameter, f"<'{_quote(scene_id)}'>")


def save_scene(name):
    """Capture the current levels under a name, replacing that scene."""
    parameter = GLib.Variant("s", name) if _HAVE_GI else None
    return activate("save-scene", parameter, f"<'{_quote(name)}'>")
