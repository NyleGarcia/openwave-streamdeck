"""OpenWave plugin for OpenDeck.

One process. It speaks OpenDeck's WebSocket protocol and drives PipeWire
through pactl; there is no sandbox to cross and nothing that needs to outlive
the plugin, so a second process would buy nothing.

Two kinds of target, deliberately behind one action. A mix is a PipeWire sink
and its volume is set with pactl. A source's trim is OpenWave's own state --
its Mixer holds the dict the window holds and rewrites sources.json whole on
every save -- so it is set by asking OpenWave over the session bus. From the
key's point of view both are just "the thing this dial turns", which is the
only distinction a person placing a dial actually cares about.

Nothing here may raise to the top level. OpenDeck does not restart a plugin
that dies -- the keys simply stop responding, with no indication why -- so
every handler is wrapped and every failure is logged and swallowed.
"""

import json
import logging
import os
import select
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from owdeck import graph, ipc, owstate, render   # noqa: E402
from owdeck.ws import WebSocket                  # noqa: E402

LOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "plugin.log")
logging.basicConfig(
    filename=LOG_PATH,
    level=logging.DEBUG if os.environ.get("OPENWAVE_DECK_DEBUG") else logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("openwave-deck")

VOLUME = "dev.openwave.mixlevel"
MIC_GROUP = "dev.openwave.micgroup"

# How far one dial detent moves a level. Small enough to land on a value,
# large enough to cross the range without a long spin.
STEP = 0.02
# Keys are redrawn on this cadence so a change made in OpenWave's window, or
# by anything else touching the graph, shows up without the deck being touched
# first.
REFRESH_SECONDS = 1.0
# OpenWave's snapshot is fetched at most this often and shared by every key,
# so a deck full of source dials costs one bus round trip per tick, not one
# per key.
SNAPSHOT_SECONDS = 0.9
# Our own layout, not a built-in one. $A0 does expose a full-canvas pixmap,
# but it also carries a title item and a second canvas -- and OpenDeck draws
# BOTH over the top: the title falls back to the action's name ("Volume")
# rather than staying empty when set to "", and the unset canvas paints a
# transparency checkerboard across the middle of the strip. A layout with one
# item cannot do either.
ENCODER_LAYOUT = "layouts/strip.json"
CANVAS = "canvas"

# Mix icons come from OpenWave's own choice for the column, so a mix that
# looks like headphones in the window looks like headphones on the deck.
_MIX_GLYPHS = {
    "audio-headphones-symbolic": "headphones",
    "media-record-symbolic": "record",
    "system-users-symbolic": "speaker",
}


def parse_target(settings):
    """What a key controls, as (kind, ident), or (None, None).

    Three kinds. "mix" is a mix's master, a PipeWire sink. "src" is a source's
    trim, applying in every mix at once. "cell" is one send -- how much of one
    source a single mix receives -- and its ident is "<source>:<mix>".

    Settings written before targets existed named a mix directly; they are
    read as mix targets rather than being discarded, so a key placed earlier
    keeps working instead of quietly going blank after an update.
    """
    raw = settings.get("target") or ""
    if not raw and settings.get("mix"):
        raw = "mix:" + settings["mix"]
    kind, _, ident = raw.partition(":")
    if kind in ("mix", "src") and ident:
        return kind, ident
    if kind == "cell" and ident.count(":") == 1 and all(ident.split(":")):
        return kind, ident
    return None, None


def split_cell(ident):
    source_id, _, mix_id = ident.partition(":")
    return source_id, mix_id


class Plugin:
    def __init__(self, port, uuid, register_event):
        self._ws = WebSocket(port, timeout=1.0)
        self._uuid = uuid
        self._ws.send_json({"event": register_event, "uuid": uuid})
        log.info("registered as %s on port %s", uuid, port)
        # context -> settings, for every visible instance of our actions
        self._contexts = {}
        # context -> the last payload drawn, so a tick that changes nothing
        # sends nothing: the deck redraws on receipt, and a key repainting
        # every second visibly flickers.
        self._drawn = {}
        self._last_refresh = 0.0
        self._snapshot = None
        self._snapshot_at = 0.0

    # ------------------------------------------------------------ outbound
    def _send(self, event, context, payload=None):
        message = {"event": event, "context": context}
        if payload is not None:
            message["payload"] = payload
        log.debug("-> %s %s", event, str(payload)[:160])
        try:
            self._ws.send_json(message)
        except (OSError, ConnectionError) as exc:
            log.warning("send %s failed: %s", event, exc)

    # --------------------------------------------------------- reading state
    def _openwave(self, force=False):
        """OpenWave's source snapshot, refetched at most once a tick."""
        now = time.monotonic()
        if force or self._snapshot_at == 0.0 \
                or now - self._snapshot_at >= SNAPSHOT_SECONDS:
            self._snapshot_at = now
            self._snapshot = ipc.snapshot()
        return self._snapshot

    def _read(self, settings):
        """What a volume key should show: name, percent, mute, glyph.

        `ok` is False when the target cannot be read at all -- a mix routed
        nowhere, a source whose OpenWave is closed -- which is a normal state
        worth drawing plainly rather than an error worth hiding.
        """
        kind, ident = parse_target(settings)
        if kind is None:
            return None
        if kind == "mix":
            sink = owstate.mix_sink(ident)
            name = owstate.mix_name(ident)
            glyph = _MIX_GLYPHS.get(
                (owstate.mixes().get(ident) or {}).get("icon_name"), "speaker")
            if not sink or not graph.sink_exists(sink):
                return {"name": name, "percent": 0, "muted": False,
                        "glyph": glyph, "ok": False, "context": ""}
            volume = graph.get_volume(sink)
            return {
                "name": name,
                "percent": 0 if volume is None else round(volume * 100),
                "muted": bool(graph.get_mute(sink)),
                "glyph": glyph,
                "ok": volume is not None,
                "context": "",
            }
        data = self._openwave()
        if data is None:
            return {"name": "OpenWave", "percent": 0, "muted": False,
                    "glyph": "mic", "ok": False, "context": ""}
        if kind == "cell":
            source_id, mix_id = split_cell(ident)
            cell = (data.get("cells") or {}).get(f"{source_id}.{mix_id}")
            source = next((s for s in data.get("sources") or []
                           if s.get("id") == source_id), None)
            mix = next((m for m in data.get("mixes") or []
                        if m.get("id") == mix_id), None)
            if cell is None or source is None or mix is None:
                return {"name": "Missing", "percent": 0, "muted": False,
                        "glyph": "speaker", "ok": False, "context": ""}
            return {
                "name": source.get("name", source_id),
                "percent": round(float(cell["volume"]) * 100),
                "muted": bool(cell["muted"]),
                "glyph": ("mic" if source.get("kind") == "device"
                          else "speaker"),
                "ok": True,
                "context": mix.get("name", mix_id),
            }
        for source in data.get("sources") or []:
            if source.get("id") != ident:
                continue
            device = source.get("kind") == "device"
            return {
                "name": source.get("name", ident),
                "percent": round(float(source.get("level", 1.0)) * 100),
                "muted": bool(source.get("muted")),
                "glyph": "mic" if device else "speaker",
                "ok": True,
                "context": "",
            }
        return {"name": "Missing", "percent": 0, "muted": False,
                "glyph": "speaker", "ok": False, "context": ""}

    def _group_state(self, group):
        """(live microphone name, member count, its position) for a group."""
        data = self._openwave()
        if data is None:
            return None
        members = [s for s in (data.get("sources") or [])
                   if (s.get("group") or "") == group]
        live = next((s for s in members if not s.get("muted")), None)
        position = members.index(live) + 1 if live is not None else 0
        return (live.get("name", "") if live else "", len(members), position)

    # ------------------------------------------------------------- drawing
    def _paint(self, context, image, title=""):
        """Send an image only when it actually changed."""
        if self._drawn.get(context) == image:
            return
        self._drawn[context] = image
        self._send("setImage", context,
                   {"image": render.data_uri(image), "target": 0})
        # The image carries the text, so any title OpenDeck would draw on top
        # of it is duplication; clearing it once keeps the key clean.
        self._send("setTitle", context, {"title": title, "target": 0})

    def _paint_strip(self, context, state):
        """The encoder's touch strip, drawn whole."""
        image = render.strip(state["name"], state["percent"], state["muted"],
                             kind=state["glyph"], unavailable=not state["ok"],
                             context=state.get("context", ""))
        if self._drawn.get((context, "strip")) == image:
            return
        self._drawn[(context, "strip")] = image
        self._send("setFeedback", context,
                   {CANVAS: render.data_uri(image)})

    def _render(self, context):
        """Draw one instance from live audio state."""
        settings = self._contexts.get(context) or {}
        if settings.get("action") == MIC_GROUP:
            self._render_group(context, settings)
            return

        encoder = settings.get("controller") == "Encoder"
        state = self._read(settings)
        if state is None:
            if encoder:
                self._paint_strip(context, {
                    "name": "Pick a mix or source", "percent": 0,
                    "muted": False, "glyph": "speaker", "ok": False,
                    "context": ""})
            else:
                self._paint(context, render.unconfigured_key(
                    "Pick a mix", "or a source"))
            return
        if encoder:
            self._paint_strip(context, state)
        else:
            self._paint(context, render.level_key(
                state["name"], state["percent"], state["muted"],
                kind=state["glyph"], unavailable=not state["ok"],
                context=state.get("context", "")))

    def _render_group(self, context, settings):
        group = settings.get("group")
        if not group:
            self._paint(context, render.unconfigured_key(
                "Pick a group", "in settings", kind="mic"))
            return
        state = self._group_state(group)
        if state is None:
            self._paint(context, render.group_key(group, "", 0,
                                                  unavailable=True))
            return
        live, count, position = state
        self._paint(context, render.group_key(group, live, count, position))

    def _render_all(self):
        for context in list(self._contexts):
            try:
                self._render(context)
            except Exception:                      # noqa: BLE001
                log.exception("render failed for %s", context)

    # ------------------------------------------------------------- actions
    def _set_level(self, settings, value):
        kind, ident = parse_target(settings)
        value = max(0.0, min(1.0, value))
        if kind == "mix":
            sink = owstate.mix_sink(ident)
            if sink:
                graph.set_volume(sink, value)
        elif kind == "src":
            ipc.set_source_level(ident, value)
            self._openwave(force=True)
        elif kind == "cell":
            ipc.set_cell_level(*split_cell(ident), value)
            self._openwave(force=True)

    def _adjust(self, context, ticks):
        settings = self._contexts.get(context) or {}
        state = self._read(settings)
        if state is None or not state["ok"]:
            return
        self._set_level(settings, state["percent"] / 100.0 + ticks * STEP)
        self._render(context)

    def _toggle_mute(self, context):
        settings = self._contexts.get(context) or {}
        kind, ident = parse_target(settings)
        if kind == "mix":
            sink = owstate.mix_sink(ident)
            if not sink:
                self._send("showAlert", context)
                return
            graph.toggle_mute(sink)
        elif kind == "cell":
            if ipc.toggle_cell_mute(*split_cell(ident)) is False:
                self._send("showAlert", context)
                return
            self._openwave(force=True)
        elif kind == "src":
            if ipc.toggle_source_mute(ident) is False:
                # A source's mute lives in OpenWave; with it closed there is
                # nothing to flip, and saying so beats a key that looks dead.
                self._send("showAlert", context)
                return
            self._openwave(force=True)
        else:
            self._send("showAlert", context)
            return
        self._render(context)

    def _switch_group(self, context):
        settings = self._contexts.get(context) or {}
        group = settings.get("group")
        if not group:
            self._send("showAlert", context)
            return
        if not ipc.switch_group(group):
            self._send("showAlert", context)
            return
        self._openwave(force=True)
        self._render(context)

    # ------------------------------------------------- property inspector
    def _inspector_payload(self, action):
        if action == MIC_GROUP:
            data = self._openwave(force=True)
            return {
                "openwave": data is not None,
                "groups": list((data or {}).get("groups") or []),
            }
        default = graph.default_sink()
        data = self._openwave(force=True)
        targets = [
            {
                "value": f"mix:{mix_id}",
                "label": label,
                "group": "Mixes",
                # The monitoring mix is normally the system default sink, so
                # its master is the machine's volume. The inspector says so
                # rather than letting someone find out by muting everything.
                "isDefault": sink == default,
            }
            for mix_id, label, sink in owstate.mix_choices()
        ]
        for source in (data or {}).get("sources") or []:
            targets.append({
                "value": f"src:{source.get('id')}",
                "label": source.get("name", source.get("id", "")),
                "group": ("Microphones" if source.get("kind") == "device"
                          else "Sources"),
                "isDefault": False,
            })
        # Sends last and grouped by mix, so the list reads the way the matrix
        # does: a column is a mix, and the rows under it are what feeds it.
        for mix in (data or {}).get("mixes") or []:
            mix_id, mix_name = mix.get("id"), mix.get("name", mix.get("id"))
            for source in (data or {}).get("sources") or []:
                targets.append({
                    "value": f"cell:{source.get('id')}:{mix_id}",
                    "label": f"{source.get('name')} into {mix_name}",
                    "group": f"Sends into {mix_name}",
                    "isDefault": False,
                })
        return {"targets": targets, "openwave": data is not None}

    # ------------------------------------------------------------- inbound
    def _handle(self, message):
        event = message.get("event")
        context = message.get("context")
        payload = message.get("payload") or {}

        if event in ("willAppear", "didReceiveSettings"):
            settings = dict(payload.get("settings") or {})
            settings["controller"] = payload.get("controller", "Keypad")
            settings["action"] = message.get("action", VOLUME)
            self._contexts[context] = settings
            # A redraw after a settings change must not be suppressed by the
            # previous target's cached image.
            self._drawn.pop(context, None)
            self._drawn.pop((context, "strip"), None)
            if settings["controller"] == "Encoder":
                self._send("setFeedbackLayout", context,
                           {"layout": ENCODER_LAYOUT})
            self._render(context)
        elif event == "willDisappear":
            self._contexts.pop(context, None)
            self._drawn.pop(context, None)
            self._drawn.pop((context, "strip"), None)
        elif event == "dialRotate":
            self._adjust(context, int(payload.get("ticks", 0)))
        elif event in ("dialDown", "keyDown", "touchTap"):
            settings = self._contexts.get(context) or {}
            if settings.get("action") == MIC_GROUP:
                self._switch_group(context)
            else:
                self._toggle_mute(context)
        elif event == "propertyInspectorDidAppear":
            # Pushed, not waited for. The panel asks once when its webview is
            # built, which can be long before anyone looks at it, and a reply
            # that arrives while it is still loading -- or is missed because
            # the webview was rebuilt on the way to being shown -- leaves a
            # dropdown reading "Loading…" with nothing to retry it. This
            # event fires exactly when the panel is on screen, so answering
            # it unprompted makes the lists correct at the only moment they
            # are being read.
            self._send("sendToPropertyInspector", context,
                       self._inspector_payload(
                           message.get("action")
                           or (self._contexts.get(context) or {}).get("action")
                           or VOLUME))
        elif event == "sendToPlugin":
            if payload.get("debug"):
                log.info("PI[%s] %s", context, payload["debug"])
                return
            # The inspector asks what to offer; the lists are whatever
            # OpenWave currently has, never a hardcoded set.
            action = (payload.get("action")
                      or message.get("action")
                      or (self._contexts.get(context) or {}).get("action")
                      or VOLUME)
            self._send("sendToPropertyInspector", context,
                       self._inspector_payload(action))

    # ---------------------------------------------------------------- loop
    def run(self):
        while True:
            try:
                ready, _, _ = select.select([self._ws], [], [], 0.25)
                if ready:
                    raw = self._ws.receive()
                    if raw:
                        log.debug("<- %s", raw[:400])
                        try:
                            self._handle(json.loads(raw))
                        except Exception:          # noqa: BLE001
                            log.exception("handler failed: %s", raw[:200])
                now = time.monotonic()
                if now - self._last_refresh >= REFRESH_SECONDS:
                    self._last_refresh = now
                    self._render_all()
            except ConnectionError as exc:
                log.error("connection lost: %s", exc)
                return
            except Exception:                      # noqa: BLE001
                log.exception("loop iteration failed; continuing")
                time.sleep(0.25)


def main():
    args = {}
    argv = sys.argv[1:]
    for i in range(0, len(argv) - 1, 2):
        args[argv[i].lstrip("-")] = argv[i + 1]
    port = args.get("port")
    uuid = args.get("pluginUUID")
    register_event = args.get("registerEvent", "registerPlugin")
    if not port or not uuid:
        log.error("missing -port/-pluginUUID; got %s", argv)
        return 1
    try:
        Plugin(int(port), uuid, register_event).run()
    except Exception:                              # noqa: BLE001
        log.exception("fatal")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
