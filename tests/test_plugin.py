"""The plugin's decisions, without a Stream Deck or a running OpenWave.

Everything that talks to the outside -- pactl, the session bus, OpenWave's
config -- is replaced, so these cover the parts that are actually easy to get
wrong: which target a settings blob names, what gets drawn for each state, and
whether a press reaches the right subsystem.
"""

import json
import os
import sys
import unittest

PLUGIN_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "dev.openwave.sdPlugin",
)
sys.path.insert(0, PLUGIN_DIR)

import plugin as P                                          # noqa: E402
from owdeck import graph, ipc, owstate, render               # noqa: E402


SNAPSHOT = {
    "groups": ["Mic"],
    "sources": [
        {"id": "dock", "name": "XLR Dock", "level": 0.8, "muted": False,
         "group": "Mic", "kind": "device"},
        {"id": "arctis", "name": "Arctis", "level": 1.0, "muted": True,
         "group": "Mic", "kind": "device"},
        {"id": "music", "name": "Music", "level": 0.5, "muted": False,
         "group": "", "kind": "app"},
    ],
}

MIXES = {
    "personal": {"id": "personal", "name": "Personal Mix",
                 "sink": "openwave_personal_mix",
                 "icon_name": "audio-headphones-symbolic"},
    "chat": {"id": "chat", "name": "Chat Mix", "sink": "openwave_chat_mix",
             "icon_name": "system-users-symbolic"},
}


class FakeWS:
    def __init__(self):
        self.sent = []

    def send_json(self, message):
        self.sent.append(message)


class PluginCase(unittest.TestCase):
    """A Plugin wired to stubs, plus the bookkeeping to inspect what it sent."""

    def setUp(self):
        self.calls = []
        self.sinks = {"openwave_personal_mix": [1.0, False],
                      "openwave_chat_mix": [0.6, True]}
        self.snapshot = json.loads(json.dumps(SNAPSHOT))

        self._patched = []
        self._patch(owstate, "mixes", lambda: MIXES)
        self._patch(owstate, "mix_choices", lambda: [
            (i, m["name"], m["sink"]) for i, m in MIXES.items()])
        self._patch(owstate, "mix_sink",
                    lambda i: (MIXES.get(i) or {}).get("sink"))
        self._patch(owstate, "mix_name",
                    lambda i, d=None: (MIXES.get(i) or {}).get("name", i))
        self._patch(graph, "sink_exists", lambda n: n in self.sinks)
        self._patch(graph, "get_volume",
                    lambda n: self.sinks[n][0] if n in self.sinks else None)
        self._patch(graph, "get_mute",
                    lambda n: self.sinks[n][1] if n in self.sinks else None)
        self._patch(graph, "set_volume", self._set_volume)
        self._patch(graph, "toggle_mute", self._toggle_mute)
        self._patch(graph, "default_sink", lambda: "openwave_personal_mix")
        self._patch(ipc, "snapshot", lambda: self.snapshot)
        self._patch(ipc, "set_source_level", self._set_source_level)
        self._patch(ipc, "toggle_source_mute", self._toggle_source_mute)
        self._patch(ipc, "switch_group", self._switch_group)

        self.ws = FakeWS()
        self.plugin = P.Plugin.__new__(P.Plugin)
        self.plugin._ws = self.ws
        self.plugin._uuid = "test"
        self.plugin._contexts = {}
        self.plugin._drawn = {}
        self.plugin._last_refresh = 0.0
        self.plugin._snapshot = None
        self.plugin._snapshot_at = 0.0

    def tearDown(self):
        for module, name, original in reversed(self._patched):
            setattr(module, name, original)

    def _patch(self, module, name, replacement):
        self._patched.append((module, name, getattr(module, name)))
        setattr(module, name, replacement)

    # -- stub behaviours --------------------------------------------------
    def _set_volume(self, name, value):
        self.calls.append(("sink-volume", name, round(value, 3)))
        self.sinks[name][0] = max(0.0, min(1.0, value))

    def _toggle_mute(self, name):
        self.calls.append(("sink-mute", name))
        self.sinks[name][1] = not self.sinks[name][1]

    def _source(self, source_id):
        return next(s for s in self.snapshot["sources"]
                    if s["id"] == source_id)

    def _set_source_level(self, source_id, level):
        self.calls.append(("src-level", source_id, round(level, 3)))
        self._source(source_id)["level"] = level
        return True

    def _toggle_source_mute(self, source_id):
        self.calls.append(("src-mute", source_id))
        source = self._source(source_id)
        source["muted"] = not source["muted"]
        return source["muted"]

    def _switch_group(self, group):
        self.calls.append(("switch", group))
        members = [s for s in self.snapshot["sources"] if s["group"] == group]
        live = next((i for i, s in enumerate(members) if not s["muted"]), -1)
        for source in members:
            source["muted"] = True
        members[(live + 1) % len(members)]["muted"] = False
        return True

    # -- helpers ----------------------------------------------------------
    def place(self, context, action, settings, controller="Keypad"):
        self.plugin._handle({
            "event": "willAppear", "context": context, "action": action,
            "payload": {"controller": controller, "settings": settings},
        })
        self.ws.sent.clear()

    def press(self, context):
        self.plugin._handle({"event": "keyDown", "context": context})

    def events(self, name):
        return [m for m in self.ws.sent if m["event"] == name]


class TestParseTarget(unittest.TestCase):
    def test_target_forms(self):
        self.assertEqual(P.parse_target({"target": "mix:chat"}),
                         ("mix", "chat"))
        self.assertEqual(P.parse_target({"target": "src:music"}),
                         ("src", "music"))

    def test_settings_written_before_targets_still_resolve(self):
        """A key placed by an earlier build named its mix directly."""
        self.assertEqual(P.parse_target({"mix": "chat"}), ("mix", "chat"))

    def test_nothing_chosen(self):
        self.assertEqual(P.parse_target({}), (None, None))
        self.assertEqual(P.parse_target({"target": ""}), (None, None))
        self.assertEqual(P.parse_target({"target": "mix:"}), (None, None))
        self.assertEqual(P.parse_target({"target": "bogus:x"}), (None, None))

    def test_the_empty_legacy_key_does_not_win(self):
        """Choosing a source clears `mix`; an empty one must not resurrect it."""
        self.assertEqual(P.parse_target({"target": "src:music", "mix": ""}),
                         ("src", "music"))


class TestReadingState(PluginCase):
    def test_mix(self):
        state = self.plugin._read({"target": "mix:chat"})
        self.assertEqual(state["name"], "Chat Mix")
        self.assertEqual(state["percent"], 60)
        self.assertTrue(state["muted"])
        self.assertTrue(state["ok"])

    def test_mix_icon_follows_openwave(self):
        self.assertEqual(
            self.plugin._read({"target": "mix:personal"})["glyph"],
            "headphones")

    def test_device_source_gets_a_microphone(self):
        state = self.plugin._read({"target": "src:dock"})
        self.assertEqual(state["glyph"], "mic")
        self.assertEqual(state["percent"], 80)

    def test_application_source_gets_a_speaker(self):
        self.assertEqual(self.plugin._read({"target": "src:music"})["glyph"],
                         "speaker")

    def test_mix_routed_nowhere_is_unavailable_not_an_error(self):
        self.sinks.pop("openwave_chat_mix")
        state = self.plugin._read({"target": "mix:chat"})
        self.assertFalse(state["ok"])
        self.assertEqual(state["name"], "Chat Mix")

    def test_source_with_openwave_closed(self):
        self.snapshot = None
        self.plugin._snapshot_at = 0.0
        self.assertFalse(self.plugin._read({"target": "src:dock"})["ok"])

    def test_no_target(self):
        self.assertIsNone(self.plugin._read({}))


class TestAdjusting(PluginCase):
    def test_rotating_a_mix_moves_its_sink(self):
        self.place("c", P.VOLUME, {"target": "mix:chat"})
        self.plugin._handle({"event": "dialRotate", "context": "c",
                             "payload": {"ticks": -5}})
        self.assertIn(("sink-volume", "openwave_chat_mix", 0.5), self.calls)

    def test_rotating_a_source_goes_through_openwave(self):
        """Never written to sources.json directly: OpenWave rewrites it whole."""
        self.place("c", P.VOLUME, {"target": "src:music"})
        self.plugin._handle({"event": "dialRotate", "context": "c",
                             "payload": {"ticks": 5}})
        self.assertIn(("src-level", "music", 0.6), self.calls)

    def test_level_is_clamped(self):
        self.place("c", P.VOLUME, {"target": "mix:personal"})
        self.plugin._handle({"event": "dialRotate", "context": "c",
                             "payload": {"ticks": 40}})
        self.assertIn(("sink-volume", "openwave_personal_mix", 1.0),
                      self.calls)

    def test_an_unreadable_target_is_left_alone(self):
        self.sinks.pop("openwave_chat_mix")
        self.place("c", P.VOLUME, {"target": "mix:chat"})
        self.plugin._handle({"event": "dialRotate", "context": "c",
                             "payload": {"ticks": -5}})
        self.assertEqual(self.calls, [])


class TestPressing(PluginCase):
    def test_press_mutes_a_mix(self):
        self.place("c", P.VOLUME, {"target": "mix:personal"})
        self.press("c")
        self.assertIn(("sink-mute", "openwave_personal_mix"), self.calls)

    def test_press_mutes_a_source_through_openwave(self):
        self.place("c", P.VOLUME, {"target": "src:music"})
        self.press("c")
        self.assertIn(("src-mute", "music"), self.calls)

    def test_dial_press_mutes_too(self):
        self.place("c", P.VOLUME, {"target": "mix:personal"},
                   controller="Encoder")
        self.plugin._handle({"event": "dialDown", "context": "c"})
        self.assertIn(("sink-mute", "openwave_personal_mix"), self.calls)

    def test_press_with_nothing_chosen_says_so(self):
        self.place("c", P.VOLUME, {})
        self.press("c")
        self.assertTrue(self.events("showAlert"))

    def test_press_switches_a_microphone_group(self):
        self.place("g", P.MIC_GROUP, {"group": "Mic"})
        self.press("g")
        self.assertIn(("switch", "Mic"), self.calls)
        self.assertEqual(self.plugin._group_state("Mic")[0], "Arctis")

    def test_group_press_with_openwave_closed_says_so(self):
        self.place("g", P.MIC_GROUP, {"group": "Mic"})
        ipc.switch_group = lambda group: False
        self.press("g")
        self.assertTrue(self.events("showAlert"))


class TestGroupState(PluginCase):
    def test_reports_the_live_microphone_and_its_position(self):
        self.assertEqual(self.plugin._group_state("Mic"), ("XLR Dock", 2, 1))

    def test_all_muted(self):
        for source in self.snapshot["sources"]:
            source["muted"] = True
        self.assertEqual(self.plugin._group_state("Mic"), ("", 2, 0))

    def test_openwave_closed(self):
        self.snapshot = None
        self.plugin._snapshot_at = 0.0
        self.assertIsNone(self.plugin._group_state("Mic"))


class TestDrawing(PluginCase):
    def test_a_key_is_drawn_as_an_svg_data_uri(self):
        self.plugin._handle({
            "event": "willAppear", "context": "c", "action": P.VOLUME,
            "payload": {"controller": "Keypad",
                        "settings": {"target": "mix:chat"}},
        })
        image = self.events("setImage")[0]["payload"]["image"]
        self.assertTrue(image.startswith("data:image/svg+xml;base64,"))

    def test_the_title_is_cleared_because_the_image_carries_it(self):
        self.place("c", P.VOLUME, {"target": "mix:chat"})
        self.plugin._render("c")
        # Nothing changed, so nothing is resent; force a redraw to see it.
        self.plugin._drawn.clear()
        self.plugin._render("c")
        self.assertEqual(self.events("setTitle")[0]["payload"]["title"], "")

    def test_an_unchanged_key_is_not_redrawn(self):
        """The deck repaints on receipt, so a key resent every tick flickers."""
        self.place("c", P.VOLUME, {"target": "mix:chat"})
        self.plugin._render("c")
        self.assertEqual(self.events("setImage"), [])

    def test_a_changed_level_is_redrawn(self):
        self.place("c", P.VOLUME, {"target": "mix:personal"})
        self.sinks["openwave_personal_mix"][0] = 0.2
        self.plugin._render("c")
        self.assertEqual(len(self.events("setImage")), 1)

    def test_a_level_change_under_a_mute_is_not_redrawn(self):
        """A muted key shows MUTED, not a number, so it has not changed."""
        self.place("c", P.VOLUME, {"target": "mix:chat"})
        self.sinks["openwave_chat_mix"][0] = 0.2
        self.plugin._render("c")
        self.assertEqual(self.events("setImage"), [])

    def test_changing_the_target_forces_a_redraw(self):
        self.place("c", P.VOLUME, {"target": "mix:chat"})
        self.plugin._handle({
            "event": "didReceiveSettings", "context": "c", "action": P.VOLUME,
            "payload": {"controller": "Keypad",
                        "settings": {"target": "mix:personal"}},
        })
        self.assertEqual(len(self.events("setImage")), 1)

    def test_an_encoder_loads_a_layout_before_it_sends_feedback(self):
        self.plugin._handle({
            "event": "willAppear", "context": "e", "action": P.VOLUME,
            "payload": {"controller": "Encoder",
                        "settings": {"target": "mix:personal"}},
        })
        names = [m["event"] for m in self.ws.sent]
        self.assertIn("setFeedbackLayout", names)
        self.assertLess(names.index("setFeedbackLayout"),
                        names.index("setFeedback"))

    def test_encoder_feedback_uses_the_layout_keys(self):
        self.plugin._handle({
            "event": "willAppear", "context": "e", "action": P.VOLUME,
            "payload": {"controller": "Encoder",
                        "settings": {"target": "mix:chat"}},
        })
        feedback = self.events("setFeedback")[0]["payload"]
        # $A0 names exactly these; a key it does not define is rejected.
        self.assertEqual(set(feedback), {"full-canvas", "title"})
        self.assertTrue(feedback["full-canvas"].startswith(
            "data:image/svg+xml;base64,"))
        # The canvas carries the name, so the layout's own title is cleared
        # rather than drawn over the top of it.
        self.assertEqual(feedback["title"], "")

    def test_an_encoder_is_sent_no_key_image(self):
        """OpenDeck routes setImage into the layout's icon slot, which put a
        shrunken copy of a whole key inside the touch strip."""
        self.plugin._handle({
            "event": "willAppear", "context": "e", "action": P.VOLUME,
            "payload": {"controller": "Encoder",
                        "settings": {"target": "mix:chat"}},
        })
        self.assertEqual(self.events("setImage"), [])

    def test_a_keypad_sends_no_feedback(self):
        self.place("c", P.VOLUME, {"target": "mix:chat"})
        self.plugin._drawn.clear()
        self.plugin._render("c")
        self.assertEqual(self.events("setFeedback"), [])

    def test_forgetting_a_key_forgets_what_was_drawn_on_it(self):
        self.place("c", P.VOLUME, {"target": "mix:chat"})
        self.plugin._handle({"event": "willDisappear", "context": "c"})
        self.assertEqual(self.plugin._drawn, {})
        self.assertEqual(self.plugin._contexts, {})


class TestInspectorPayload(PluginCase):
    def test_mixes_and_sources_are_offered_together(self):
        payload = self.plugin._inspector_payload(P.VOLUME)
        values = [t["value"] for t in payload["targets"]]
        self.assertIn("mix:personal", values)
        self.assertIn("src:dock", values)
        self.assertIn("src:music", values)

    def test_microphones_are_separated_from_application_sources(self):
        payload = self.plugin._inspector_payload(P.VOLUME)
        groups = {t["value"]: t["group"] for t in payload["targets"]}
        self.assertEqual(groups["src:dock"], "Microphones")
        self.assertEqual(groups["src:music"], "Sources")
        self.assertEqual(groups["mix:chat"], "Mixes")

    def test_the_system_output_is_flagged(self):
        """Muting it silences the machine, not just OpenWave."""
        payload = self.plugin._inspector_payload(P.VOLUME)
        flagged = [t["value"] for t in payload["targets"] if t["isDefault"]]
        self.assertEqual(flagged, ["mix:personal"])

    def test_mixes_are_still_offered_with_openwave_closed(self):
        self.snapshot = None
        self.plugin._snapshot_at = 0.0
        payload = self.plugin._inspector_payload(P.VOLUME)
        self.assertFalse(payload["openwave"])
        self.assertTrue([t for t in payload["targets"]
                         if t["value"].startswith("mix:")])
        self.assertFalse([t for t in payload["targets"]
                          if t["value"].startswith("src:")])

    def test_group_inspector(self):
        payload = self.plugin._inspector_payload(P.MIC_GROUP)
        self.assertEqual(payload["groups"], ["Mic"])
        self.assertTrue(payload["openwave"])


class TestRendering(unittest.TestCase):
    def test_keys_are_well_formed_svg(self):
        import xml.etree.ElementTree as ET
        for svg in (
            render.strip("Personal Mix", 100, False, "headphones"),
            render.strip("XLR Dock", 0, True, "mic"),
            render.strip("Nothing", 0, False, unavailable=True),
            render.level_key("Personal Mix", 72, False, "headphones"),
            render.level_key("XLR Dock", 100, True, "mic"),
            render.level_key("Gone", 0, False, unavailable=True),
            render.group_key("Mic", "XLR Dock", 2, 1),
            render.group_key("Mic", "", 2),
            render.group_key("Mic", "", 0, unavailable=True),
            render.unconfigured_key("Pick a mix", "or a source"),
        ):
            ET.fromstring(svg)

    def test_muting_recolours_the_key(self):
        self.assertIn(render.MUTED, render.level_key("A", 50, True))
        self.assertNotIn(render.MUTED, render.level_key("A", 50, False))

    def test_a_live_microphone_group_is_green(self):
        self.assertIn(render.MIC_LIVE, render.group_key("Mic", "Dock", 2, 1))
        self.assertIn(render.MUTED, render.group_key("Mic", "", 2))

    def test_names_too_long_for_a_key_are_truncated(self):
        svg = render.level_key("Arctis Nova Pro Wireless Mono", 50, False)
        self.assertIn("…", svg)

    def test_markup_in_a_name_cannot_break_the_document(self):
        import xml.etree.ElementTree as ET
        root = ET.fromstring(render.level_key('<b>&"x', 50, False))
        self.assertTrue(any("<b>&" in (e.text or "") for e in root.iter()))

    def test_long_names_wrap_instead_of_being_cut(self):
        """"Arctis Nov…" identifies nothing; two lines identify the device."""
        self.assertEqual(render._wrap("Arctis Nova Pro Wireless Mono", 12),
                         ["Arctis Nova", "Pro Wireles…"])

    def test_a_short_name_stays_on_one_line(self):
        self.assertEqual(render._wrap("XLR Dock", 12), ["XLR Dock"])

    def test_a_single_unbreakable_word_is_truncated(self):
        self.assertEqual(render._wrap("Supercalifragilistic", 12),
                         ["Supercalifr…"])

    def test_the_strip_is_the_whole_touch_canvas(self):
        svg = render.strip("System", 65, False)
        self.assertIn('width="200"', svg)
        self.assertIn('height="100"', svg)

    def test_data_uri_is_what_opendeck_accepts(self):
        uri = render.data_uri(render.level_key("A", 50, False))
        self.assertTrue(uri.startswith("data:image/svg+xml;base64,"))


if __name__ == "__main__":
    unittest.main()
