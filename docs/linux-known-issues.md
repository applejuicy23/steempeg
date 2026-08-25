# Linux known issues

Short notes for desktop Linux / SteamOS.

---

## v45.1 (fixed)

- **App icon in dock:** GNOME showed a generic placeholder because the portable pack runs as `python -m steempeg` (WM_CLASS=`python`) and had no installed `.desktop` / theme icon. First launch now writes `~/.local/share/applications/steempeg.desktop` and a hicolor `steempeg.png`.
- **Terminal alongside the app:** Nautilus/GNOME “run script” opened a console. The app now detaches like Windows `FreeConsole`. Debug: `STEEMPEG_KEEP_CONSOLE=1`.
- **GLib-GObject-CRITICAL / Kvantum / portal noise:** leftover KDE `QT_STYLE_OVERRIDE=kvantum` + gtk3 platform theme on GNOME. Cleared; Fusion + `xdgdesktopportal`.

---

## Deferred to 44.1 (still open)

- Settings helper text clipped (HiDPI labels under dropdowns).
- Render queue not cleared after “Open history” (desktop-wide).

---

## Fixed (earlier)

- Screenshots open (session env + kde-open5), fullscreen over taskbar, preview vo=gpu — see commit `1cf8419` / v44 Linux pack.

---

## v47 (fixed locally — verify)

- **Rapid clip-switch hang:** Remux-cache preview could leave `_is_switching` / `_awaiting_first_frame` stuck so clicks did nothing while mpv kept playing. Soft finish + cancel + watchdog now clear both gates; same-clip spam paths log.
- **First-clip black preview (NVIDIA/XWayland):** First session open (e.g. CS2 HEVC remux) could play audio while the embed stayed black; switching clips forced a VO reconfig and looked fine. Cause: libmpv created under ``video_blank_frame`` (parked 0×0 wid). Fix: map ``video_container`` + real geometry before first ``winId()``, and re-kick geometry on reveal.
- **Settings → UI font (Linux-only):** Widget code called `QFont("Segoe UI")` / `setFamily("Segoe UI")` (fontconfig alias → Adwaita/Noto), and System mode used bare `QFont()` which copies the current app font. Fixed: real-Segoe detection, in-process Selawik via `addApplicationFont`, `pin_ui_font` / live `FONT_APP` in QSS; System picks a real desktop sans. **Windows:** no UI font combo; classic Segoe only.
