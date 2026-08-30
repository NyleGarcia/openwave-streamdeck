"""OpenWave plugin for OpenDeck.

One process. It speaks OpenDeck's WebSocket protocol and drives PipeWire
through pactl/wpctl; there is no sandbox to cross and nothing that needs to
outlive the plugin, so a second process would buy nothing.

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

from owdeck import graph, ipc, owstate     # noqa: E402
from owdeck.ws import WebSocket            # noqa: E402

LOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "plugin.log")
logging.basicConfig(
    filename=LOG_PATH, level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("openwave-deck")

MIX_LEVEL = "dev.openwave.mixlevel"
MIC_GROUP = "dev.openwave.micgroup"

# How far one dial detent moves a level. Small enough to land on a value,
# large enough to cross the range without a long spin.
STEP = 0.02
# Keys and dials are refreshed on this cadence so a change made in OpenWave's
# window, or by anything else touching the graph, shows up without the user
# having to touch the deck first.
REFRESH_SECONDS = 1.0


class Plugin:
    def __init__(self, port, uuid, register_event):
        self._ws = WebSocket(port, timeout=1.0)
        self._uuid = uuid
        self._ws.send_json({"event": register_event, "uuid": uuid})
        log.info("registered as %s on port %s", uuid, port)
        # context -> settings, for every visible instance of our actions
        self._contexts = {}
        self._last_refresh = 0.0

    # ------------------------------------------------------------ outbound
    def _send(self, event, context, payload=None):
        message = {"event": event, "context": context}
        if payload is not None:
            message["payload"] = payload
        try:
            self._ws.send_json(message)
        except (OSError, ConnectionError) as exc:
            log.warning("send %s failed: %s", event, exc)

    def _render(self, context):
        """Draw one instance from live audio state."""
        settings = self._contexts.get(context) or {}
        if settings.get("action") == MIC_GROUP:
            self._render_group(context, settings)
            return
        mix_id = settings.get("mix")
        if not mix_id:
            self._send("setTitle", context, {"title": "Pick\na mix"})
            return
        sink = owstate.mix_sink(mix_id)
        name = owstate.mix_name(mix_id)
        if not sink or not graph.sink_exists(sink):
            # A mix routed nowhere has no sink at all, which is a normal
            # state in OpenWave rather than an error.
            self._send("setTitle", context, {"title": f"{name}\n--"})
            return
        volume = graph.get_volume(sink)
        muted = graph.get_mute(sink)
        percent = 0 if volume is None else round(volume * 100)
        title = f"{name}\n{'MUTE' if muted else f'{percent}%'}"
        self._send("setTitle", context, {"title": title})
        if settings.get("controller") == "Encoder":
            self._send("setFeedback", context, {
                "title": name,
                "value": "MUTE" if muted else f"{percent}%",
                "indicator": {"value": percent, "opacity": 0.4 if muted else 1.0},
            })

    def _render_group(self, context, settings):
        group = settings.get("group")
        if not group:
            self._send("setTitle", context, {"title": "Pick\na group"})
            return
        live = ""
        for source in owstate.sources().values():
            if (source.get("group") or "").strip() == group \
                    and not source.get("muted"):
                live = source.get("name", "")
                break
        # The live microphone's name is the useful thing on the key, not the
        # group's: the group is what you chose when you placed it.
        self._send("setTitle", context, {
            "title": f"{group}\n{live or '--'}",
        })

    def _render_all(self):
        for context in list(self._contexts):
            try:
                self._render(context)
            except Exception:                      # noqa: BLE001
                log.exception("render failed for %s", context)

    # ------------------------------------------------------------- actions
    def _adjust(self, context, ticks):
        settings = self._contexts.get(context) or {}
        sink = owstate.mix_sink(settings.get("mix", ""))
        if not sink:
            return
        current = graph.get_volume(sink)
        if current is None:
            return
        graph.set_volume(sink, current + ticks * STEP)
        self._render(context)

    def _switch_group(self, context):
        settings = self._contexts.get(context) or {}
        group = settings.get("group")
        if not group:
            return
        if not ipc.switch_group(group):
            # OpenWave owns which microphone is live; with it closed there is
            # nothing to switch, and saying so beats a key that looks dead.
            self._send("showAlert", context)
            return
        self._render(context)

    def _toggle_mute(self, context):
        settings = self._contexts.get(context) or {}
        sink = owstate.mix_sink(settings.get("mix", ""))
        if not sink:
            return
        graph.toggle_mute(sink)
        self._render(context)

    # ------------------------------------------------------------- inbound
    def _handle(self, message):
        event = message.get("event")
        context = message.get("context")
        payload = message.get("payload") or {}

        if event in ("willAppear", "didReceiveSettings"):
            settings = dict(payload.get("settings") or {})
            settings["controller"] = payload.get("controller", "Keypad")
            settings["action"] = message.get("action", MIX_LEVEL)
            self._contexts[context] = settings
            self._render(context)
        elif event == "willDisappear":
            self._contexts.pop(context, None)
        elif event == "dialRotate":
            self._adjust(context, int(payload.get("ticks", 0)))
        elif event in ("dialDown", "keyDown", "touchTap"):
            settings = self._contexts.get(context) or {}
            if settings.get("action") == MIC_GROUP:
                self._switch_group(context)
            else:
                self._toggle_mute(context)
        elif event == "sendToPlugin" or event == "propertyInspectorDidAppear":
            # The inspector asks what to offer; the mix list is whatever
            # OpenWave currently has, never a hardcoded set.
            if (payload.get("request") == "groups"
                    or message.get("action") == MIC_GROUP):
                self._send("sendToPropertyInspector", context, {
                    "groups": ipc.source_groups(),
                    "openwave": ipc.available(),
                })
                return
            default = graph.default_sink()
            self._send("sendToPropertyInspector", context, {
                "mixes": [
                    {
                        "id": mix_id,
                        "label": label,
                        # The monitoring mix is normally the system default
                        # sink, so its master is the machine's volume. The
                        # inspector says so rather than letting someone find
                        # out by muting everything.
                        "isDefault": sink == default,
                    }
                    for mix_id, label, sink in owstate.mix_choices()
                ],
            })

    # ---------------------------------------------------------------- loop
    def run(self):
        while True:
            try:
                ready, _, _ = select.select([self._ws], [], [], 0.25)
                if ready:
                    raw = self._ws.receive()
                    if raw:
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
