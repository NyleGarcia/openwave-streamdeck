"""Draw the keys.

OpenDeck renders SVG -- it bundles resvg -- so a key is generated rather than
picked from a set of static PNGs. That matters here because the useful state
is continuous and combinatorial: a name, a level, a mute, and for a
microphone group, which of several microphones is currently live. Baking that
into images would need one file per combination.

Everything is drawn on a 144x144 grid, the Stream Deck key size, and scaled by
the host for other panels.
"""

import base64

SIZE = 144

# One accent per meaning, used for the glyph, the bar and the border alike so
# a key reads at a glance from across a desk rather than needing to be read.
#
# A theme is the whole palette, not a single hue: recolouring only the accent
# leaves a light theme's text unreadable on a dark ground. Every key is drawn
# from THEME, which is swapped whole by set_theme().
THEMES = {
    "default": {
        "name": "Default",
        "live": "#3ba7f0", "mic_live": "#3ecf8e", "muted": "#e5484d",
        "idle": "#6b7280", "bg": "#17191c", "text": "#eceff2",
        "dim": "#8b929b", "track": "#2b2f35",
    },
    "amber": {
        "name": "Amber",
        "live": "#f0a83b", "mic_live": "#ffd166", "muted": "#e5484d",
        "idle": "#6b6154", "bg": "#1a1713", "text": "#f6eee2",
        "dim": "#a2957f", "track": "#332b21",
    },
    "violet": {
        "name": "Violet",
        "live": "#b07cf0", "mic_live": "#6ee7d3", "muted": "#f2568f",
        "idle": "#6b6480", "bg": "#17141f", "text": "#efeaf7",
        "dim": "#9a92ad", "track": "#2c2740",
    },
    "mono": {
        "name": "Monochrome",
        "live": "#e8ecf1", "mic_live": "#ffffff", "muted": "#7a828c",
        "idle": "#4d545c", "bg": "#141618", "text": "#f2f4f7",
        "dim": "#828a94", "track": "#2a2e33",
    },
    "contrast": {
        # Deliberately not subtle. Chosen for a deck under stage lighting,
        # where the default's mid-tones disappear.
        "name": "High contrast",
        "live": "#00d4ff", "mic_live": "#00ff88", "muted": "#ff2d55",
        "idle": "#8a8a8a", "bg": "#000000", "text": "#ffffff",
        "dim": "#c8c8c8", "track": "#3a3a3a",
    },
    "light": {
        "name": "Light",
        "live": "#0b74d1", "mic_live": "#0f8f5e", "muted": "#c4262e",
        "idle": "#8a9199", "bg": "#f4f6f8", "text": "#14181c",
        "dim": "#5b636b", "track": "#d3d9df",
    },
}

DEFAULT_THEME = "default"
THEME = dict(THEMES[DEFAULT_THEME])


def set_theme(name):
    """Swap the palette every key is drawn from. Returns the name in use.

    Module state rather than a parameter threaded through nine functions:
    drawing happens only on the plugin's event-loop thread, so there is no
    second caller to race with, and an unknown name falls back rather than
    leaving keys half-drawn in a palette that does not exist.
    """
    global THEME
    THEME = dict(THEMES.get(name) or THEMES[DEFAULT_THEME])
    return THEME["name"]


def theme_choices():
    return [{"id": key, "label": value["name"]}
            for key, value in THEMES.items()]


FONT = "Liberation Sans, DejaVu Sans, Helvetica, Arial, sans-serif"

# 24x24 glyph paths, translated and scaled into place by _glyph().
_MIC = ("M12 3.2a2.9 2.9 0 0 1 2.9 2.9v5.6a2.9 2.9 0 0 1-5.8 0V6.1"
        "A2.9 2.9 0 0 1 12 3.2z")
_MIC_ARC = "M5.6 11a6.4 6.4 0 0 0 12.8 0"
_MIC_STEM = "M12 17.4v3.4"
_SPEAKER = "M3.6 9.2h3.3l4.9-4v13.6l-4.9-4H3.6z"
_WAVE_1 = "M15.4 8.6a4.8 4.8 0 0 1 0 6.8"
_WAVE_2 = "M18.2 5.8a8.8 8.8 0 0 1 0 12.4"
_HEADBAND = "M4 15.4v-3.2a8 8 0 0 1 16 0v3.2"
_RECORD = "M12 5.4a6.6 6.6 0 1 1 0 13.2 6.6 6.6 0 0 1 0-13.2z"
_SWAP = "M4.4 9.2h13.2l-3.4-3.4M19.6 14.8H6.4l3.4 3.4"

# Each glyph is drawn on a 24x24 grid: filled paths, stroked paths, and
# rounded rectangles, which is what earcups and slider caps want and what a
# path would only express clumsily.
GLYPHS = {
    "mic": {"fill": [_MIC], "stroke": [_MIC_ARC, _MIC_STEM], "rects": []},
    "speaker": {"fill": [_SPEAKER], "stroke": [_WAVE_1, _WAVE_2],
                "rects": []},
    "headphones": {
        "fill": [], "stroke": [_HEADBAND],
        "rects": [(2.2, 14.2, 4.6, 7.2, 2.3), (17.2, 14.2, 4.6, 7.2, 2.3)],
    },
    "record": {"fill": [_RECORD], "stroke": [], "rects": []},
    "swap": {"fill": [], "stroke": [_SWAP], "rects": []},
}


def _escape(text):
    return (str(text).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;"))


def _fit(text, limit):
    """Truncate to a width the key can actually show, with an ellipsis."""
    text = str(text)
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _wrap(text, per_line, max_lines=2):
    """Break a name across lines rather than cutting it short.

    "Arctis Nova Pro Wireless Mono" truncated to one line is "Arctis Nov…",
    which does not identify anything; over two lines it is readable. Only the
    overflow past the last line is ellipsised.
    """
    words, lines, current = str(text).split(), [], ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if len(candidate) <= per_line or not current:
            current = candidate
        else:
            lines.append(current)
            current = word
            if len(lines) == max_lines:
                break
    if current and len(lines) < max_lines:
        lines.append(current)
    if not lines:
        return [""]
    consumed = len(" ".join(lines).split())
    if consumed < len(words):
        lines[-1] = _fit(lines[-1] + " " + words[consumed], per_line)
    return [_fit(line, per_line) for line in lines]


def _text_block(lines, centre_y, size, colour, weight="600", x=SIZE / 2,
                anchor="middle"):
    """One or two centred lines, kept vertically centred as a block."""
    step = size + 4
    top = centre_y - (len(lines) - 1) * step / 2
    return "".join(
        f'<text x="{x}" y="{top + i * step:.1f}" fill="{colour}" '
        f'font-size="{size}" font-family="{FONT}" font-weight="{weight}" '
        f'text-anchor="{anchor}">{_escape(line)}</text>'
        for i, line in enumerate(lines)
    )


def _glyph(kind, colour, x, y, scale, muted=False):
    """One icon, drawn at (x, y) with its 24-unit grid scaled by `scale`."""
    shape = GLYPHS.get(kind, GLYPHS["speaker"])
    stroke_width = 2.0
    parts = [f'<g transform="translate({x},{y}) scale({scale})" '
             f'fill="none" stroke="{colour}" stroke-width="{stroke_width}" '
             f'stroke-linecap="round" stroke-linejoin="round">']
    for path in shape["fill"]:
        parts.append(f'<path d="{path}" fill="{colour}" stroke="none"/>')
    for rect in shape["rects"]:
        rx, ry, rw, rh, radius = rect
        parts.append(f'<rect x="{rx}" y="{ry}" width="{rw}" height="{rh}" '
                     f'rx="{radius}" fill="{colour}" stroke="none"/>')
    for path in shape["stroke"]:
        parts.append(f'<path d="{path}"/>')
    if muted:
        # A slash through the glyph, doubled in the background colour
        # underneath so it reads as a cut rather than as one more stroke of
        # the icon itself.
        parts.append(f'<path d="M3.6 3.6 20.4 20.4" stroke="{THEME["bg"]}" '
                     f'stroke-width="{stroke_width + 2.2}"/>')
        parts.append(f'<path d="M3.6 3.6 20.4 20.4" stroke="{colour}"/>')
    parts.append("</g>")
    return "".join(parts)


def _bar(value, colour, y, muted=False, width=None):
    """A level bar across the key, with the unfilled part left visible."""
    left, height = 16, 8
    width = SIZE - 32 if width is None else width
    filled = max(0.0, min(1.0, value)) * width
    track = (f'<rect x="{left}" y="{y}" width="{width}" height="{height}" '
             f'rx="{height / 2}" fill="{THEME["track"]}"/>')
    if filled <= 0.5 or muted:
        # A zero-width rounded rect renders as a dot; nothing is clearer.
        return track
    return track + (
        f'<rect x="{left}" y="{y}" width="{filled:.1f}" height="{height}" '
        f'rx="{height / 2}" fill="{colour}"/>'
    )


def _document(body, accent):
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{SIZE}" '
        f'height="{SIZE}" viewBox="0 0 {SIZE} {SIZE}">'
        f'<rect width="{SIZE}" height="{SIZE}" rx="20" fill="{THEME["bg"]}"/>'
        f'<rect x="1.5" y="1.5" width="{SIZE - 3}" height="{SIZE - 3}" '
        f'rx="18.5" fill="none" stroke="{accent}" stroke-width="3" '
        f'stroke-opacity="0.55"/>'
        f'{body}</svg>'
    )


def data_uri(svg):
    """OpenDeck accepts image/svg+xml; base64 avoids any quoting question."""
    encoded = base64.b64encode(svg.encode("utf-8")).decode("ascii")
    return f"data:image/svg+xml;base64,{encoded}"


def level_key(name, percent, muted, kind="speaker", unavailable=False,
              context="", press="mute", step=0):
    """A volume key: what it controls, how loud it is, whether it is muted.

    `context` is the mix a send belongs to. It sits under the name in smaller
    dim type rather than being joined to it, because "Music -> Chat Mix" on
    one line truncates to "Music -> Ch…" and loses the half that says where.
    """
    if unavailable:
        return _document(
            _glyph(kind, THEME["idle"], 50, 28, 1.75)
            + _text_block(_wrap(name, 13), 108, 19, THEME["dim"]),
            THEME["idle"])

    accent = THEME["muted"] if muted else THEME["live"]
    lines = _wrap(name, 12)
    body = (
        _glyph(kind, accent, 11, 11, 1.3, muted=muted)
        + f'<text x="{SIZE - 13}" y="42" fill="{accent}" font-size="30" '
        f'font-family="{FONT}" font-weight="bold" text-anchor="end">'
        f'{"MUTED" if muted else f"{percent}%"}</text>'
        + _text_block(lines, (78 if context else 92) if len(lines) > 1
                      else (84 if context else 96),
                      23 if len(lines) == 1 else 20, THEME["text"])
        + (_text_block([_fit(context, 15)], 108, 14, THEME["dim"], weight="400")
           if context else "")
    )
    if press in ("up", "down") and step:
        # A key that steps needs to say so and by how much: three keys on one
        # source differ only in what pressing them does, and the level they
        # all show is identical. The bar gives up its right-hand end for it.
        body += _bar(percent / 100.0, accent, 118, muted, width=SIZE - 62)
        # The sign is bound out here: an escape inside an f-string
        # expression is a syntax error before Python 3.12, and this runs on
        # whatever python3 the host distribution ships.
        sign = "+" if press == "up" else "\u2212"
        body += (
            f'<text x="{SIZE - 14}" y="127" fill="{accent}" font-size="17" '
            f'font-family="{FONT}" font-weight="bold" text-anchor="end">'
            f'{sign}{step}</text>'
        )
    else:
        body += _bar(percent / 100.0, accent, 118, muted)
    return _document(body, accent)


def group_key(group, live_name, member_count, position=0,
              unavailable=False):
    """A microphone-group key: which microphone is open right now.

    The live microphone's name is the headline, not the group's. The group is
    what you chose when you placed the key; which microphone it is currently
    handing the audio to is the thing that changes underneath you, so that is
    what the key shows largest.
    """
    if unavailable:
        return _document(
            _glyph("mic", THEME["idle"], 50, 24, 1.75, muted=True)
            + _text_block(_wrap(group, 14), 104, 18, THEME["dim"])
            + _text_block(["OpenWave closed"], 126, 13, THEME["dim"], weight="400"),
            THEME["idle"])

    live = bool(live_name)
    accent = THEME["mic_live"] if live else THEME["muted"]
    lines = _wrap(live_name or "all muted", 12)
    body = (
        _glyph("mic", accent, 11, 10, 1.3, muted=not live)
        + f'<text x="{SIZE - 13}" y="34" fill="{THEME["dim"]}" font-size="16" '
        f'font-family="{FONT}" text-anchor="end">'
        f'{_escape(_fit(group, 9))}</text>'
        + _text_block(lines, 90 if len(lines) > 1 else 94,
                      23 if len(lines) == 1 else 20, THEME["text"])
        + _glyph("swap", accent, 14, 104, 1.05)
        + f'<text x="{SIZE - 15}" y="126" fill="{THEME["dim"]}" font-size="14" '
        f'font-family="{FONT}" text-anchor="end">'
        f'{max(member_count, 0)} mics</text>'
    )
    return _document(body, accent)


def unconfigured_key(headline, hint, kind="speaker"):
    """The key before anything has been chosen for it in the inspector."""
    body = (
        _glyph(kind, THEME["idle"], 50, 22, 1.75)
        + _text_block([headline], 100, 20, THEME["text"])
        + _text_block([hint], 122, 15, THEME["dim"], weight="400")
    )
    return _document(body, THEME["idle"])


STRIP_W, STRIP_H = 200, 100


def strip(name, percent, muted, kind="speaker", unavailable=False,
          context=""):
    """The encoder's entire touch strip, as one image.

    The $A0 layout exposes a full-canvas pixmap covering all 200x100, so the
    strip is drawn the same way a key is instead of being assembled from a
    title slot, a cramped 48x48 icon and a bar that cannot be moved. It also
    sidesteps setImage: OpenDeck routes a key image into the layout's icon
    item, which put a whole shrunken key card inside the strip.
    """
    accent = THEME["idle"] if unavailable else (THEME["muted"] if muted else THEME["live"])
    readout = "--" if unavailable else ("MUTED" if muted else f"{percent}%")
    # Two rows rather than one. The strip is 200 wide, and a name and a large
    # readout on the same line overlap the moment the name is longer than
    # "System" -- so the name gets the top row to itself and the readout sits
    # beside the bar underneath, where nothing competes with it.
    bar_x, bar_w, bar_h, bar_y = 12, 108, 14, 70
    filled = 0.0 if (muted or unavailable) else \
        max(0.0, min(1.0, percent / 100.0)) * bar_w
    # With a mix to name, the name and the mix each get a row of their own.
    # Side by side they collide the moment the name is longer than "Music":
    # right-aligning the mix does not help, because both widths depend on
    # text that is not measurable here.
    name_y, context_y = (32, 52) if context else (40, None)
    body = (
        f'<rect width="{STRIP_W}" height="{STRIP_H}" fill="{THEME["bg"]}"/>'
        + _glyph(kind, accent, 10, (14 if context else 10), 1.35,
                 muted=muted and not unavailable)
        + f'<text x="54" y="{name_y}" fill="{THEME["text"]}" font-size="23" '
        f'font-family="{FONT}" font-weight="600">'
        f'{_escape(_fit(name, 12))}</text>'
        + (f'<text x="54" y="{context_y}" fill="{THEME["dim"]}" font-size="15" '
           f'font-family="{FONT}">into {_escape(_fit(context, 14))}</text>'
           if context else "")
        + f'<rect x="{bar_x}" y="{bar_y}" width="{bar_w}" height="{bar_h}" '
        f'rx="{bar_h / 2}" fill="{THEME["track"]}"/>'
    )
    if filled > 1.0:
        body += (f'<rect x="{bar_x}" y="{bar_y}" width="{filled:.1f}" '
                 f'height="{bar_h}" rx="{bar_h / 2}" fill="{accent}"/>')
    body += (f'<text x="{STRIP_W - 12}" y="{bar_y + bar_h - 1}" '
             f'fill="{accent}" font-size="23" font-family="{FONT}" '
             f'font-weight="bold" text-anchor="end">'
             f'{_escape(readout)}</text>')
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{STRIP_W}" '
            f'height="{STRIP_H}" viewBox="0 0 {STRIP_W} {STRIP_H}">'
            f'{body}</svg>')


def scene_key(name, unavailable=False, saved=False):
    """A scene key: one press recalls a whole named setup.

    The scene's name is the headline. `saved` flashes the confirmation
    frame after a hold-to-save, because a save changes nothing visible
    anywhere else — without it the gesture feels like it did nothing.
    """
    if unavailable:
        return _document(
            _glyph("swap", THEME["idle"], 50, 24, 1.75, muted=True)
            + _text_block(_wrap(name or "Scene", 12), 104, 18, THEME["dim"])
            + _text_block(["OpenWave closed"], 126, 13, THEME["dim"],
                          weight="400"),
            THEME["idle"])
    accent = THEME["live"]
    lines = _wrap(name or "Pick a scene", 12)
    body = (
        _glyph("swap", accent, 11, 10, 1.3)
        + f'<text x="{SIZE - 13}" y="34" fill="{THEME["dim"]}" font-size="16" '
        f'font-family="{FONT}" text-anchor="end">SCENE</text>'
        + _text_block(lines, 90 if len(lines) > 1 else 94,
                      23 if len(lines) == 1 else 20, THEME["text"])
        + _text_block(["saved ✓" if saved else "press to recall"],
                      126, 13, accent if saved else THEME["dim"],
                      weight="700" if saved else "400")
    )
    return _document(body, accent)
