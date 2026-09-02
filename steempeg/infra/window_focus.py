"""Bring Steempeg windows to the foreground (Windows).

Used by:
- ``steempeg:`` toast protocol / ``--raise-existing`` (restore running instance)
- Desktop startup (``force_widget_foreground``) so the main window is not
  buried under the launcher under Windows focus-stealing rules
"""
from __future__ import annotations

import logging
import os
import sys

_log = logging.getLogger(__name__)

_GW_OWNER = 4
_GW_HWNDPREV = 3  # next higher window in Z-order
_SW_RESTORE = 9
_SW_SHOW = 5
_HWND_TOPMOST = -1
_HWND_NOTOPMOST = -2
_SWP_NOSIZE = 0x0001
_SWP_NOMOVE = 0x0002
_SWP_NOZORDER = 0x0004
_SWP_NOACTIVATE = 0x0010
_SWP_SHOWWINDOW = 0x0040
_SWP_FRAMECHANGED = 0x0020
_SWP_NOOWNERZORDER = 0x0200
_GWL_EXSTYLE = -20
_WS_EX_TOPMOST = 0x00000008
_WS_EX_NOACTIVATE = 0x08000000


def _pid_from_instance_lock() -> int | None:
    try:
        from steempeg.infra.single_instance import instance_lock_path

        path = instance_lock_path()
        if not os.path.isfile(path):
            return None
        with open(path, "rb") as fh:
            raw = fh.read(256)
        # QLockFile: first line is the owning PID (UTF-8 decimal).
        line = raw.split(b"\n", 1)[0].strip()
        if line.isdigit():
            return int(line)
    except Exception as exc:
        _log.debug("lock pid read failed: %s", exc)
    return None


def _enum_top_level_hwnds_for_pid(pid: int) -> list[int]:
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    found: list[int] = []

    @WNDENUMPROC
    def _cb(hwnd, _lparam):  # type: ignore[misc]
        if not user32.IsWindowVisible(hwnd):
            return True
        if user32.GetWindow(hwnd, _GW_OWNER):
            return True
        proc = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(proc))
        if int(proc.value) == int(pid):
            found.append(int(hwnd))
        return True

    user32.EnumWindows(_cb, 0)
    return found


def _hwnd_title(hwnd: int) -> str:
    import ctypes

    user32 = ctypes.windll.user32
    n = user32.GetWindowTextLengthW(hwnd)
    if n <= 0:
        return ""
    buf = ctypes.create_unicode_buffer(n + 1)
    user32.GetWindowTextW(hwnd, buf, n + 1)
    return buf.value or ""


def _pick_main_hwnd(hwnds: list[int]) -> int | None:
    if not hwnds:
        return None
    scored: list[tuple[int, int]] = []
    for hwnd in hwnds:
        title = _hwnd_title(hwnd)
        score = 0
        if title.startswith("Steempeg"):
            score += 100
        if title:
            score += min(len(title), 40)
        try:
            import ctypes
            from ctypes import wintypes

            rect = wintypes.RECT()
            if ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect)):
                area = max(0, rect.right - rect.left) * max(0, rect.bottom - rect.top)
                score += min(area // 10000, 50)
        except Exception:
            pass
        scored.append((score, hwnd))
    scored.sort(reverse=True)
    return scored[0][1]


def _exstyle(hwnd: int) -> int:
    import ctypes

    return int(ctypes.windll.user32.GetWindowLongW(hwnd, _GWL_EXSTYLE))


def _has_topmost_bit(hwnd: int) -> bool:
    try:
        return bool(_exstyle(hwnd) & _WS_EX_TOPMOST)
    except Exception:
        return False


def _hwnd_is_strictly_above(hwnd: int, other: int) -> bool:
    """True when *hwnd* is higher than *other* in the global Z-order."""
    import ctypes

    user32 = ctypes.windll.user32
    cur = int(other)
    # Cap walks — z-order lists are finite but a bad HWND must not spin forever.
    for _ in range(512):
        cur = int(user32.GetWindow(cur, _GW_HWNDPREV) or 0)
        if not cur:
            return False
        if cur == int(hwnd):
            return True
    return False


def _same_process(hwnd_a: int, hwnd_b: int) -> bool:
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    pid_a = wintypes.DWORD()
    pid_b = wintypes.DWORD()
    user32.GetWindowThreadProcessId(int(hwnd_a), ctypes.byref(pid_a))
    user32.GetWindowThreadProcessId(int(hwnd_b), ctypes.byref(pid_b))
    return bool(pid_a.value) and int(pid_a.value) == int(pid_b.value)


def _is_foreign_foreground(shell_hwnd: int, fg: int) -> bool:
    """True when *fg* is a real other-app window (not Steempeg / our Tools)."""
    import ctypes

    if not fg or int(fg) == int(shell_hwnd):
        return False
    user32 = ctypes.windll.user32
    if user32.IsChild(int(shell_hwnd), int(fg)):
        return False
    if _same_process(shell_hwnd, fg):
        return False
    owner = int(user32.GetWindow(int(fg), _GW_OWNER) or 0)
    if owner and (
        owner == int(shell_hwnd) or user32.IsChild(int(shell_hwnd), owner)
    ):
        return False
    return True


def _clear_topmost(hwnd: int, *, reshuffle_z: bool = False) -> None:
    """Ensure *hwnd* actually leaves the always-on-top band.

    Windows only honors topmost changes via ``SetWindowPos(HWND_NOTOPMOST)``.
    Stripping ``WS_EX_TOPMOST`` with ``SetWindowLong`` + ``SWP_NOZORDER`` is a
    no-op for Z-order: the style bit can disappear while the window stays in the
    topmost band — Explorer/browsers then map *under* Steempeg forever.

    The older style-only path tried to avoid ``HWND_NOTOPMOST`` parking the shell
    at the top of the *normal* band (which buried tabs during mpv play). That
    race is handled by ``demote_hwnd_below_foreground`` when another app already
    owns the foreground — do **not** resurrect style-only clears.

    Never use ``SWP_FRAMECHANGED`` here: on frameless + ``wid=`` embed that
    sends ``WM_NCCALCSIZE`` and can orphan the mpv child HWND as a floating
    video surface (seen when opening Start / losing focus in windowed mode).

    ``reshuffle_z`` is kept for call-site compatibility; both paths demote for
    real when the topmost bit is set (the only durable fix).
    """
    import ctypes

    user32 = ctypes.windll.user32
    try:
        ex = int(user32.GetWindowLongW(hwnd, _GWL_EXSTYLE))
        if not (ex & _WS_EX_TOPMOST):
            return
        user32.SetWindowLongW(hwnd, _GWL_EXSTYLE, ex & ~_WS_EX_TOPMOST)
        # HWND_NOTOPMOST is mandatory — style-only left us stuck in the topmost band.
        flags = _SWP_NOMOVE | _SWP_NOSIZE | _SWP_NOACTIVATE
        user32.SetWindowPos(hwnd, _HWND_NOTOPMOST, 0, 0, 0, 0, flags)
        _ = reshuffle_z  # API compat; demotion always applies when bit was set
    except Exception as exc:
        _log.debug("clear_topmost failed hwnd=%s: %s", hwnd, exc)


def demote_hwnd_below_foreground(hwnd: int) -> None:
    """Tuck *hwnd* under a foreign foreground window; drop stuck topmost.

    Root cause this targets (Emily / «раз и навсегда»): while mpv ``wid=`` +
    ``vo=gpu`` presents, Steempeg can sit above Explorer/browser even when that
    other app is ``GetForegroundWindow`` — either from a stuck topmost band
    (ineffective style-only clear after a focus flash) or from Z-order steal
    without activation. Idle / no clip does not present, so ordering looks fine.

    ``SetWindowPos(hwnd, fg, …)`` places us directly below *fg* (fg precedes us
    in Z-order) and, when *fg* is non-topmost, also ejects us from the topmost
    band — without the ``HWND_NOTOPMOST`` “jump to top of normal band” park.

    Never raises / activates Steempeg. Never ``SWP_FRAMECHANGED`` (mpv orphan).
    Callers must skip Start / Search / Snipping via
    ``should_skip_hwnd_ops_for_foreground``.
    """
    import ctypes

    user32 = ctypes.windll.user32
    try:
        hwnd = int(hwnd)
        if not hwnd or not user32.IsWindow(hwnd):
            return
        fg = int(user32.GetForegroundWindow() or 0)
        had_topmost = _has_topmost_bit(hwnd)
        if had_topmost:
            user32.SetWindowLongW(
                hwnd, _GWL_EXSTYLE, _exstyle(hwnd) & ~_WS_EX_TOPMOST
            )

        flags = _SWP_NOMOVE | _SWP_NOSIZE | _SWP_NOACTIVATE
        if _is_foreign_foreground(hwnd, fg):
            # Demote when covering FG, or when still carrying topmost over it.
            if had_topmost or _hwnd_is_strictly_above(hwnd, fg):
                user32.SetWindowPos(hwnd, fg, 0, 0, 0, 0, flags)
                return

        if had_topmost:
            user32.SetWindowPos(hwnd, _HWND_NOTOPMOST, 0, 0, 0, 0, flags)
    except Exception as exc:
        _log.debug("demote_hwnd_below_foreground failed hwnd=%s: %s", hwnd, exc)


def demote_widget_below_foreground(widget) -> bool:
    """Qt wrapper for :func:`demote_hwnd_below_foreground`."""
    if sys.platform != "win32" or widget is None:
        return False
    try:
        hwnd = int(widget.winId())
        if not hwnd:
            return False
        demote_hwnd_below_foreground(hwnd)
        return True
    except Exception as exc:
        _log.debug("demote_widget_below_foreground failed: %s", exc)
        return False


def _topmost_flash(hwnd: int) -> None:
    """Brief TOPMOST → NOTOPMOST so Windows allows SetForegroundWindow.

    Always clears topmost in ``finally`` so a failed second hop cannot leave the
    shell always-on-top over Explorer / other apps.
    """
    import ctypes

    user32 = ctypes.windll.user32
    # Do not use SWP_SHOWWINDOW here — it can race with maximize/chrome and
    # leave WS_EX_TOPMOST stuck after the NOTOPMOST hop.
    flags = _SWP_NOMOVE | _SWP_NOSIZE | _SWP_NOACTIVATE
    try:
        user32.SetWindowPos(hwnd, _HWND_TOPMOST, 0, 0, 0, 0, flags)
    finally:
        _clear_topmost(hwnd, reshuffle_z=True)


def _force_foreground(hwnd: int) -> None:
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32

    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, _SW_RESTORE)
    else:
        user32.ShowWindow(hwnd, _SW_SHOW)

    foreground = user32.GetForegroundWindow()
    if foreground == hwnd:
        # Already front — only strip a stuck TOPMOST bit; do not BringWindowToTop
        # (that re-stacks Steempeg over other apps on every no-op raise).
        # HWND_NOTOPMOST is required; style-only leaves the topmost band intact.
        _clear_topmost(hwnd, reshuffle_z=True)
        return

    pid_fore = wintypes.DWORD()
    tid_fore = user32.GetWindowThreadProcessId(foreground, ctypes.byref(pid_fore))
    tid_target = user32.GetWindowThreadProcessId(hwnd, None)
    tid_cur = kernel32.GetCurrentThreadId()

    attached_fore = False
    attached_target = False
    try:
        if tid_fore and tid_fore != tid_cur:
            attached_fore = bool(user32.AttachThreadInput(tid_cur, tid_fore, True))
        if tid_target and tid_target != tid_cur:
            attached_target = bool(user32.AttachThreadInput(tid_cur, tid_target, True))
        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)
        user32.SetActiveWindow(hwnd)
        try:
            user32.SetFocus(hwnd)
        except Exception:
            pass
        # Focus-stealing rules often ignore SetForegroundWindow alone when
        # launched from another app (terminal, Steam, Explorer sibling). A
        # momentary topmost flash is the reliable workaround.
        if user32.GetForegroundWindow() != hwnd:
            _topmost_flash(hwnd)
            user32.SetForegroundWindow(hwnd)
            user32.BringWindowToTop(hwnd)
    finally:
        if attached_target:
            user32.AttachThreadInput(tid_cur, tid_target, False)
        if attached_fore:
            user32.AttachThreadInput(tid_cur, tid_fore, False)
        # We intend to be the foreground app — HWND_NOTOPMOST is correct here
        # (top of the normal band). Never leave WS_EX_TOPMOST stuck.
        _clear_topmost(hwnd, reshuffle_z=True)


def clear_widget_topmost(widget, *, reshuffle_z: bool = False) -> bool:
    """Strip stuck always-on-top from a Qt top-level widget (Windows).

    Always issues ``HWND_NOTOPMOST`` when the bit is set (style-only clear does
    not leave the topmost band). When another app already owns the foreground,
    prefer :func:`demote_widget_below_foreground` so we tuck *under* that app
    instead of parking at the top of the normal Z-order.
    """
    if sys.platform != "win32":
        return False
    try:
        hwnd = int(widget.winId())
        if not hwnd:
            return False
        _clear_topmost(hwnd, reshuffle_z=reshuffle_z)
        return True
    except Exception as exc:
        _log.debug("clear_widget_topmost failed: %s", exc)
        return False


_GWLP_HWNDPARENT = -8


def detach_tool_ownership(widget) -> None:
    """Ensure a Qt Tool is not owned / transient-parented to the Steempeg shell.

    Owned Tools re-stack their owner on every ``show()`` (Explorer / browser get
    buried under Steempeg). Qt often assigns a transient parent even when
    ``QWidget(None)`` — clear both the Win32 owner and Qt transient link.
    """
    if sys.platform != "win32" or widget is None:
        return
    try:
        widget.createWinId()
        hwnd = int(widget.winId())
        if not hwnd:
            return
        import ctypes

        user32 = ctypes.windll.user32
        # Drop Win32 owner (GWLP_HWNDPARENT). Ignore failures on exotic HWNDs.
        try:
            user32.SetWindowLongPtrW(hwnd, _GWLP_HWNDPARENT, 0)
        except Exception:
            try:
                user32.SetWindowLongW(hwnd, _GWLP_HWNDPARENT, 0)
            except Exception:
                pass
        try:
            wh = widget.windowHandle()
            if wh is not None and wh.transientParent() is not None:
                wh.setTransientParent(None)
        except Exception:
            pass
    except Exception as exc:
        _log.debug("detach_tool_ownership failed: %s", exc)


def prepare_shell_for_modeless_dialog(shell, dialog) -> None:
    """Demote shell topmost, then put *dialog* in front (open / restore path)."""
    shell_win = None
    if shell is not None:
        try:
            shell_win = shell.window() if hasattr(shell, "window") else shell
            clear_widget_topmost(shell_win, reshuffle_z=True)
        except Exception:
            shell_win = None
    if shell_win is not None:
        try:
            from steempeg.ui.window_chrome import release_windows_edge_resize_grabs

            release_windows_edge_resize_grabs(shell_win)
        except Exception:
            pass
    if dialog is None:
        return
    try:
        dialog.raise_()
        dialog.activateWindow()
        wh = dialog.windowHandle()
        if wh is not None:
            wh.requestActivate()
    except RuntimeError:
        return
    force_widget_foreground(dialog)
    try:
        from steempeg.ui.window_chrome import force_app_cursor_resync

        force_app_cursor_resync()
    except Exception:
        pass


def on_shell_internal_dialog_focus(widget) -> None:
    """Shell lost activation to another Steempeg dialog (Render Settings, etc.).

    Drop the shell out of the always-on-top band (``HWND_NOTOPMOST``), then
    re-raise every visible SteempegDialog. Style-only TOPMOST clear left the
    shell painted above modeless dialogs — post-v48 «dialog under app» bug.
    """
    clear_widget_topmost(widget, reshuffle_z=True)
    try:
        from steempeg.ui.window_chrome import release_windows_edge_resize_grabs

        release_windows_edge_resize_grabs(widget)
    except Exception:
        pass
    raise_visible_steempeg_dialogs()


def steempeg_internal_dialog_active() -> bool:
    """True when *focus* is on a Steempeg dialog (same app still ApplicationActive).

    Must NOT treat «any visible dialog» as active — that made Win+Shift+S /
    Snipping Tool abort: we re-raised ourselves and stole foreground mid-capture.
    """
    if sys.platform != "win32":
        return False
    try:
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QGuiApplication
        from PySide6.QtWidgets import QApplication

        from steempeg.ui.widgets.dialog_chrome import SteempegDialog

        app = QApplication.instance()
        if app is None:
            return False
        # OS focus is outside Steempeg entirely (Snipping Tool, Explorer, …).
        if app.applicationState() != Qt.ApplicationState.ApplicationActive:
            return False

        candidates = []
        fg = app.activeWindow()
        if fg is not None:
            candidates.append(fg)
        try:
            fw = QGuiApplication.focusWindow()
            if fw is not None:
                candidates.append(fw)
        except Exception:
            pass

        for fg in candidates:
            w = fg
            while w is not None:
                try:
                    if isinstance(w, SteempegDialog) and w.isVisible():
                        return True
                except RuntimeError:
                    break
                try:
                    w = w.parentWidget()
                except RuntimeError:
                    break
        return False
    except Exception:
        return False


def foreground_is_screen_capture() -> bool:
    """True when Windows Snipping / ScreenClippingHost owns the foreground."""
    if sys.platform != "win32":
        return False
    try:
        import ctypes

        user32 = ctypes.windll.user32
        hwnd = int(user32.GetForegroundWindow() or 0)
        if not hwnd:
            return False
        # Class name is the reliable signal (titles localize).
        buf = ctypes.create_unicode_buffer(256)
        if not user32.GetClassNameW(hwnd, buf, 256):
            return False
        cls = (buf.value or "").lower()
        needles = (
            "screenclipping",
            "snippingtool",
            "snipoverlay",
            "screensketch",
        )
        return any(n in cls for n in needles)
    except Exception:
        return False


def foreground_is_windows_shell_ui() -> bool:
    """True when Start / Search / Task View owns the foreground.

    Opening Пуск while a clip plays used to race our TOPMOST clear
    (``SWP_FRAMECHANGED``) and orphan the mpv ``wid=`` child as a floating
    video rectangle. Skip HWND churn for these hosts the same way we skip
    Snipping Tool.
    """
    if sys.platform != "win32":
        return False
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        hwnd = int(user32.GetForegroundWindow() or 0)
        if not hwnd:
            return False
        buf = ctypes.create_unicode_buffer(256)
        if user32.GetClassNameW(hwnd, buf, 256):
            cls = (buf.value or "").lower()
            class_needles = (
                "immersivelauncher",
                "windows.ui.core.corewindow",
                "xamlexplorerhostislandwindow",
                "multitaskingviewframe",  # Task View
                "windows.internal.shell",
            )
            if any(n in cls for n in class_needles):
                return True
        # Process name is stable across Win10/11 Start / Search hosts.
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if not pid.value:
            return False
        kernel32 = ctypes.windll.kernel32
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        handle = kernel32.OpenProcess(
            PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid.value)
        )
        if not handle:
            return False
        try:
            size = wintypes.DWORD(260)
            path_buf = ctypes.create_unicode_buffer(260)
            if kernel32.QueryFullProcessImageNameW(handle, 0, path_buf, ctypes.byref(size)):
                name = (path_buf.value or "").replace("/", "\\").lower()
                leaf = name.rsplit("\\", 1)[-1]
                return leaf in (
                    "startmenuexperiencehost.exe",
                    "searchhost.exe",
                    "searchapp.exe",
                    "shellexperiencehost.exe",
                )
        finally:
            kernel32.CloseHandle(handle)
        return False
    except Exception:
        return False


def steempeg_popup_menu_active() -> bool:
    """True while a Qt popup (ClipCard QMenu, etc.) owns the grab.

    Shell ActivationChange fires when a QMenu opens (main window is no longer
    ``isActiveWindow``) but the process stays ``ApplicationActive``. Running
    ``SetWindowPos`` / TOPMOST clears on the frameless shell in that window
    orphans the mpv ``wid=`` child — video floats over the Render Queue while
    the player viewport stays black. Same class of bug as Start-menu detach.
    """
    if sys.platform != "win32":
        return False
    try:
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance()
        if app is None:
            return False
        if app.activePopupWidget() is not None:
            return True
        return False
    except Exception:
        return False


def should_skip_hwnd_ops_for_foreground() -> bool:
    """Snipping / Start / Search / our QMenu — do not touch shell HWND z-order."""
    return (
        foreground_is_screen_capture()
        or foreground_is_windows_shell_ui()
        or steempeg_popup_menu_active()
    )


def raise_visible_steempeg_dialogs() -> None:
    """Bring every visible SteempegDialog above the main shell (Windows)."""
    if sys.platform != "win32":
        return
    try:
        from PySide6.QtWidgets import QApplication

        from steempeg.ui.widgets.dialog_chrome import SteempegDialog

        app = QApplication.instance()
        if app is None:
            return
        for w in app.topLevelWidgets():
            try:
                if not isinstance(w, SteempegDialog) or not w.isVisible():
                    continue
                if getattr(w, "_map_suppressed", False):
                    continue
                w.raise_()
                w.activateWindow()
                force_widget_foreground(w)
            except RuntimeError:
                continue
            except Exception:
                continue
    except Exception as exc:
        _log.debug("raise_visible_steempeg_dialogs failed: %s", exc)


def on_shell_lost_foreground(widget) -> None:
    """Call when Steempeg is no longer the OS foreground app.

    Durable demotion (not a style-only TOPMOST clear):
    - Drop stuck always-on-top
    - If a foreign window owns focus but Steempeg still paints above it
      (mpv ``vo=gpu`` present / prior HWND_NOTOPMOST park), tuck the shell
      directly under that foreground HWND

    Also sweeps every top-level Steempeg HWND — Portable sheets / Tools can
    carry the topmost bit too.

    Never raise / activate Steempeg here — Win+Shift+S and Snipping Tool abort
    if we steal foreground mid-capture. Same for Start / Search / ClipCard
    QMenu (``SetWindowPos`` on the frameless shell orphans mpv ``wid=``).
    """
    if should_skip_hwnd_ops_for_foreground():
        return
    demote_widget_below_foreground(widget)
    # Other top-levels (Tools / sheets) may still carry WS_EX_TOPMOST.
    clear_all_steempeg_topmost()
    # clear_all uses HWND_NOTOPMOST which can re-park the shell at the top of
    # the normal band — demote again under the real foreground app.
    demote_widget_below_foreground(widget)


def clear_all_steempeg_topmost() -> None:
    """Strip stuck always-on-top from every Qt top-level window (Windows)."""
    if sys.platform != "win32":
        return
    try:
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance()
        if app is None:
            return
        for w in app.topLevelWidgets():
            try:
                if w is None or not w.isWindow():
                    continue
                clear_widget_topmost(w, reshuffle_z=True)
            except RuntimeError:
                continue
            except Exception:
                continue
    except Exception as exc:
        _log.debug("clear_all_steempeg_topmost failed: %s", exc)


def yield_foreground_to_external(anchor=None) -> None:
    """Drop TOPMOST before opening Explorer / browsers / native pickers.

    If Steempeg stays always-on-top, those windows map *under* us and we often
    remain ApplicationActive — so the focus-loss clear never runs. Call this
    right before ``os.startfile`` / ``QFileDialog`` / ``webbrowser.open``.
    """
    if sys.platform != "win32":
        return
    if anchor is not None:
        try:
            win = anchor.window() if hasattr(anchor, "window") else anchor
            # Real demotion — style-only left us in the topmost band.
            clear_widget_topmost(win, reshuffle_z=True)
            demote_widget_below_foreground(win)
        except Exception:
            pass
    clear_all_steempeg_topmost()
    if anchor is not None:
        try:
            win = anchor.window() if hasattr(anchor, "window") else anchor
            demote_widget_below_foreground(win)
        except Exception:
            pass


def reseat_native_embed_child(widget) -> bool:
    """Re-parent an mpv ``wid=`` child if Win32 parenting drifted from Qt.

    Shell ``SetWindowPos`` / focus churn (ClipCard QMenu, Explorer yield) can
    leave the native child as a floating HWND — video paints offset over the
    UI while ``video_container`` stays black. ``SetParent`` back to the Qt
    parent, then geometry update, without ``SWP_FRAMECHANGED``.
    """
    if sys.platform != "win32" or widget is None:
        return False
    try:
        import ctypes

        parent = widget.parentWidget()
        if parent is None:
            return False
        widget.createWinId()
        parent.createWinId()
        child = int(widget.winId())
        parent_hwnd = int(parent.winId())
        if not child or not parent_hwnd:
            return False
        user32 = ctypes.windll.user32
        cur = int(user32.GetParent(child) or 0)
        if cur != parent_hwnd:
            user32.SetParent(child, parent_hwnd)
            _log.info(
                "reseat_native_embed_child: SetParent hwnd=%s -> %s (was %s)",
                child,
                parent_hwnd,
                cur,
            )
        mark_embed_noactivate(widget)
        return True
    except Exception as exc:
        _log.debug("reseat_native_embed_child failed: %s", exc)
        return False


def mark_embed_noactivate(widget) -> bool:
    """Tag an embedded video HWND so it cannot activate the Steempeg shell.

    libmpv ``wid=`` paints into a native child. On Windows that child can still
    yank activation (and Z-order) toward the owner while frames present — which
    matches «Explorer hides only while a clip is open».
    """
    if sys.platform != "win32" or widget is None:
        return False
    try:
        import ctypes

        widget.createWinId()
        hwnd = int(widget.winId())
        if not hwnd:
            return False
        user32 = ctypes.windll.user32
        ex = int(user32.GetWindowLongW(hwnd, _GWL_EXSTYLE))
        if ex & _WS_EX_NOACTIVATE:
            return True
        user32.SetWindowLongW(hwnd, _GWL_EXSTYLE, ex | _WS_EX_NOACTIVATE)
        # No SWP_FRAMECHANGED — same orphan risk as clear_topmost on wid= embeds.
        flags = (
            _SWP_NOMOVE
            | _SWP_NOSIZE
            | _SWP_NOZORDER
            | _SWP_NOOWNERZORDER
            | _SWP_NOACTIVATE
        )
        user32.SetWindowPos(hwnd, 0, 0, 0, 0, 0, flags)
        return True
    except Exception as exc:
        _log.debug("mark_embed_noactivate failed: %s", exc)
        return False


def force_widget_foreground(widget) -> bool:
    """Bring a Qt top-level widget forward on Windows (startup / show).

    No-op on non-Windows. Uses the same Win32 path as toast ``--raise-existing``.
    Never leaves the window permanently always-on-top.
    """
    if sys.platform != "win32":
        return False
    try:
        hwnd = int(widget.winId())
        if not hwnd:
            return False
        _force_foreground(hwnd)
        _log.info("force_widget_foreground: focused hwnd=%s", hwnd)
        return True
    except Exception as exc:
        _log.debug("force_widget_foreground failed: %s", exc)
        return False


def raise_steempeg_window() -> bool:
    """Restore + focus the running Steempeg main window. No Qt required."""
    if sys.platform != "win32":
        return False
    try:
        pid = _pid_from_instance_lock()
        hwnds: list[int] = []
        if pid:
            hwnds = _enum_top_level_hwnds_for_pid(pid)
        if not hwnds:
            # Fallback: any visible top-level titled Steempeg…
            import ctypes
            from ctypes import wintypes

            user32 = ctypes.windll.user32
            WNDENUMPROC = ctypes.WINFUNCTYPE(
                wintypes.BOOL, wintypes.HWND, wintypes.LPARAM
            )
            titled: list[int] = []

            @WNDENUMPROC
            def _cb(hwnd, _lparam):  # type: ignore[misc]
                if not user32.IsWindowVisible(hwnd):
                    return True
                if user32.GetWindow(hwnd, _GW_OWNER):
                    return True
                if _hwnd_title(int(hwnd)).startswith("Steempeg"):
                    titled.append(int(hwnd))
                return True

            user32.EnumWindows(_cb, 0)
            hwnds = titled

        hwnd = _pick_main_hwnd(hwnds)
        if not hwnd:
            _log.info("raise_steempeg_window: no window found")
            return False
        _force_foreground(hwnd)
        _log.info("raise_steempeg_window: focused hwnd=%s", hwnd)
        return True
    except Exception as exc:
        _log.warning("raise_steempeg_window failed: %s", exc)
        return False


def ensure_toast_protocol_registered() -> None:
    """HKCU URL protocol ``steempeg:`` → ``--raise-existing`` (toast click)."""
    if sys.platform != "win32":
        return
    try:
        import winreg

        if getattr(sys, "frozen", False):
            cmd = f'"{os.path.abspath(sys.executable)}" --raise-existing "%1"'
        else:
            cmd = f'"{os.path.abspath(sys.executable)}" -m steempeg --raise-existing "%1"'

        base = r"Software\Classes\steempeg"
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, base) as key:
            winreg.SetValueEx(key, None, 0, winreg.REG_SZ, "URL:Steempeg Protocol")
            winreg.SetValueEx(key, "URL Protocol", 0, winreg.REG_SZ, "")
        with winreg.CreateKeyEx(
            winreg.HKEY_CURRENT_USER, base + r"\shell\open\command"
        ) as key:
            winreg.SetValueEx(key, None, 0, winreg.REG_SZ, cmd)
        _log.info("Registered steempeg: protocol → %s", cmd)
    except Exception as exc:
        _log.debug("toast protocol registration failed: %s", exc)


TOAST_PROTOCOL_LAUNCH = "steempeg:focus"
