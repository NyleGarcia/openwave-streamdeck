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
    "mixes": [
        {"id": "personal", "name": "Personal Mix",
         "sink": "openwave_personal_mix"},
        {"id": "chat", "name": "Chat Mix", "sink": "openwave_chat_mix"},
    ],
    "cells": {
        "dock.personal": {"volume": 0.0, "muted": False},
        "dock.chat": {"volume": 0.68, "muted": False},
        "music.personal": {"volume": 0.55, "muted": False},
        "music.chat": {"volume": 0.3, "muted": True},
    },
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
        self._patch(ipc, "set_cell_level", self._set_cell_level)
        self._patch(ipc, "toggle_cell_mute", self._toggle_cell_mute)
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
        self.plugin._theme = render.DEFAULT_THEME
        render.set_theme(render.DEFAULT_THEME)

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

    def _set_cell_level(self, source_id, mix_id, level):
        self.calls.append(("cell-level", source_id, mix_id, round(level, 3)))
        self.snapshot["cells"][f"{source_id}.{mix_id}"]["volume"] = level
        return True

    def _toggle_cell_mute(self, source_id, mix_id):
        self.calls.append(("cell-mute", source_id, mix_id))
        cell = self.snapshot["cells"][f"{source_id}.{mix_id}"]
        cell["muted"] = not cell["muted"]
        return cell["muted"]

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

    def test_a_send_names_both_halves(self):
        self.assertEqual(P.parse_target({"target": "cell:music:chat"}),
                         ("cell", "music:chat"))
        self.assertEqual(P.split_cell("music:chat"), ("music", "chat"))

    def test_a_half_written_send_is_not_a_target(self):
        """Acting on "cell:music" would need a mix it does not have."""
        self.assertEqual(P.parse_target({"target": "cell:music"}),
                         (None, None))
        self.assertEqual(P.parse_target({"target": "cell:music:"}),
                         (None, None))
        self.assertEqual(P.parse_target({"target": "cell::chat"}),
                         (None, None))
        self.assertEqual(P.parse_target({"target": "cell:a:b:c"}),
                         (None, None))

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


class TestReadingCells(PluginCase):
    def test_a_send_reads_its_own_level(self):
        state = self.plugin._read({"target": "cell:dock:chat"})
        self.assertEqual(state["percent"], 68)
        self.assertFalse(state["muted"])

    def test_a_send_is_labelled_with_its_mix(self):
        """Two sends from one source differ only by where they go, so the key
        has to say which; the source name alone is ambiguous."""
        state = self.plugin._read({"target": "cell:dock:chat"})
        self.assertEqual(state["name"], "XLR Dock")
        self.assertEqual(state["context"], "Chat Mix")

    def test_a_send_is_not_the_row_trim(self):
        """dock's trim is 0.8 and its send into chat is 0.68: reading one for
        the other would look plausible and be wrong."""
        self.assertEqual(self.plugin._read({"target": "src:dock"})["percent"],
                         80)
        self.assertEqual(
            self.plugin._read({"target": "cell:dock:chat"})["percent"], 68)

    def test_a_send_keeps_its_source_glyph(self):
        self.assertEqual(
            self.plugin._read({"target": "cell:dock:chat"})["glyph"], "mic")
        self.assertEqual(
            self.plugin._read({"target": "cell:music:chat"})["glyph"],
            "speaker")

    def test_a_send_to_a_deleted_mix_is_unavailable(self):
        self.snapshot["mixes"] = [self.snapshot["mixes"][0]]
        self.plugin._snapshot_at = 0.0
        self.assertFalse(
            self.plugin._read({"target": "cell:dock:chat"})["ok"])

    def test_a_send_with_openwave_closed_is_unavailable(self):
        self.snapshot = None
        self.plugin._snapshot_at = 0.0
        self.assertFalse(
            self.plugin._read({"target": "cell:dock:chat"})["ok"])


class TestAdjustingCells(PluginCase):
    def test_rotating_a_send_goes_through_openwave(self):
        """Sends are re-applied on every reconcile, so a value written any
        other way is undone within a second."""
        self.place("c", P.VOLUME, {"target": "cell:dock:chat"})
        self.plugin._handle({"event": "dialRotate", "context": "c",
                             "payload": {"ticks": 5}})
        self.assertIn(("cell-level", "dock", "chat", 0.78), self.calls)

    def test_pressing_a_send_mutes_only_that_cell(self):
        self.place("c", P.VOLUME, {"target": "cell:dock:chat"})
        self.press("c")
        self.assertIn(("cell-mute", "dock", "chat"), self.calls)
        self.assertNotIn(("src-mute", "dock"), self.calls)

    def test_a_send_on_a_missing_mix_is_left_alone(self):
        self.snapshot["mixes"] = []
        self.plugin._snapshot_at = 0.0
        self.place("c", P.VOLUME, {"target": "cell:dock:chat"})
        self.plugin._handle({"event": "dialRotate", "context": "c",
                             "payload": {"ticks": 5}})
        self.assertEqual(self.calls, [])


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


class TestPressBehaviour(PluginCase):
    """A key only presses, so what a press does is the whole control."""

    def test_a_press_mutes_by_default(self):
        self.place("c", P.VOLUME, {"target": "mix:personal"})
        self.press("c")
        self.assertIn(("sink-mute", "openwave_personal_mix"), self.calls)

    def test_a_key_can_turn_up_instead(self):
        self.place("c", P.VOLUME,
                   {"target": "mix:chat", "press": "up", "step": 5})
        self.press("c")
        self.assertIn(("sink-volume", "openwave_chat_mix", 0.65), self.calls)
        self.assertNotIn(("sink-mute", "openwave_chat_mix"), self.calls)

    def test_a_key_can_turn_down(self):
        self.place("c", P.VOLUME,
                   {"target": "mix:chat", "press": "down", "step": 10})
        self.press("c")
        self.assertIn(("sink-volume", "openwave_chat_mix", 0.5), self.calls)

    def test_stepping_a_source_goes_through_openwave(self):
        self.place("c", P.SOURCE_LEVEL,
                   {"target": "src:music", "press": "up", "step": 20})
        self.press("c")
        self.assertIn(("src-level", "music", 0.7), self.calls)

    def test_stepping_a_send_goes_through_openwave(self):
        self.place("c", P.SEND_LEVEL,
                   {"target": "cell:dock:chat", "press": "down", "step": 8})
        self.press("c")
        self.assertIn(("cell-level", "dock", "chat", 0.6), self.calls)

    def test_a_dial_rotates_by_the_same_step(self):
        """One setting, not two: a dial and its press should not disagree."""
        self.place("c", P.VOLUME,
                   {"target": "mix:chat", "step": 25}, controller="Encoder")
        self.plugin._handle({"event": "dialRotate", "context": "c",
                             "payload": {"ticks": 1}})
        self.assertIn(("sink-volume", "openwave_chat_mix", 0.85), self.calls)

    def test_stepping_stops_at_the_top(self):
        self.place("c", P.VOLUME,
                   {"target": "mix:personal", "press": "up", "step": 25})
        self.press("c")
        self.assertIn(("sink-volume", "openwave_personal_mix", 1.0),
                      self.calls)

    def test_an_unreadable_target_is_not_stepped(self):
        self.sinks.pop("openwave_chat_mix")
        self.place("c", P.VOLUME, {"target": "mix:chat", "press": "up"})
        self.press("c")
        self.assertEqual(self.calls, [])

    def test_a_stepping_key_says_which_way_and_by_how_much(self):
        """Three keys on one source differ only in what pressing them does,
        and the level they all show is identical."""
        import base64
        self.place("c", P.VOLUME,
                   {"target": "mix:chat", "press": "up", "step": 5})
        self.plugin._drawn.clear()
        self.plugin._render("c")
        uri = self.events("setImage")[0]["payload"]["image"]
        svg = base64.b64decode(uri.split(",", 1)[1]).decode()
        self.assertIn("+5", svg)

    def test_a_muting_key_carries_no_step_badge(self):
        import base64
        self.place("c", P.VOLUME, {"target": "mix:personal", "step": 5})
        self.plugin._drawn.clear()
        self.plugin._render("c")
        uri = self.events("setImage")[0]["payload"]["image"]
        svg = base64.b64decode(uri.split(",", 1)[1]).decode()
        self.assertNotIn("+5", svg)


class TestSettingsAreReadDefensively(unittest.TestCase):
    """Both arrive from inspector inputs, so neither can be trusted raw."""

    def test_press_falls_back_to_mute(self):
        for settings in ({}, {"press": ""}, {"press": "bogus"},
                         {"press": None}):
            self.assertEqual(P.press_action(settings), "mute")

    def test_step_is_clamped_and_coerced(self):
        self.assertEqual(P.step_percent({}), P.DEFAULT_STEP)
        self.assertEqual(P.step_percent({"step": "7"}), 7)
        self.assertEqual(P.step_percent({"step": ""}), P.DEFAULT_STEP)
        self.assertEqual(P.step_percent({"step": None}), P.DEFAULT_STEP)
        self.assertEqual(P.step_percent({"step": 0}), P.MIN_STEP)
        self.assertEqual(P.step_percent({"step": 999}), P.MAX_STEP)


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


class TestTheSplitActionsShareBehaviour(PluginCase):
    """Only the offered list differs; driving a target is the same code."""

    def test_a_source_key_on_the_source_action_still_mutes(self):
        self.place("c", P.SOURCE_LEVEL, {"target": "src:music"})
        self.press("c")
        self.assertIn(("src-mute", "music"), self.calls)

    def test_a_send_key_on_the_send_action_still_rotates(self):
        self.place("c", P.SEND_LEVEL, {"target": "cell:dock:chat"})
        self.plugin._handle({"event": "dialRotate", "context": "c",
                             "payload": {"ticks": 5}})
        self.assertIn(("cell-level", "dock", "chat", 0.78), self.calls)

    def test_an_old_key_holding_another_kind_still_works(self):
        """The UUID that used to hold every kind keeps driving what it has."""
        self.place("c", P.VOLUME, {"target": "src:music"})
        self.press("c")
        self.assertIn(("src-mute", "music"), self.calls)

    def test_each_action_prompts_for_its_own_kind(self):
        import base64
        seen = {}
        for action in (P.VOLUME, P.SOURCE_LEVEL, P.SEND_LEVEL):
            self.plugin._handle({
                "event": "willAppear", "context": action, "action": action,
                "payload": {"controller": "Keypad", "settings": {}},
            })
            uri = [m for m in self.ws.sent if m["event"] == "setImage"
                   and m["context"] == action][0]["payload"]["image"]
            seen[action] = base64.b64decode(uri.split(",", 1)[1]).decode()
        self.assertIn("Pick a mix", seen[P.VOLUME])
        self.assertIn("Pick a source", seen[P.SOURCE_LEVEL])
        self.assertIn("Pick a source", seen[P.SEND_LEVEL])
        self.assertIn("and a mix", seen[P.SEND_LEVEL])


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
        self.assertEqual(
            self.events("setFeedbackLayout")[0]["payload"]["layout"],
            "layouts/strip.json")
        self.assertLess(names.index("setFeedbackLayout"),
                        names.index("setFeedback"))

    def test_encoder_feedback_uses_the_layout_keys(self):
        self.plugin._handle({
            "event": "willAppear", "context": "e", "action": P.VOLUME,
            "payload": {"controller": "Encoder",
                        "settings": {"target": "mix:chat"}},
        })
        feedback = self.events("setFeedback")[0]["payload"]
        # Our layout defines exactly one item, and OpenDeck rejects a key it
        # does not define. Anything extra here would also be drawn over the
        # canvas, which is the whole reason the built-in layouts were dropped.
        self.assertEqual(set(feedback), {"canvas"})
        self.assertTrue(feedback["canvas"].startswith(
            "data:image/svg+xml;base64,"))

    def test_an_encoder_gets_both_a_strip_and_a_key_image(self):
        """The strip is what the hardware shows, but OpenDeck's editor draws a
        dial from its key image: an encoder sent only feedback appears there
        as the static manifest icon, identical for every dial whatever each is
        bound to. Sending the image is safe only because layouts/strip.json
        has no icon item for it to be routed into."""
        self.plugin._handle({
            "event": "willAppear", "context": "e", "action": P.VOLUME,
            "payload": {"controller": "Encoder",
                        "settings": {"target": "mix:chat"}},
        })
        self.assertEqual(len(self.events("setImage")), 1)
        self.assertEqual(len(self.events("setFeedback")), 1)

    def test_an_encoder_key_image_names_what_it_controls(self):
        self.plugin._handle({
            "event": "willAppear", "context": "e", "action": P.VOLUME,
            "payload": {"controller": "Encoder",
                        "settings": {"target": "cell:music:chat"}},
        })
        import base64
        uri = self.events("setImage")[0]["payload"]["image"]
        svg = base64.b64decode(uri.split(",", 1)[1]).decode()
        self.assertIn("Music", svg)
        self.assertIn("Chat Mix", svg)

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
    """Each action offers only its own kind, so no list is 31 entries long."""

    def values(self, action, settings=None):
        return [t["value"]
                for t in self.plugin._inspector_payload(action, settings)
                ["targets"]]

    def test_mix_volume_offers_only_mixes(self):
        values = self.values(P.VOLUME)
        self.assertIn("mix:personal", values)
        self.assertFalse([v for v in values if v.startswith(("src:", "cell:"))])

    def test_source_volume_offers_only_sources(self):
        values = self.values(P.SOURCE_LEVEL)
        self.assertIn("src:dock", values)
        self.assertIn("src:music", values)
        self.assertFalse([v for v in values if v.startswith(("mix:", "cell:"))])

    def test_per_mix_offers_two_lists_not_every_pairing(self):
        """Sources x mixes is 21 entries here and grows multiplicatively; the
        choice is genuinely two choices, so it is offered as two."""
        pair = self.plugin._inspector_payload(P.SEND_LEVEL)["pair"]
        self.assertEqual([m["id"] for m in pair["mixes"]],
                         ["personal", "chat"])
        self.assertEqual([s["id"] for s in pair["sources"]],
                         ["dock", "arctis", "music"])

    def test_per_mix_separates_microphones_from_sources(self):
        pair = self.plugin._inspector_payload(P.SEND_LEVEL)["pair"]
        groups = {s["id"]: s["group"] for s in pair["sources"]}
        self.assertEqual(groups["dock"], "Microphones")
        self.assertEqual(groups["music"], "Sources")

    def test_per_mix_reports_what_is_already_chosen(self):
        """Both dropdowns are preselected from it, so a panel reopened on a
        working key shows what that key does rather than two blanks."""
        pair = self.plugin._inspector_payload(
            P.SEND_LEVEL, {"target": "cell:music:chat"})["pair"]
        self.assertEqual(pair["chosen"], "cell:music:chat")

    def test_microphones_are_separated_from_application_sources(self):
        payload = self.plugin._inspector_payload(P.SOURCE_LEVEL)
        groups = {t["value"]: t["group"] for t in payload["targets"]}
        self.assertEqual(groups["src:dock"], "Microphones")
        self.assertEqual(groups["src:music"], "Sources")

    def test_the_trim_action_is_a_single_list(self):
        """Only the per-mix action pairs; a trim is one choice."""
        payload = self.plugin._inspector_payload(P.SOURCE_LEVEL)
        self.assertNotIn("pair", payload)
        self.assertEqual({t["value"]: t["label"]
                          for t in payload["targets"]}["src:music"], "Music")

    def test_the_system_output_is_flagged(self):
        """Muting it silences the machine, not just OpenWave."""
        payload = self.plugin._inspector_payload(P.VOLUME)
        flagged = [t["value"] for t in payload["targets"] if t["isDefault"]]
        self.assertEqual(flagged, ["mix:personal"])

    def test_a_target_from_before_the_split_is_kept(self):
        """A key placed when one action held every kind may carry a target
        this one would not offer. Dropping it from the list silently would
        read as the key having lost its setting."""
        settings = {"target": "src:music"}
        payload = self.plugin._inspector_payload(P.VOLUME, settings)
        kept = [t for t in payload["targets"] if t["value"] == "src:music"]
        self.assertEqual(len(kept), 1)
        self.assertEqual(kept[0]["group"], "Currently set")
        self.assertEqual(kept[0]["label"], "Music")

    def test_a_kept_send_says_where_it_goes(self):
        payload = self.plugin._inspector_payload(
            P.VOLUME, {"target": "cell:music:chat"})
        kept = next(t for t in payload["targets"]
                    if t["value"] == "cell:music:chat")
        self.assertEqual(kept["label"], "Music into Chat Mix")

    def test_a_target_of_the_right_kind_is_not_duplicated(self):
        values = self.values(P.VOLUME, {"target": "mix:chat"})
        self.assertEqual(values.count("mix:chat"), 1)

    def test_the_panel_is_told_what_the_key_already_has(self):
        """The plugin holds the authoritative settings, so it says what is
        chosen rather than leaving the panel to work it out from its own
        copy and risk the two disagreeing."""
        payload = self.plugin._inspector_payload(
            P.VOLUME, {"target": "mix:chat", "press": "down", "step": 15})
        self.assertEqual(payload["chosen"], "mix:chat")
        self.assertEqual(payload["press"], "down")
        self.assertEqual(payload["step"], 15)

    def test_each_action_explains_itself(self):
        for action in (P.VOLUME, P.SOURCE_LEVEL, P.SEND_LEVEL):
            self.assertTrue(
                self.plugin._inspector_payload(action)["hint"], action)

    def test_mixes_are_still_offered_with_openwave_closed(self):
        self.snapshot = None
        self.plugin._snapshot_at = 0.0
        payload = self.plugin._inspector_payload(P.VOLUME)
        self.assertFalse(payload["openwave"])
        self.assertTrue([t for t in payload["targets"]
                         if t["value"].startswith("mix:")])

    def test_nothing_is_offered_with_openwave_closed(self):
        self.snapshot = None
        self.plugin._snapshot_at = 0.0
        self.assertEqual(
            self.plugin._inspector_payload(P.SOURCE_LEVEL)["targets"], [])
        pair = self.plugin._inspector_payload(P.SEND_LEVEL)["pair"]
        self.assertEqual(pair["mixes"], [])
        self.assertEqual(pair["sources"], [])

    def test_group_inspector(self):
        payload = self.plugin._inspector_payload(P.MIC_GROUP)
        self.assertEqual(payload["groups"], ["Mic"])
        self.assertTrue(payload["openwave"])


class TestTheming(PluginCase):
    def tearDown(self):
        render.set_theme(render.DEFAULT_THEME)
        super().tearDown()

    def _global(self, theme):
        self.plugin._handle({
            "event": "didReceiveGlobalSettings", "context": None,
            "payload": {"settings": {"theme": theme}},
        })

    def test_a_theme_change_repaints_every_key(self):
        """Cached images were drawn in the old palette, so a change that did
        not clear the cache would land only on keys that happened to move."""
        self.place("a", P.VOLUME, {"target": "mix:personal"})
        self.place("b", P.VOLUME, {"target": "mix:chat"})
        self._global("contrast")
        painted = {m["context"] for m in self.events("setImage")}
        self.assertEqual(painted, {"a", "b"})

    def test_the_palette_actually_changes(self):
        import base64
        self.place("a", P.VOLUME, {"target": "mix:personal"})
        self._global("light")
        uri = self.events("setImage")[0]["payload"]["image"]
        svg = base64.b64decode(uri.split(",", 1)[1]).decode()
        self.assertIn(render.THEMES["light"]["bg"], svg)
        self.assertNotIn(render.THEMES["default"]["live"], svg)

    def test_an_unknown_theme_falls_back(self):
        self._global("chartreuse")
        self.assertEqual(self.plugin._theme, render.DEFAULT_THEME)

    def test_a_missing_theme_falls_back(self):
        self.plugin._handle({
            "event": "didReceiveGlobalSettings", "context": None,
            "payload": {"settings": {}},
        })
        self.assertEqual(self.plugin._theme, render.DEFAULT_THEME)

    def test_every_inspector_can_change_it(self):
        """Whichever key you happen to open, the setting is reachable."""
        for action in (P.VOLUME, P.SOURCE_LEVEL, P.SEND_LEVEL, P.MIC_GROUP):
            payload = self.plugin._inspector_payload(action)
            self.assertTrue(payload["themes"], action)
            self.assertEqual(payload["theme"], render.DEFAULT_THEME, action)


class TestThemeDefinitions(unittest.TestCase):
    def tearDown(self):
        render.set_theme(render.DEFAULT_THEME)

    def test_every_theme_defines_every_colour(self):
        """A theme missing a key would raise mid-draw, on a key already on a
        deck, with the plugin unable to report it."""
        expected = set(render.THEMES[render.DEFAULT_THEME])
        for name, theme in render.THEMES.items():
            self.assertEqual(set(theme), expected, name)

    def test_every_theme_renders_every_key(self):
        import xml.etree.ElementTree as ET
        for name in render.THEMES:
            render.set_theme(name)
            for svg in (
                render.level_key("Music", 55, False, context="Chat Mix"),
                render.level_key("Dock", 0, True, "mic"),
                render.level_key("Gone", 0, False, unavailable=True),
                render.group_key("Mic", "Dock", 2, 1),
                render.unconfigured_key("Pick a mix", "in settings"),
                render.strip("Music", 55, False, context="Chat Mix"),
            ):
                ET.fromstring(svg)

    def test_an_unknown_name_falls_back_rather_than_half_drawing(self):
        self.assertEqual(render.set_theme("nonsense"),
                         render.THEMES[render.DEFAULT_THEME]["name"])

    def test_the_light_theme_is_actually_light(self):
        """It exists to be readable on a bright desk; a copy of the dark one
        with a different accent would not be."""
        light, default = render.THEMES["light"], render.THEMES["default"]
        self.assertGreater(_luminance(light["bg"]), 0.5)
        self.assertLess(_luminance(light["text"]), 0.5)
        self.assertLess(_luminance(default["bg"]), 0.5)


def _luminance(colour):
    r, g, b = (int(colour[i:i + 2], 16) / 255 for i in (1, 3, 5))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


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
        muted = render.THEME["muted"]
        self.assertIn(muted, render.level_key("A", 50, True))
        self.assertNotIn(muted, render.level_key("A", 50, False))

    def test_a_live_microphone_group_is_its_own_colour(self):
        """Distinct from a level, because "this mic has the floor" is not the
        same fact as "this is turned up"."""
        self.assertIn(render.THEME["mic_live"],
                      render.group_key("Mic", "Dock", 2, 1))
        self.assertIn(render.THEME["muted"], render.group_key("Mic", "", 2))
        self.assertNotEqual(render.THEME["mic_live"], render.THEME["live"])

    def test_a_send_shows_the_mix_under_the_source(self):
        """Joined on one line, "Music -> Chat Mix" truncates to "Music -> Ch…"
        and loses the half that says where it goes."""
        svg = render.level_key("Music", 61, False, context="Chat Mix")
        self.assertIn("Music", svg)
        self.assertIn("Chat Mix", svg)

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
