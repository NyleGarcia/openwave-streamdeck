#!/usr/bin/env python3
"""Check the plugin bundle is loadable before it is released.

OpenDeck fails a broken plugin quietly: a missing property inspector gives an
empty panel, a missing layout gives a blank touch strip, and neither writes
anything to a log. Nothing here needs a Stream Deck, so it can gate a release
in a way that hardware testing cannot.
"""

import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUNDLE = os.path.join(ROOT, "dev.openwave.sdPlugin")
SEMVER = re.compile(r"^\d+\.\d+\.\d+$")
# Layouts named with a leading $ are built into OpenDeck and have no file.
BUILTIN_LAYOUT = re.compile(r"^\$[A-Z]\d$")
# Elgato omits the extension in manifest image references.
IMAGE_SUFFIXES = ("", ".png", ".svg")

problems = []


def check(condition, message):
    if not condition:
        problems.append(message)
    return condition


def resolve_image(reference):
    return any(os.path.isfile(os.path.join(BUNDLE, reference + suffix))
               for suffix in IMAGE_SUFFIXES)


def main():
    manifest_path = os.path.join(BUNDLE, "manifest.json")
    if not check(os.path.isfile(manifest_path), "manifest.json is missing"):
        return report()
    try:
        manifest = json.load(open(manifest_path))
    except ValueError as exc:
        problems.append(f"manifest.json is not valid JSON: {exc}")
        return report()

    check(SEMVER.match(str(manifest.get("Version", ""))),
          f"Version {manifest.get('Version')!r} is not MAJOR.MINOR.PATCH -- "
          f"semantic-release writes it, so a mismatch means the bump failed")
    check(resolve_image(manifest.get("Icon", "")),
          f"plugin Icon {manifest.get('Icon')!r} resolves to no file")

    entry = manifest.get("CodePathLin") or manifest.get("CodePath")
    entry_path = os.path.join(BUNDLE, entry or "")
    if check(entry and os.path.isfile(entry_path),
             f"CodePathLin {entry!r} does not exist"):
        check(os.access(entry_path, os.X_OK),
              f"{entry} is not executable; OpenDeck runs it directly")

    uuids = set()
    for action in manifest.get("Actions") or []:
        uuid = action.get("UUID", "<unnamed>")
        check(uuid not in uuids, f"duplicate action UUID {uuid}")
        uuids.add(uuid)

        inspector = action.get("PropertyInspectorPath")
        if inspector:
            check(os.path.isfile(os.path.join(BUNDLE, inspector)),
                  f"{uuid}: property inspector {inspector} is missing")

        check(resolve_image(action.get("Icon", "")),
              f"{uuid}: Icon {action.get('Icon')!r} resolves to no file")
        for i, state in enumerate(action.get("States") or []):
            check(resolve_image(state.get("Image", "")),
                  f"{uuid}: state {i} Image {state.get('Image')!r} "
                  f"resolves to no file")

        layout = (action.get("Encoder") or {}).get("layout")
        if layout and not BUILTIN_LAYOUT.match(layout):
            path = os.path.join(BUNDLE, layout)
            if check(os.path.isfile(path),
                     f"{uuid}: encoder layout {layout} is missing"):
                try:
                    items = json.load(open(path)).get("items") or []
                except ValueError as exc:
                    problems.append(f"{uuid}: layout {layout} is not valid "
                                    f"JSON: {exc}")
                    continue
                check(items, f"{uuid}: layout {layout} defines no items")
                for item in items:
                    check("key" in item and "type" in item and "rect" in item,
                          f"{uuid}: layout {layout} has an item missing "
                          f"key/type/rect")

    # Every file the entry point will import must be present in the bundle:
    # a module left out of a release zip is only discovered on someone's deck.
    for module in ("plugin.py", "owdeck/ws.py", "owdeck/graph.py",
                   "owdeck/ipc.py", "owdeck/owstate.py", "owdeck/render.py"):
        check(os.path.isfile(os.path.join(BUNDLE, module)),
              f"{module} is missing from the bundle")

    return report()


def report():
    if problems:
        print(f"{len(problems)} problem(s) in the plugin bundle:")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    print("plugin bundle OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
