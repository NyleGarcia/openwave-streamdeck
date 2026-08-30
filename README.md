# openwave-streamdeck

An [OpenDeck](https://github.com/nekename/OpenDeck) plugin for controlling
[OpenWave](https://github.com/rikkichy/openwave) from a Stream Deck.

## Actions

| Action | Controls | Needs OpenWave running? |
|---|---|---|
| **Mix Volume** | a mix's master | no |
| **Source Volume** | a source's trim, in every mix at once | yes |
| **Source Level per Mix** | one source inside a *single* mix | yes |
| **Mic Group** | which microphone in a group has the floor | yes |

All four work on a key or a dial except Mic Group, which is a key.

Rotate a dial to adjust, press to mute; a key presses to mute too.

One action per kind rather than one action with every target in a single list.
With three mixes and seven sources that list is **31 entries**, 21 of them
sends — long enough that finding a mix master at the top is work. Split, each
list is short, and OpenDeck's own action list says what a button does before
it is placed.

They are also genuinely different things. A mix master is a PipeWire sink, so
it works whether OpenWave is open or not. A trim and a send both live inside
OpenWave: the send is one cell of the matrix, the trim sits ahead of all of
them. Sharing one control would imply they are interchangeable.

A key placed before the split keeps whatever it holds. Its action still drives
any kind, and a target its list would no longer offer is shown under
**Currently set** rather than vanishing, which would read as the key having
lost its setting.

"Turn Music down" means three different things, which is why there are three
actions:

| Action | What moves |
|---|---|
| **Source Volume** | Music, everywhere — every mix at once |
| **Source Level per Mix** | Music *in Chat only* — your own ears unaffected |
| **Mix Volume** | the whole Chat Mix, Music included |

Source Level per Mix asks in **two dropdowns**, a source and a mix, because
that is genuinely two choices. One combined list is every pairing — 21 entries
for three mixes and seven sources, and it grows multiplicatively.

On the key the source is the headline and the mix sits under it in smaller type
— joined on one line, "Music → Chat Mix" truncates to "Music → Ch…" and loses
the half that says where.

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

Sends were absent until OpenWave grew `set-cell-level` and `toggle-cell-mute`,
for exactly this reason: OpenWave re-applies `send × trim` on every reconcile,
so a cell written directly to `mixes.json` is undone within a second. Going
through the window is not a nicety, it is the only thing that sticks.

Device gain is still absent, and stays that way while the GUI holds the USB
handle — the firmware serves one process at a time.

## Install

Download `openwave-streamdeck-<version>.zip` from
[Releases](https://github.com/NyleGarcia/openwave-streamdeck/releases) and
install it through OpenDeck, or from a checkout:

```bash
make install     # copies into ~/.config/opendeck/plugins, then restart OpenDeck
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

```bash
make check       # bundle validation, byte-compile, shell syntax, tests
make test        # tests only
make package     # build the release zip into dist/
```

`scripts/validate_plugin.py` is the part worth having: OpenDeck fails a broken
plugin *quietly*. A missing property inspector gives an empty panel, a missing
layout gives a blank touch strip, and neither writes anything to any log. The
validator resolves every path the manifest names — inspectors, layouts, icons,
each state image, every module the entry point imports — so a bundle that would
fail silently on a deck fails loudly in CI instead.

## Releasing

Versioning is [semantic-release](https://semantic-release.gitbook.io/) driven
by [Angular](https://www.conventionalcommits.org/) commit messages on `main`:

| Commit prefix | Bump |
|---|---|
| `fix:` | patch |
| `feat:` | minor |
| `polish:` | patch |
| `BREAKING CHANGE:` in the body | major |
| `chore:`, `docs:`, `refactor:`, `test:` | none |

A release writes the version into `dev.openwave.sdPlugin/manifest.json` as well
as tagging — the manifest is the only place a version is visible to someone
using the plugin — updates `CHANGELOG.md`, and attaches the installable zip to
the GitHub release. `next` publishes prereleases.

The zip contains the `dev.openwave.sdPlugin` directory *at its root*, which is
what OpenDeck's installer expects; a zip of that directory's contents installs a
plugin with no manifest where one should be.

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
