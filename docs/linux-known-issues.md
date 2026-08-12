# Linux known issues

Short notes for desktop Linux (not Windows). Open items only — resolved bugs stay checked for a release cycle, then drop.

## Player

- [x] **Screenshots:** Right-click → "Open screenshot" in the player panel does not open screenshots on Linux.
  - *Fixed:* Player open no longer trusts `QDesktopServices.openUrl()` (returns `True` without opening when DBus/`XDG_RUNTIME_DIR` are missing). Linux helpers run in-session (`new_session=False`), restore session env from `/run/user/$UID`, and prefer `kde-open5` on KDE before `xdg-open` / `gio`.
- [x] **Fullscreen:** Immersive/fullscreen does not cover the full display — it respects the bottom taskbar/panel (e.g. KDE) instead of true edge-to-edge fullscreen over the panel.
  - *Fixed:* Immersive chrome on non-Windows uses `showFullScreen()` so the compositor allows covering panels; enter finish re-asserts fullscreen state.
- [x] **Preview quality:** Preview player video looks heavily degraded / noisy / artifacty (visual interference during playback).
  - *Fixed:* Prefer host `libmpv` (NVIDIA EGL) over brew-linked bundled Mesa; use `vo=gpu` + `gpu-context=x11egl` when possible; avoid legacy `vo=xv` (mpv warns: bad quality). Fallback `x11`/`xv` forces `hwdec=no`.
