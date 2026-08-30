# Prompt: migrate OpenDeck from Flatpak to unsandboxed AppImage

Paste everything below the line into a fresh Claude Code session.

---

Replace my Flatpak install of OpenDeck with the unsandboxed AppImage build, migrating
all my existing configuration, and verify it works before removing anything.

## Why

I am writing an OpenDeck plugin that controls PipeWire and ALSA audio. The Flatpak
sandbox blocks all of it — inside `me.amankhanna.opendeck`, `pactl` returns
"Connection refused", `pw-dump` returns "Host is down", and `wpctl`, `amixer` and
`alsactl` are not installed in the `org.gnome.Platform` runtime at all. Running
unsandboxed removes that entirely and lets the plugin be a single process instead of
an in-sandbox client plus a `flatpak-spawn --host` broker.

## My machine (already verified — do not re-derive)

- Bazzite 44 (Fedora Silverblue derivative, immutable `/usr`, rpm-ostree). Prefer an
  AppImage over the `.rpm`: an rpm means `rpm-ostree` layering and a reboot, an
  AppImage is just a file. `~/.local/bin` is already on PATH.
- Currently installed: Flatpak `me.amankhanna.opendeck` version 2.14.0.
- Hardware: Elgato Stream Deck Plus, Stream Deck XL, and Stream Deck Pedal, all
  connected simultaneously.
- The Stream Deck hidraw nodes are already accessible to my user unsandboxed —
  `crw-rw-rw-` plus an ACL granting `user:Zedwil:rw-` — so **no udev rules are
  needed**. Confirm this still holds rather than assuming it.
- All required audio tools exist on the host: `pactl`, `pw-dump`, `pw-cli`, `wpctl`,
  `amixer`, `alsactl`, `pw-cat`, `pw-link`.

## State that must survive the migration

Flatpak config lives at `~/.var/app/me.amankhanna.opendeck/config/opendeck/` (~23 MB):

    plugins/            two installed plugins:
                          com.amansprojects.starterpack.sdPlugin
                          me.amankhanna.oadiscord.sdPlugin
    profiles/           my key layouts for all three devices
    settings/
    settings.json
    applications.json

Runtime data is at `~/.var/app/me.amankhanna.opendeck/data/opendeck/` (`logs`,
`mediakeys`, `storage`, caches). Caches need not be migrated; check whether
`storage` and `mediakeys` matter before discarding them.

The AppImage will use `~/.config/opendeck/` instead, which does not exist yet, so the
target is clean.

## What to do

1. Download `opendeck_2.14.0_amd64.AppImage` from the `nekename/OpenDeck` GitHub
   releases. Match the version I already run (2.14.0) so this is purely a packaging
   change, not an upgrade — I want one variable changed at a time. Verify the
   download (checksum or signature) if the release provides one.
2. Install it somewhere sensible for an immutable OS — `~/.local/bin/opendeck` or
   `~/Applications` — make it executable, and add a `.desktop` entry so it launches
   from the GNOME overview like the Flatpak did.
3. **Quit the running Flatpak first**, then copy the config across. Copy, never move:
   the Flatpak must stay intact and working as a rollback until I confirm the
   AppImage is good.
4. Start the AppImage and verify, without me having to guess:
   - it launches with no errors,
   - **all three decks** are detected — Plus, XL and Pedal,
   - my existing profiles and key layouts are present, not a blank deck,
   - both plugins loaded,
   - the Stream Deck Plus **dials and touchscreen** work, since encoders are the
     thing I care most about and are easiest to silently lose.
5. Prove the sandbox problem is actually gone: run `pactl info` and `wpctl status`
   **from inside a command spawned by the AppImage's own plugin runtime**, not just
   from a shell. A plain host shell proves nothing — the whole point is what a
   *plugin* can reach.
6. Report what worked and what did not. **Do not uninstall the Flatpak.** Leave it
   installed and tell me the exact command to remove it once I have used the
   AppImage for a few days.

## Constraints

- Do not modify anything under `~/.var/app/me.amankhanna.opendeck/` — that is my
  rollback.
- Do not run `rpm-ostree install` or anything requiring a reboot.
- If both the Flatpak and the AppImage can autostart, make sure they cannot both run
  at once and fight over the USB devices. Check for an existing autostart entry for
  the Flatpak and tell me what you find before changing it.
- If the AppImage stores config somewhere other than `~/.config/opendeck/`, find out
  where by observation rather than assuming, and migrate to the real location.
