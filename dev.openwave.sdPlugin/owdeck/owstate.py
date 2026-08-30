"""Read OpenWave's configuration, without importing OpenWave.

The plugin needs to know which mixes exist and what they are called. It gets
that by reading the same JSON files OpenWave writes, rather than importing
wavexlr, for three reasons:

  - Constructing a Mixer would start a second worker thread with its own
    private copy of the cell state, fighting the GUI's.
  - Constructing a WaveDevice would open the USB device, and the firmware
    serves vendor transfers to one process at a time.
  - Importing it at all would tie the plugin to a checkout of OpenWave at a
    particular path.

Read-only, always. Mixer._state is read once at construction and rewritten
whole on every save, so anything this process wrote to mixes.json would be
silently discarded the next time a slider moved.
"""

import json
import os

CONFIG_DIR = os.path.expanduser("~/.config/openwave")
MIXDEFS = os.path.join(CONFIG_DIR, "mixdefs.json")
SOURCES = os.path.join(CONFIG_DIR, "sources.json")
CELLS = os.path.join(CONFIG_DIR, "mixes.json")


def _load(path):
    try:
        with open(path) as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def mixes():
    """Mix definitions, in column order.

    Insertion order is column order in OpenWave's matrix, and json preserves
    it, so the plugin lists mixes the way the user sees them.
    """
    return _load(MIXDEFS)


def sources():
    return _load(SOURCES)


def mix_choices():
    """[(mix_id, label, sink_name)] for a property inspector dropdown."""
    return [
        (mix_id, mix.get("name", mix_id), mix.get("sink", ""))
        for mix_id, mix in mixes().items()
        if mix.get("sink")
    ]


def mix_sink(mix_id):
    """The PipeWire sink carrying a mix, or None if it is gone.

    Looked up by id rather than remembered, because a mix can be renamed --
    OpenWave keeps the sink name stable across a rename precisely so that
    things pointing at it keep working.
    """
    mix = mixes().get(mix_id)
    return mix.get("sink") if mix else None


def mix_name(mix_id, default=None):
    mix = mixes().get(mix_id)
    return mix.get("name", default or mix_id) if mix else (default or mix_id)


def mtimes():
    """Modification times of the files worth watching, for change detection."""
    out = {}
    for path in (MIXDEFS, SOURCES, CELLS):
        try:
            out[path] = os.stat(path).st_mtime
        except OSError:
            out[path] = None
    return out
