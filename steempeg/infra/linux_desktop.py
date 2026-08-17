"""Linux session glue: dock icon, .desktop, GLib/Qt theme noise.

GNOME matches the window WM_CLASS to a Freedesktop desktop file. Portable
packs run as ``venv/bin/python -m steempeg``, so the class is ``python`` and
the dock shows a generic placeholder. We rewrite argv, install
``steempeg.desktop`` with an absolute icon path, and drop leftover KDE
(Kvantum / gtk3) theming that floods GLib-CRITICAL on GNOME.
"""
from __future__ import annotations

import logging
import os
import shutil
import sys
from pathlib import Path

# Keep the ctypes callback alive (GLib holds a raw function pointer).
_GLIB_LOG_CB = None


def _keep_console() -> bool:
    return os.environ.get("STEEMPEG_KEEP_CONSOLE", "0") == "1"


def _session_desktop() -> str:
    return " ".join(
        (
            os.environ.get("XDG_CURRENT_DESKTOP") or "",
            os.environ.get("XDG_SESSION_DESKTOP") or "",
            os.environ.get("DESKTOP_SESSION") or "",
        )
    ).lower()


def _is_gtk_session() -> bool:
    desk = _session_desktop()
    return any(
        name in desk
        for name in (
            "gnome",
            "cinnamon",
            "budgie",
            "pantheon",
            "unity",
            "cosmic",
            "xfce",
            "mate",
            "lxde",
        )
    )


def prepare_linux_qt_environment() -> None:
    """Call before ``QApplication`` — env, argv, GLib filter, optional detach."""
    if sys.platform == "win32":
        return

    # Portable PySide only ships Fusion/Windows. Kvantum from a KDE session
    # (or leftover env after switching to GNOME) just prints a warning.
    style = (os.environ.get("QT_STYLE_OVERRIDE") or "").strip().lower()
    if style in {"kvantum", "kvantum-dark", "kvantum-light"}:
        os.environ.pop("QT_STYLE_OVERRIDE", None)

    # gtk3 platform theme + GNOME's GTK4/portal stack → GParam CRITICAL flood.
    # Leave KDE/LXQt alone so Qt can pick the native ``kde`` plugin.
    theme = (os.environ.get("QT_QPA_PLATFORMTHEME") or "").strip().lower()
    gtk_leftover = theme in {"gtk3", "gtk2", "gnome"}
    if gtk_leftover or (_is_gtk_session() and theme in {"", "gtk3", "gtk2", "gnome"}):
        os.environ["QT_QPA_PLATFORMTHEME"] = "xdgdesktopportal"
    # Duplicate portal app-id registration is noisy and not user-actionable.
    if "QT_LOGGING_RULES" not in os.environ:
        os.environ["QT_LOGGING_RULES"] = "qt.qpa.services.warning=false"

    # WM_CLASS / portal app-id must not be "python".
    if sys.argv:
        sys.argv[0] = "steempeg"

    try:
        from PySide6.QtGui import QGuiApplication

        QGuiApplication.setDesktopFileName("steempeg")
    except Exception:
        pass

    _install_glib_log_filter()
    _detach_from_terminal()


def apply_linux_qt_app(app) -> None:
    """Call right after ``QApplication`` exists."""
    if sys.platform == "win32":
        return
    try:
        app.setStyle("Fusion")
    except Exception:
        pass
    try:
        if hasattr(app, "setDesktopFileName"):
            app.setDesktopFileName("steempeg")
    except Exception:
        pass
    try:
        from PySide6.QtGui import QGuiApplication

        QGuiApplication.setDesktopFileName("steempeg")
    except Exception:
        pass


def install_linux_desktop_entry() -> None:
    """Write ``~/.local/share/applications/steempeg.desktop`` + hicolor icon."""
    if sys.platform == "win32":
        return
    try:
        from steempeg.infra.paths import get_install_root, get_resource_path
    except Exception:
        return

    icon_src = get_resource_path("logo.png")
    if not icon_src or not os.path.isfile(icon_src):
        logging.warning("Linux desktop: logo.png missing, dock icon will stay generic")
        return

    home = Path.home()
    apps = home / ".local" / "share" / "applications"
    hicolor = home / ".local" / "share" / "icons" / "hicolor" / "256x256" / "apps"
    pixmaps = home / ".local" / "share" / "pixmaps"
    try:
        apps.mkdir(parents=True, exist_ok=True)
        hicolor.mkdir(parents=True, exist_ok=True)
        pixmaps.mkdir(parents=True, exist_ok=True)
    except OSError:
        logging.debug("Linux desktop: could not create XDG dirs", exc_info=True)
        return

    icon_dst = hicolor / "steempeg.png"
    try:
        if not icon_dst.is_file() or os.path.getmtime(icon_src) > icon_dst.stat().st_mtime:
            shutil.copy2(icon_src, icon_dst)
        shutil.copy2(icon_src, pixmaps / "steempeg.png")
    except OSError:
        logging.debug("Linux desktop: icon copy failed", exc_info=True)

    root = get_install_root()
    exec_line, working = _exec_and_path(root)
    desk = apps / "steempeg.desktop"
    body = (
        "[Desktop Entry]\n"
        "Version=1.0\n"
        "Type=Application\n"
        "Name=Steempeg\n"
        "Comment=Steam Game Recording clips\n"
        f"Exec={exec_line}\n"
        f"Path={working}\n"
        "Icon=steempeg\n"
        "Terminal=false\n"
        "Categories=AudioVideo;Video;Player;\n"
        "StartupNotify=true\n"
        "StartupWMClass=steempeg\n"
        "X-GNOME-UsesNotifications=true\n"
    )
    try:
        old = desk.read_text(encoding="utf-8") if desk.is_file() else ""
        if old != body:
            desk.write_text(body, encoding="utf-8")
            os.chmod(desk, 0o755)
            logging.info("Linux desktop: wrote %s", desk)
    except OSError:
        logging.debug("Linux desktop: failed to write .desktop", exc_info=True)
        return

    # Best-effort caches — missing on some Atomic images.
    for cmd in (
        ["update-desktop-database", str(apps)],
        ["gtk-update-icon-cache", "-f", "-t", str(home / ".local" / "share" / "icons" / "hicolor")],
    ):
        try:
            import subprocess

            subprocess.run(cmd, check=False, capture_output=True, timeout=8)
        except Exception:
            pass


def _exec_and_path(root: str) -> tuple[str, str]:
    for name in ("Steempeg-linux", "Steempeg.sh", "Steempeg"):
        candidate = os.path.join(root, name)
        if os.path.isfile(candidate):
            return _desktop_exec_escape(candidate), root
    py = sys.executable or "python3"
    return f"{_desktop_exec_escape(py)} -m steempeg", root


def _desktop_exec_escape(path: str) -> str:
    if any(ch.isspace() or ch in "\"'\\" for ch in path):
        return '"' + path.replace('"', r"\"") + '"'
    return path


def _install_glib_log_filter() -> None:
    """Swallow GObject param-spec CRITICAL spam; keep real GLib errors."""
    global _GLIB_LOG_CB
    try:
        from ctypes import CFUNCTYPE, c_char_p, c_int, c_void_p, CDLL

        glib = CDLL("libglib-2.0.so.0")
        GLogFunc = CFUNCTYPE(None, c_char_p, c_int, c_char_p, c_void_p)

        def _handler(domain, level, message, userdata):
            text = (message or b"").decode("utf-8", "replace")
            if (
                "GParam" in text
                or "g_value_get_gtype" in text
                or "invalid param spec type" in text
            ):
                return
            try:
                sys.stderr.write(text + "\n")
            except Exception:
                pass

        _GLIB_LOG_CB = GLogFunc(_handler)
        glib.g_log_set_default_handler(_GLIB_LOG_CB, None)
    except Exception:
        pass


def _detach_from_terminal() -> None:
    """Close the extra terminal Nautilus/GNOME opens for scripts (like Windows FreeConsole)."""
    if _keep_console():
        return
    if os.environ.get("STEEMPEG_DETACHED") == "1":
        return
    if not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
        return
    # .desktop launches have no tty — nothing to detach.
    try:
        if not any(os.isatty(fd) for fd in (0, 1, 2)):
            return
    except Exception:
        pass
    try:
        pid = os.fork()
    except OSError:
        return
    if pid > 0:
        os._exit(0)
    try:
        os.setsid()
    except OSError:
        pass
    os.environ["STEEMPEG_DETACHED"] = "1"
    try:
        devnull = open(os.devnull, "w", encoding="utf-8", errors="ignore")
        os.dup2(devnull.fileno(), 1)
        os.dup2(devnull.fileno(), 2)
        sys.stdout = devnull
        sys.stderr = devnull
    except Exception:
        pass
