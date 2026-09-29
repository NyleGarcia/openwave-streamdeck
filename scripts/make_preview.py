#!/usr/bin/env python3
"""Draw the README's pictures from the keys' own renderer.

Each action is painted in a representative live state and laid out as a deck,
and each is also written on its own in every state worth showing, so the
pictures on the repository page are the same art a deck shows rather than
mock-ups that drift from it. Run after changing how a key draws; the output is
committed.
"""

import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "dev.openwave.sdPlugin"))

from owdeck import render                           # noqa: E402

OUT_SVG = os.path.join(ROOT, ".github", "preview.svg")
OUT_PNG = os.path.join(ROOT, ".github", "preview.png")
KEYS_DIR = os.path.join(ROOT, ".github", "keys")
COLUMNS = 3
GAP = 24
PAD = 32
BG = "#0e0f11"


def keys():
    render.set_theme("default")
    return [
        render.level_key("Game Mix", 72, False),
        render.level_key("Shure SM7B", 64, False, kind="mic"),
        render.level_key("Music", 35, False, kind="headphones",
                         context="Chat Mix"),
        render.group_key("Desk", "Shure SM7B", 2),
        render.scene_key("Streaming"),
        render.fx_key("Shure SM7B", "gate", True, value="-42 dB"),
    ]


def states():
    """name -> [(state, svg)], in the order the README shows them."""
    render.set_theme("default")
    return {
        "mix": [
            ("live", render.level_key("Game Mix", 72, False)),
            ("muted", render.level_key("Game Mix", 72, True)),
            ("step", render.level_key("Game Mix", 72, False,
                                      press="up", step=5)),
        ],
        "source": [
            ("live", render.level_key("Shure SM7B", 64, False, kind="mic")),
            ("muted", render.level_key("Shure SM7B", 64, True, kind="mic")),
            ("closed", render.level_key("Shure SM7B", 0, False, kind="mic",
                                        unavailable=True)),
        ],
        "send": [
            ("live", render.level_key("Music", 35, False, kind="headphones",
                                      context="Chat Mix")),
            ("muted", render.level_key("Music", 35, True, kind="headphones",
                                       context="Chat Mix")),
        ],
        "group": [
            ("live", render.group_key("Desk", "Shure SM7B", 2)),
            ("muted", render.group_key("Desk", "", 2)),
            ("closed", render.group_key("Desk", "", 2, unavailable=True)),
        ],
        "scene": [
            ("ready", render.scene_key("Streaming")),
            ("saved", render.scene_key("Streaming", saved=True)),
        ],
        "fx": [
            ("on", render.fx_key("Shure SM7B", "gate", True,
                                 value="-42 dB")),
            ("off", render.fx_key("Shure SM7B", "comp", False)),
        ],
        "strip": [
            ("live", render.strip("Game Mix", 72, False, level=0.18)),
            ("send", render.strip("Music", 35, False, kind="headphones",
                                  context="Chat Mix", level=0.05)),
            ("muted", render.strip("Shure SM7B", 64, True, kind="mic")),
        ],
        "theme": [
            (name, _themed(name)) for name in render.THEMES
        ],
    }


def _themed(name):
    render.set_theme(name)
    try:
        return render.level_key("Game Mix", 72, False)
    finally:
        render.set_theme("default")


def compose(svgs):
    rows = -(-len(svgs) // COLUMNS)
    width = PAD * 2 + COLUMNS * render.SIZE + (COLUMNS - 1) * GAP
    height = PAD * 2 + rows * render.SIZE + (rows - 1) * GAP
    parts = []
    for index, svg in enumerate(svgs):
        x = PAD + (index % COLUMNS) * (render.SIZE + GAP)
        y = PAD + (index // COLUMNS) * (render.SIZE + GAP)
        # Nest each key as its own <svg>, positioned in the grid.
        parts.append(re.sub(r"^<svg ", f'<svg x="{x}" y="{y}" ', svg, count=1))
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" '
        f'height="{height}" viewBox="0 0 {width} {height}">'
        f'<rect width="{width}" height="{height}" rx="28" fill="{BG}"/>'
        + "".join(parts) + "</svg>"
    )


def rasterise(svg_path, png_path):
    """Render at 2x for high-density screens, keeping the aspect ratio."""
    for command in (
        ["rsvg-convert", "-z", "2", "-o", png_path, svg_path],
        ["magick", "-background", "none", "-density", "192", svg_path,
         png_path],
    ):
        try:
            subprocess.run(command, check=True, stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL)
            return True
        except (OSError, subprocess.CalledProcessError):
            continue
    return False


def main():
    svg = compose(keys())
    os.makedirs(os.path.dirname(OUT_SVG), exist_ok=True)
    with open(OUT_SVG, "w", encoding="utf-8") as handle:
        handle.write(svg)
    if not rasterise(OUT_SVG, OUT_PNG):
        print("no rasteriser found (install librsvg or imagemagick)")
        return 1
    os.remove(OUT_SVG)
    print(OUT_PNG)

    os.makedirs(KEYS_DIR, exist_ok=True)
    for action, variants in states().items():
        for state, key in variants:
            base = os.path.join(KEYS_DIR, f"{action}-{state}")
            with open(base + ".svg", "w", encoding="utf-8") as handle:
                handle.write(key)
            if not rasterise(base + ".svg", base + ".png"):
                return 1
            os.remove(base + ".svg")
            print(base + ".png")
    return 0


if __name__ == "__main__":
    sys.exit(main())
