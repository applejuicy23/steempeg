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
