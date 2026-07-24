# Steempeg v40

🚀 **NEW FEATURES:**

- **[Linux] First desktop Linux build:** Portable pack ships venv + bundled ffmpeg/libmpv (same stack as the Linux launcher). Run via `Steempeg-linux` / `Steempeg.sh` — no PyInstaller freeze on Bazzite/NVIDIA.
- **[Deck] Steam Deck channel:** Builds ship as `*_steamdeck.zip`; Update Center only pulls that channel’s assets.
- **Update channels (from 40T):** Windows / Linux / Steam Deck each fetch only their own zip (`Steempeg_v40.zip` untagged for Windows, `*_linux.zip`, `*_steamdeck.zip`). Old Windows updaters still work when the Windows zip is uploaded first.
- **Settings dialog:** Startup updates toggle, Desktop/Portable shell, notifications, hints reset, logs/cache, render priority + pause preview — one place for the day-to-day knobs.
- **Title-bar Settings:** `settings2` icon next to About `(i)`; opens the same dialog as the footer Settings entry.
- **Quality ladder:** `2160p (Divine Quality)`, `4320p (Goddess Quality)`, and taller Goddess presets with bitrate scaled by frame area from the 4320 table.
- **Desktop vs Portable shell chooser:** On startup pick Desktop or Portable. Portable locks into theatre with Choose a Clip / Render sheets.
- **Portable Render sheet:** Control strip, left-rail queue, desktop-style queue cards, empty-queue stub, multi-select in Clips Manager.
- **Title-bar About + updates:** About `(i)`, Update Available chip, Check for updates in About, and a silent GitHub check for the badge.

✨ **PLAYER & UI IMPROVEMENTS:**

- **[Linux] Progressive DASH remux:** Steam clips open without a “Preparing…” spinner — remux grows a seekable file and playback starts as soon as enough data exists.
- **[Linux] Prefetch remux:** Selecting a clip warms remux so the first play is faster; export sessions no longer stick a bad trim.
- **[Linux] Preview quality under xv/x11:** Prefers software scale — Homebrew Mesa can’t drive NVIDIA GL cleanly.
- **[Linux] Fake-maximize on startup:** Fills the screen work area. Native maximize is avoided on NVIDIA + XWayland so the UI doesn’t hard-freeze.
- **[Linux] NVENC in the encoder list:** Shows by default when the GPU probe succeeds.
- **Continuous UI density:** Deck comfort → compact scales smoothly instead of a hard width cliff; dialogs and toolbar chrome follow.
- **Theatre / portable polish:** Adaptive trim placement, pinned footer timer, rounded zoom overview.
- **Zoom overview `*` mark:** The second strip shows a playhead stick (`*`) that tracks where the timeline scroller sits in the full clip — like Steam’s overview cue.
- **Timeline playhead:** 3-part scroller assets (`scrollerhead2` / `body` / `back`) with a translucent hover ghost needle.
- **Quality combo:** Hides presets taller than the source; popup sized so visible items (+ Target File Size) fit without needless scroll.
- **Output Filename field:** Horizontal padding + fixed height so the underscore isn’t clipped.
- **Filter chrome:** Rounded-square filter button (like the sort combo); Cured health chip only when cured clips exist.
- **Library multi-select:** Ctrl/Alt/Shift+LMB; safer clip/export delete (unload media first).
- **Queue duplicates:** Allowed with a one-time notice; jobs tracked by id with clamped batch progress.
- **Fullscreen / immersive exit:** Less Aero flash, geometry restore under the cover, Esc clears a stuck transition.

📝 **OTHER UPDATES & FIXES:**

- **[Linux] Remux cache cap:** ~8 GiB with prune + free-space checks so `cache/mpd_playback/` can’t fill the disk again.
- **[Linux] libmpv bootstrap:** No longer RTLD_GLOBAL-preloads Homebrew Mesa/gallium into Qt (that was the “opens then dies” pack freeze).
- **[Linux] Update Center relaunch:** Install/restore starts `Steempeg-linux` (shell path), not a Windows `.exe` / `.bat` flow.
- **Short version + separate channel:** Display stays `40` / `40T`; `APP_UPDATE_CHANNEL` carries windows/linux/steamdeck so the title bar doesn’t say `40T-linux`.
- **Frozen Windows assets:** `settings2`, shell chooser icons (`desktop` / `portable`), `addclip`, `queue`, plus the rest of the manifest; console-free VBS helper for `pythonw`.
- **Portable Linux chrome:** Sheet sizing, queue card detach hang, and frameless resize fixes carried into 40.
- **Windows packaging:** `Steempeg_v40.zip` (untagged folder `Steempeg/`); Linux/Steam Deck keep `*_linux` / `*_steamdeck`.
