# openwave-streamdeck

An [OpenDeck](https://github.com/nekename/OpenDeck) plugin for controlling
[OpenWave](https://github.com/rikkichy/openwave) from a Stream Deck.

## Actions

| Action | Controllers | Needs OpenWave running? |
|---|---|---|
| **Volume** | key, dial | only for microphones and sources |
| **Mic Group** | key | yes |

**Volume** controls one thing's level — a mix, a microphone, or an application
source. Rotate a dial to adjust, press to mute; a key presses to mute too. The
inspector lists all three kinds together, grouped, because from a dial's point
of view they are the same job.

Underneath they are not. A mix is a PipeWire sink and its volume masters both
paths out of that mix at once — what you hear, and what an application
capturing the mix records — so it works whether OpenWave is open or not. A
microphone or source is a **trim inside OpenWave**, applied ahead of the
per-mix faders, so that half needs OpenWave running.

**Mic Group** hands a microphone group over to its next microphone: two mics on
one speaker, one press to swap. The key shows which microphone is currently
live, not which group it is bound to — the group is what you chose when you
placed it; which mic has the floor is what changes underneath you.

Every list is read live, never hardcoded. Rename a mix, add a source or make a
group in OpenWave and the inspector shows it.

## What the keys look like

Keys are drawn as SVG and sent with `setImage`; OpenDeck bundles resvg, so
they render as vectors at any panel size. The state is continuous and
combinatorial — a name, a level, a mute, and for a group, which of several
microphones is open — and baking that into static images would need one file
per combination.

The colour is the state: blue for a normal level, **red for muted** (with the
glyph struck through), **green for the microphone that currently has the
floor**. Long names wrap to a second line rather than truncating — "Arctis
Nov…" identifies nothing.

Encoders use **`layouts/strip.json`**, a layout of our own holding exactly one
pixmap item across the whole 200×100 strip, so it is drawn the same way a key
is instead of being assembled from a title slot, a cramped 48×48 icon and a bar
that cannot be moved.

None of the built-in layouts will do, including `$A0` — which does expose a
full-canvas pixmap, but carries a title item and a second canvas alongside it,
and OpenDeck draws **both over the top**: the title falls back to the action's
name rather than staying empty when set to `""`, and the unset canvas paints a
transparency checkerboard across the middle. A layout with one item cannot do
either.

Encoders are also sent **no** `setImage` — OpenDeck routes a key image into the
layout's icon slot, which puts a shrunken copy of an entire key inside the
strip.

## How it talks to things

Two different jobs, two different mechanisms, and the split is deliberate.

Anything PipeWire owns is done directly with `pactl`. Anything **OpenWave**
owns goes through it, over the session bus. Its `Mixer` holds the same dict the
window holds and rewrites `sources.json` whole on every save, so a value
written from outside is discarded the moment a slider moves; and its GUI holds
the only USB handle the firmware will serve.

The bus side needs no protocol of its own: `GApplication` already exports
`org.gtk.Actions` on `com.github.openwave`, so OpenWave registers actions and
this calls them.

```
gdbus call --session --dest com.github.openwave \
  --object-path /com/github/openwave \
  --method org.gtk.Actions.List
→ (['switch-group', 'set-source-level', 'toggle-source-mute',
    'source-groups', 'snapshot'],)
```

`snapshot` is one action rather than one per field: a button has to draw all of
it at once — name, level, mute, group, which mic is live — and reading that
piecemeal would let the parts disagree mid-read. `Activate` has no reply, so
the pair is refresh-then-`Describe`, which also gives a `Changed` signal to
subscribe to later.

Preferred transport is GObject introspection, which hands back real GVariants
so the JSON snapshot survives with its quoting intact; `gdbus` is the fallback
for the fire-and-forget calls when `gi` is not importable.

Device gain and per-cell sends are still absent. OpenWave re-applies
`send × trim` on every reconcile, so a value set from here would revert within
a second, and an action that silently undoes itself is worse than one that is
not offered.

## Install

```bash
cp -r dev.openwave.sdPlugin ~/.config/opendeck/plugins/
# restart OpenDeck
```

Requires an **unsandboxed** OpenDeck — the AppImage or a native package. The
Flatpak has no access to `pactl`, `pw-dump`, `wpctl` or `amixer`, so none of
this works inside it.

`run.sh` scrubs the AppImage's injected `PYTHONHOME`, `PYTHONPATH` and
`LD_LIBRARY_PATH` before exec'ing the system Python. Without that the
interpreter looks for its standard library inside the AppImage and aborts
before running a line.

## Layout

```
dev.openwave.sdPlugin/
  manifest.json     actions, icons, the property inspectors
  run.sh            env scrub, then /usr/bin/python3
  plugin.py         event loop; one process, no dependencies
  owdeck/ws.py      stdlib RFC 6455 client
  owdeck/graph.py   pactl/wpctl wrappers
  owdeck/owstate.py read-only readers for OpenWave's JSON
  owdeck/ipc.py     org.gtk.Actions calls into a running OpenWave
  owdeck/render.py  the SVG the keys are drawn from
  layouts/          the encoder strip layout
  pi/               property inspectors
tests/              50 stdlib unittest cases, no dependencies
```

Run them with `python3 -m unittest discover -s tests -t .`.

Node ids are resolved by `node.name` on every use, never cached: they are
reassigned whenever a node reappears, and OpenWave destroys and recreates its
sinks whenever mixes are installed.

Nothing in `plugin.py` may raise to the top level. OpenDeck does not restart a
plugin that dies — the keys just stop responding, with nothing to say why.

## Debugging

A property inspector runs in a webview inside a Tauri window, where nothing can
read its console — so it reports what it did back to the plugin, which has a
log file:

```
PI[sd-…Encoder.0.0] payload 833b
PI[sd-…Encoder.0.0] rendered 11 options, 3 groups, chosen=none, visible=true
```

Uncaught errors are reported the same way. Set `OPENWAVE_DECK_DEBUG=1` in
OpenDeck's environment for the full event firehose in `plugin.log`; without it
only the inspector reports and real errors are logged.

`pi/` pages can also be driven outside OpenDeck entirely — WebKitGTK is the
same engine the panel runs in, so loading one with a stubbed socket shows
exactly what the page builds.

## Writing a property inspector

The context to send on is **`inActionInfo.context`** — the action's context,
not the inspector's own uuid. Sending the uuid is accepted by the socket and
then routed nowhere: settings are never saved, the plugin is never asked for
its lists, and the panel sits empty with nothing in any log to explain it.
`pi/_shared.js` handles that, and both connect conventions OpenDeck ships.

Asking once is also not enough. The panel's webview is built well before anyone
looks at it — often ten seconds before — so the panel retries until it gets an
answer, and the plugin **pushes** the lists on `propertyInspectorDidAppear`,
which fires at the only moment they are actually being read.

## Status

Volume and Mic Group work, on keys and on dials. Per-cell sends, device gain
and per-mix output selection need more actions on OpenWave's side first.
