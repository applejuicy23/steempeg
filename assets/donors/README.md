# Per-game DASH init donors

Steempeg salvage borrows a decoder header (`init-stream0.m4s`) when a dead
clip's own init is missing. These files are **per Steam `app_id`** — there is
no universal donor.

Layout:

```
assets/donors/<app_id>/init-stream0.m4s   # video (required)
assets/donors/<app_id>/init-stream1.m4s   # audio (optional)
```

Harvest from healthy library clips:

```
python tools/harvest_donors.py
```

Do not invent inits. Only copy from known-good clips of the same game.
