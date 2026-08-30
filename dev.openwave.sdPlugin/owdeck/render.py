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
LIVE = "#3ba7f0"        # a normal, audible level
MIC_LIVE = "#3ecf8e"    # the microphone that is currently open
MUTED = "#e5484d"       # muted, on anything
IDLE = "#6b7280"        # nothing chosen yet, or nothing to show

BG = "#17191c"
TEXT = "#eceff2"
DIM = "#8b929b"
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
        parts.append(f'<path d="M3.6 3.6 20.4 20.4" stroke="{BG}" '
                     f'stroke-width="{stroke_width + 2.2}"/>')
        parts.append(f'<path d="M3.6 3.6 20.4 20.4" stroke="{colour}"/>')
    parts.append("</g>")
    return "".join(parts)


def _bar(value, colour, y, muted=False):
    """A level bar across the key, with the unfilled part left visible."""
    left, width, height = 16, SIZE - 32, 8
    filled = max(0.0, min(1.0, value)) * width
    track = (f'<rect x="{left}" y="{y}" width="{width}" height="{height}" '
             f'rx="{height / 2}" fill="#2b2f35"/>')
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
        f'<rect width="{SIZE}" height="{SIZE}" rx="20" fill="{BG}"/>'
        f'<rect x="1.5" y="1.5" width="{SIZE - 3}" height="{SIZE - 3}" '
        f'rx="18.5" fill="none" stroke="{accent}" stroke-width="3" '
        f'stroke-opacity="0.55"/>'
        f'{body}</svg>'
    )


def data_uri(svg):
    """OpenDeck accepts image/svg+xml; base64 avoids any quoting question."""
    encoded = base64.b64encode(svg.encode("utf-8")).decode("ascii")
    return f"data:image/svg+xml;base64,{encoded}"


def level_key(name, percent, muted, kind="speaker", unavailable=False):
    """A volume key: what it controls, how loud it is, whether it is muted."""
    if unavailable:
        accent = IDLE
        body = (
            _glyph(kind, IDLE, 54, 34, 1.5)
            + f'<text x="{SIZE / 2}" y="112" fill="{DIM}" font-size="17" '
            f'font-family="{FONT}" text-anchor="middle">{_escape(name)}</text>'
        )
        return _document(body, accent)

    accent = MUTED if muted else LIVE
    readout = "MUTED" if muted else f"{percent}%"
    body = (
        _glyph(kind, accent, 12, 10, 1.15, muted=muted)
        + f'<text x="{SIZE - 12}" y="38" fill="{accent}" font-size="26" '
        f'font-family="{FONT}" font-weight="bold" text-anchor="end">'
        f'{_escape(readout)}</text>'
        + f'<text x="{SIZE / 2}" y="86" fill="{TEXT}" font-size="19" '
        f'font-family="{FONT}" text-anchor="middle">'
        f'{_escape(_fit(name, 13))}</text>'
        + _bar(percent / 100.0, accent, 108, muted)
    )
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
        body = (
            _glyph("mic", IDLE, 54, 30, 1.5, muted=True)
            + f'<text x="{SIZE / 2}" y="106" fill="{DIM}" font-size="16" '
            f'font-family="{FONT}" text-anchor="middle">'
            f'{_escape(_fit(group, 15))}</text>'
            + f'<text x="{SIZE / 2}" y="126" fill="{DIM}" font-size="13" '
            f'font-family="{FONT}" text-anchor="middle">OpenWave closed</text>'
        )
        return _document(body, IDLE)

    live = bool(live_name)
    accent = MIC_LIVE if live else MUTED
    counter = (f"{position}/{member_count}" if live and member_count
               else f"{max(member_count, 0)} mics")
    body = (
        _glyph("mic", accent, 10, 8, 1.1, muted=not live)
        + f'<text x="{SIZE - 12}" y="34" fill="{DIM}" font-size="15" '
        f'font-family="{FONT}" text-anchor="end">'
        f'{_escape(_fit(group, 9))}</text>'
        + f'<text x="{SIZE / 2}" y="88" fill="{TEXT}" font-size="19" '
        f'font-family="{FONT}" text-anchor="middle">'
        f'{_escape(_fit(live_name or "all muted", 13))}</text>'
        + _glyph("swap", accent, 16, 104, 1.0)
        + f'<text x="{SIZE - 16}" y="123" fill="{DIM}" font-size="14" '
        f'font-family="{FONT}" text-anchor="end">{_escape(counter)}</text>'
    )
    return _document(body, accent)


def unconfigured_key(headline, hint, kind="speaker"):
    """The key before anything has been chosen for it in the inspector."""
    body = (
        _glyph(kind, IDLE, 54, 26, 1.5)
        + f'<text x="{SIZE / 2}" y="102" fill="{TEXT}" font-size="18" '
        f'font-family="{FONT}" text-anchor="middle">{_escape(headline)}</text>'
        + f'<text x="{SIZE / 2}" y="124" fill="{DIM}" font-size="14" '
        f'font-family="{FONT}" text-anchor="middle">{_escape(hint)}</text>'
    )
    return _document(body, IDLE)


def strip_icon(kind, muted=False, live=True):
    """The small pixmap slot of an encoder's touch strip, 48x48.

    The strip has its own text items, so this is the glyph alone: colour and
    the slash carry the state, and repeating the name here would only crowd
    the row the layout already reserves for it.
    """
    colour = MUTED if muted else (LIVE if live else IDLE)
    body = _glyph(kind, colour, 4, 4, 1.65, muted=muted)
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" width="48" height="48" '
        f'viewBox="0 0 48 48">{body}</svg>'
    )
