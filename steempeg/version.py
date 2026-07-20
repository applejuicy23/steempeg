"""Single source of truth for the application version.

``APP_VERSION_STR`` is what users see (title bar, About, logs) — keep it short
(``40T``, ``41``, …).

Update channels (from **40T** onward) live in ``APP_UPDATE_CHANNEL``, baked by
``newver_compilator.py`` per target:

* ``""`` / ``windows`` — Windows stream (``*_windows.zip``, legacy untagged zips)
* ``linux`` — desktop Linux (``*_linux.zip``)
* ``steamdeck`` — Steam Deck / SteamOS (``*_steamdeck.zip``)

Legacy builds that still encode the channel in the version string
(``40T-linux``) keep working via suffix parsing in the Update Center.
"""
APP_VERSION_STR = "40T"
APP_VERSION_FLOAT = 40.0
APP_UPDATE_CHANNEL = ""
