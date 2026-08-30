#!/bin/sh
# OpenDeck launches plugins from inside its AppImage, whose AppRun exports a
# python environment of its own. Left in place, PYTHONHOME and PYTHONPATH send
# the system interpreter looking for its standard library inside the AppImage
# and it aborts before running a line; LD_LIBRARY_PATH breaks anything linking
# against the host's OpenSSL or GLib. Scrub them and use the system python.
#
# stdin is redirected from /dev/null: nothing here reads it, and leaving it
# inherited means a plugin can block on a descriptor it never intended to use.
exec 0</dev/null
exec env \
  -u PYTHONHOME -u PYTHONPATH -u PYTHONDONTWRITEBYTECODE \
  -u LD_LIBRARY_PATH -u LD_PRELOAD \
  -u GIO_EXTRA_MODULES -u GSETTINGS_SCHEMA_DIR -u GDK_PIXBUF_MODULE_FILE \
  -u APPDIR -u APPIMAGE -u ARGV0 -u OWD \
  PATH=/usr/bin:/bin:/usr/local/bin \
  /usr/bin/python3 "$(dirname "$0")/plugin.py" "$@"
