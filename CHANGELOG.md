# [0.6.0](https://github.com/NyleGarcia/openwave-streamdeck/compare/v0.5.0...v0.6.0) (2026-08-31)


### Features

* scene keys — one press recalls a whole setup, a hold saves it back ([cc36ca7](https://github.com/NyleGarcia/openwave-streamdeck/commit/cc36ca70d3f2a03eacb41d7296d862864ff16cf4))

# [0.5.0](https://github.com/NyleGarcia/openwave-streamdeck/compare/v0.4.0...v0.5.0) (2026-08-30)


### Features

* six colour themes, chosen from any inspector ([5d177bc](https://github.com/NyleGarcia/openwave-streamdeck/commit/5d177bc7612a7e35110f1c28dd1dae0ceae436ac))

# [0.4.0](https://github.com/NyleGarcia/openwave-streamdeck/compare/v0.3.0...v0.4.0) (2026-08-30)


### Bug Fixes

* keep the step badge parseable on Python 3.10 ([c2cc239](https://github.com/NyleGarcia/openwave-streamdeck/commit/c2cc239fee4b714b01fcdd8fd503fdcf70e2946d))


### Features

* make a press mute, raise or lower, with a settable step ([2909193](https://github.com/NyleGarcia/openwave-streamdeck/commit/29091935d160a6abdc203c83351420b9be2ad987))

# [0.3.0](https://github.com/NyleGarcia/openwave-streamdeck/compare/v0.2.0...v0.3.0) (2026-08-30)


### Bug Fixes

* name the per-mix action for what it does, not for the desk term ([905c29b](https://github.com/NyleGarcia/openwave-streamdeck/commit/905c29b531f2152dbcdab917e141d1fb84251323))


### Features

* choose a source and a mix in two dropdowns ([ca182fe](https://github.com/NyleGarcia/openwave-streamdeck/commit/ca182fe0b92c0aa5ac811ef94ce1f8df2e3d3227))

# [0.2.0](https://github.com/NyleGarcia/openwave-streamdeck/compare/v0.1.1...v0.2.0) (2026-08-30)


### Features

* split Volume into Mix Volume, Source Volume and Mix Send ([27fd6b2](https://github.com/NyleGarcia/openwave-streamdeck/commit/27fd6b29f0f193b80f811ae2561a91f62c328122))

## [0.1.1](https://github.com/NyleGarcia/openwave-streamdeck/compare/v0.1.0...v0.1.1) (2026-08-30)


### Bug Fixes

* name each dial in the OpenDeck editor instead of "Mix" ([6117de1](https://github.com/NyleGarcia/openwave-streamdeck/commit/6117de10127d1efedc7b1fbf15a3d4c4ba220e6d))

# [0.1.0](https://github.com/NyleGarcia/openwave-streamdeck/compare/v0.0.1...v0.1.0) (2026-08-30)


### Features

* control per-mix sends, and draw proper icons ([083cad6](https://github.com/NyleGarcia/openwave-streamdeck/commit/083cad6e26dcc3285fdab9d645d667735e34e4f5))

# Changelog

All notable changes to this project are documented here. This file is
maintained by [semantic-release](https://semantic-release.gitbook.io/) from
[Angular](https://www.conventionalcommits.org/) commit messages; entries below
0.0.1 were written by hand, before that was wired up.

## 0.0.1 (2026-08-29)

First release. An OpenDeck plugin for driving OpenWave from a Stream Deck.

### Features

* **Volume** — set the level of a mix, a microphone or an application source
  from a key or a dial; press to mute. Mixes are PipeWire sinks and work
  whether OpenWave is open or not; microphones and sources are trims inside
  OpenWave and are set over the session bus, because its `Mixer` rewrites
  `sources.json` whole on every save and would discard an outside write.
* **Mic Group** — hand a microphone group to its next microphone in one press.
  The key shows which microphone currently has the floor.
* Keys and the encoder touch strip are drawn as SVG, so the level, the mute and
  the live microphone are legible at a glance: blue for a level, red for muted,
  green for the open microphone.
* Both lists are read live from OpenWave, never hardcoded.
