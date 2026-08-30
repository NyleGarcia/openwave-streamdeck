# openwave-streamdeck

An [OpenDeck](https://github.com/nekename/OpenDeck) plugin for controlling
[OpenWave](https://github.com/rikkichy/openwave) from a Stream Deck.

## Actions

| Action | Controllers | Needs OpenWave running? |
|---|---|---|
| **Mix Level** | key, dial | no |
| **Mic Group** | key | yes |

**Mix Level** sets the master volume of one OpenWave mix. Rotate a dial to
adjust, press to mute. It drives the mix's own sink volume, which masters both
paths out of that mix at once — what you hear, and what an application
capturing the mix records — so it needs nothing but PipeWire.

**Mic Group** hands a microphone group over to its next microphone: two mics on
one speaker, one press to swap. Which mic is live is OpenWave's own state, so
this one talks to a running instance.

The mix and group lists are read live, never hardcoded. Rename a mix or add a
group in OpenWave and the property inspector shows it.

## How it talks to things

Two different jobs, two different mechanisms, and the split is deliberate.

Anything PipeWire owns is done directly with `pactl`/`wpctl`. Anything
**OpenWave** owns goes through it, over the session bus. Its `Mixer` reads its
state once at construction and rewrites the whole file on every save, so a
value written from outside is discarded the moment a slider moves; and its GUI
holds the only USB handle the firmware will serve. Cell sends, source trims and
device gain therefore cannot be driven from here without OpenWave's
cooperation, and actions for them are deliberately absent rather than present
and silently ineffective.

The bus side needs no protocol of its own: `GApplication` already exports
`org.gtk.Actions` on `com.github.openwave`, so OpenWave registers actions and
this calls them.

```
gdbus call --session --dest com.github.openwave \
  --object-path /com/github/openwave \
  --method org.gtk.Actions.List
```

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
  pi/               property inspectors
```

Node ids are resolved by `node.name` on every use, never cached: they are
reassigned whenever a node reappears, and OpenWave destroys and recreates its
sinks whenever mixes are installed.

Nothing in `plugin.py` may raise to the top level. OpenDeck does not restart a
plugin that dies — the keys just stop responding, with nothing to say why.

## Status

Early. Mix Level and Mic Group work. Cell sends, source trims, mic gain and
per-mix output selection need more actions registered on OpenWave's side first.
