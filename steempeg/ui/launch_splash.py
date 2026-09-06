"""Cold-start launch splash — logo · name · version · status + % bar.

Vegas / Adobe–style card. Top-left: avatar + @handle → profile.
Top-right: GitHub mark → repo. Progress strip eases like the render bar.

Drive via ``show_launch_splash`` / ``update_launch_splash`` /
``hold_launch_splash_opening`` / ``finish_launch_splash``.
Skip with env ``STEEMPEG_NO_SPLASH=1``.
"""
from __future__ import annotations

import logging
import os
import time
import webbrowser

from PySide6.QtCore import Qt, QTimer, QRectF, QUrl
from PySide6.QtGui import (
    QColor,
    QDesktopServices,
    QFont,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from steempeg.ui import design_tokens as tok
from steempeg.version import APP_VERSION_STR

_BG = "#2a2a2a"
_BG_EDGE = QColor("#1a1a1a")
_BG_EDGE_PURPLE = QColor("#2a2240")
_BG_MID = QColor(_BG)
_BG_BOTTOM = QColor("#222222")
_TRACK = QColor("#3a3a3a")
_FILL_A = QColor("#6b5a8e")
_FILL_B = QColor("#b29ae7")
_SHIMMER = QColor(255, 255, 255, 72)
_LERP = 0.28
# Cap how far the visible % can jump per frame → reads 10,11,12… not 10→30.
_MAX_STEP_PER_TICK = 1.35
_CREEP_PER_TICK = 0.12
_SPINNER_SIZE = 12
_SPINNER_STEP = 12
# Preparing: a touch quicker than the bar phase — not a blur.
_SPINNER_STEP_FAST = 16
_SPINNER_INTERVAL_MS = 33
_SPINNER_INTERVAL_FAST_MS = 28
_CREDIT_AVATAR = 28
_CREDIT_GH = 40

_REPO_URL = "https://github.com/applejuicy23/steempeg"
_PROFILE_URL = "https://github.com/applejuicy23"
_HANDLE = "@applejuicy23"
_GH_MARK = "github.jpg"
_AVATAR = "applejuicy23.png"

_splash: LaunchSplash | None = None
_sim_timer: QTimer | None = None
_sim_steps: list[tuple[float, str]] = []
_sim_index: int = 0
_sim_hold: bool = False

_SIM_SCRIPT: tuple[tuple[float, str], ...] = (
    (0, "Starting…"),
    (4, "Starting Steempeg…"),
    (8, "Building window…"),
    (22, "Window ready…"),
    (32, "Loading preferences…"),
    (42, "Applying theme…"),
    (50, "Building chrome…"),
    (54, "Preparing dashboard…"),
    (58, "Preparing player…"),
    (64, "Building player chrome…"),
    (70, "Wiring player controls…"),
    (74, "Starting video engine…"),
    (78, "Detecting hardware…"),
    (88, "Loading library roots…"),
    (100, "Preparing workspace…"),
)


def _splash_disabled() -> bool:
    return os.environ.get("STEEMPEG_NO_SPLASH", "0").strip() in ("1", "true", "yes")


def _open_url(url: str) -> None:
    try:
        if QDesktopServices.openUrl(QUrl(url)):
            return
    except Exception:
        logging.debug("QDesktopServices open failed for %s", url, exc_info=True)
    try:
        webbrowser.open(url)
    except Exception:
        logging.debug("webbrowser open failed for %s", url, exc_info=True)


def _lerp_color(a: QColor, b: QColor, t: float) -> QColor:
    t = max(0.0, min(1.0, float(t)))
    return QColor(
        int(round(a.red() + (b.red() - a.red()) * t)),
        int(round(a.green() + (b.green() - a.green()) * t)),
        int(round(a.blue() + (b.blue() - a.blue()) * t)),
    )


def _soft_ceiling_for(percent: float) -> float:
    pct = max(0.0, min(100.0, float(percent)))
    for step, _status in _SIM_SCRIPT:
        if step > pct + 0.05:
            return float(step)
    return 100.0


class _SplashProgressBar(QWidget):
    """Eased fill that ticks up in small steps (smooth %), shimmer while busy."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(10)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._display = 0.0
        self._target = 0.0
        self._soft_ceiling = 8.0
        self._shimmer = 0.0
        self._busy = True
        self._tick = QTimer(self)
        self._tick.setInterval(16)
        self._tick.timeout.connect(self._on_tick)
        self._tick.start()

    def set_progress(self, value: float, *, soft_ceiling: float | None = None) -> None:
        self._target = max(0.0, min(100.0, float(value)))
        if soft_ceiling is None:
            self._soft_ceiling = _soft_ceiling_for(self._target)
        else:
            self._soft_ceiling = max(self._target, min(100.0, float(soft_ceiling)))
        self._busy = self._target < 99.5
        if not self._tick.isActive():
            self._tick.start()
        self.update()

    def display_value(self) -> float:
        return float(self._display)

    def snap_to(self, value: float, *, busy: bool = False) -> None:
        """Hard set visible % (Preparing workspace must land on 100, not 80–90)."""
        v = max(0.0, min(100.0, float(value)))
        self._display = v
        self._target = v
        self._soft_ceiling = v
        self._busy = bool(busy)
        if busy and not self._tick.isActive():
            self._tick.start()
        elif not busy:
            self._tick.stop()
        self.update()

    def set_finished(self, *, hold_alive: bool = False) -> None:
        # Always land on a true 100% for the final stage.
        self.snap_to(100.0, busy=bool(hold_alive))

    def set_display(self, value: float) -> None:
        self._display = max(0.0, min(100.0, float(value)))
        self.update()

    def tick_once(self, *, allow_creep: bool = True) -> bool:
        """One animation step. Returns True if display still lags the hard target."""
        if (
            allow_creep
            and self._busy
            and self._target < self._soft_ceiling - 0.05
            and self._display >= self._target - 0.4
        ):
            self._target = min(self._soft_ceiling, self._target + _CREEP_PER_TICK)

        delta = self._target - self._display
        if abs(delta) >= 1.0:
            # Whole-percent steps → label reads 12, 13, 14… not 12 → 28.
            self._display += 1.0 if delta > 0 else -1.0
        elif abs(delta) > 0.05:
            self._display = self._target
        elif self._display != self._target:
            self._display = self._target

        if self._busy or abs(self._display - 100.0) > 0.2:
            self._shimmer = (self._shimmer + 0.014) % 1.0

        self.update()
        return abs(self._display - self._target) > 0.2

    def _on_tick(self) -> None:
        if not self.tick_once() and not self._busy:
            self._tick.stop()

    def paintEvent(self, event) -> None:  # noqa: N802
        del event
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setPen(Qt.PenStyle.NoPen)
        r = QRectF(self.rect())
        radius = r.height() / 2.0
        p.setBrush(_TRACK)
        p.drawRoundedRect(r, radius, radius)
        frac = max(0.0, min(1.0, self._display / 100.0))
        if frac <= 0.001:
            return
        fill_w = max(r.height(), r.width() * frac)
        fr = QRectF(r.left(), r.top(), fill_w, r.height())
        grad = QLinearGradient(fr.topLeft(), fr.topRight())
        grad.setColorAt(0.0, _FILL_A)
        grad.setColorAt(1.0, _FILL_B)
        p.setBrush(grad)
        p.drawRoundedRect(fr, radius, radius)
        if self._busy or frac < 0.995:
            band = max(18.0, fill_w * 0.28)
            x = -band + (fill_w + band) * self._shimmer
            p.save()
            clip = QPainterPath()
            clip.addRoundedRect(fr, radius, radius)
            p.setClipPath(clip)
            shimmer = QLinearGradient(x, 0.0, x + band, 0.0)
            shimmer.setColorAt(0.0, QColor(255, 255, 255, 0))
            shimmer.setColorAt(0.45, _SHIMMER)
            shimmer.setColorAt(0.55, _SHIMMER)
            shimmer.setColorAt(1.0, QColor(255, 255, 255, 0))
            p.setBrush(shimmer)
            p.drawRoundedRect(fr, radius, radius)
            p.restore()


class _SplashBusySpinner(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(_SPINNER_SIZE, _SPINNER_SIZE)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._angle = 0
        self._step = _SPINNER_STEP
        self._tick = QTimer(self)
        self._tick.setInterval(_SPINNER_INTERVAL_MS)
        self._tick.timeout.connect(self._on_tick)
        self._tick.start()

    def set_fast(self, fast: bool) -> None:
        """High-speed spin during «Preparing workspace…»."""
        if fast:
            self._step = _SPINNER_STEP_FAST
            self._tick.setInterval(_SPINNER_INTERVAL_FAST_MS)
        else:
            self._step = _SPINNER_STEP
            self._tick.setInterval(_SPINNER_INTERVAL_MS)
        if not self._tick.isActive():
            self._tick.start()

    def advance(self) -> None:
        """Manual frame — timers do not fire during blocking cold-start work."""
        self._angle = (self._angle + self._step) % 360
        self.update()

    def _on_tick(self) -> None:
        self._angle = (self._angle + self._step) % 360
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        del event
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        r = QRectF(self.rect()).adjusted(1.5, 1.5, -1.5, -1.5)
        pen = QPen(_FILL_B)
        pen.setWidthF(1.75)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.drawArc(r, int((-self._angle) * 16), int(270 * 16))


class _LinkLabel(QLabel):
    """Clickable label / icon (best-effort on translucent splash)."""

    def __init__(self, url: str, parent=None):
        super().__init__(parent)
        self._url = url
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            _open_url(self._url)
            event.accept()
            return
        super().mouseReleaseEvent(event)


def _round_avatar(size: int) -> QPixmap:
    try:
        from steempeg.infra.paths import get_resource_path
        from steempeg.ui.icon_utils import square_fit_pixmap

        raw = QPixmap(get_resource_path(_AVATAR))
        if raw.isNull():
            return QPixmap()
        square = square_fit_pixmap(raw, size, dpr=1.0)
        out = QPixmap(size, size)
        out.fill(Qt.GlobalColor.transparent)
        p = QPainter(out)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        path = QPainterPath()
        path.addEllipse(0.0, 0.0, float(size), float(size))
        p.setClipPath(path)
        p.drawPixmap(0, 0, square)
        p.end()
        return out
    except Exception:
        logging.debug("Splash avatar failed", exc_info=True)
        return QPixmap()


class _SplashAuthor(QWidget):
    """Top-left: avatar + @handle."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background: transparent; border: none;")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)

        self._avatar = _LinkLabel(_PROFILE_URL)
        self._avatar.setFixedSize(_CREDIT_AVATAR, _CREDIT_AVATAR)
        self._avatar.setToolTip(f"{_HANDLE} on GitHub")
        pix = _round_avatar(_CREDIT_AVATAR)
        if not pix.isNull():
            self._avatar.setPixmap(pix)
        lay.addWidget(self._avatar)

        self._handle = _LinkLabel(_PROFILE_URL)
        self._handle.setText(_HANDLE)
        self._handle.setToolTip(f"Open {_HANDLE}")
        f = QFont()
        f.setFamilies(["Segoe UI", "Cascadia UI", "Segoe UI Variable", tok.FONT_APP])
        f.setPointSize(10)
        f.setWeight(QFont.Weight.Bold)
        self._handle.setFont(f)
        self._handle.setStyleSheet(
            f"color: {tok.ACCENT_PRIMARY}; background: transparent; border: none;"
        )
        lay.addWidget(self._handle)


class _SplashRepoMark(QWidget):
    """Top-right: GitHub mark (larger than avatar)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background: transparent; border: none;")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)

        self._gh = _LinkLabel(_REPO_URL)
        self._gh.setFixedSize(_CREDIT_GH, _CREDIT_GH)
        self._gh.setToolTip("Open steempeg on GitHub")
        try:
            from steempeg.ui.icon_assets import load_pixmap

            pix = load_pixmap(_GH_MARK, _CREDIT_GH)
            if not pix.isNull():
                self._gh.setPixmap(pix)
        except Exception:
            logging.debug("Splash GitHub mark failed", exc_info=True)
        lay.addWidget(self._gh, 0, Qt.AlignmentFlag.AlignRight)


class LaunchSplash(QWidget):
    """Frameless centered splash card."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("SteempegLaunchSplash")
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Window
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setFixedSize(520, 300)
        self._wash_t = 0.0

        root = QVBoxLayout(self)
        root.setContentsMargins(36, 36, 36, 28)
        root.setSpacing(0)
        root.addStretch(2)

        logo_row = QHBoxLayout()
        logo_row.addStretch(1)
        self._logo = QLabel()
        self._logo.setFixedSize(72, 72)
        self._logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        try:
            from steempeg.ui.icon_utils import apply_square_icon, app_logo_pixmap

            apply_square_icon(self._logo, app_logo_pixmap(72, dpr=1.0), 72)
        except Exception:
            logging.debug("Launch splash logo failed", exc_info=True)
        logo_row.addWidget(self._logo)
        logo_row.addStretch(1)
        root.addLayout(logo_row)
        root.addSpacing(14)

        self._title = QLabel("Steempeg")
        self._title.setObjectName("LaunchSplashTitle")
        self._title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_font = QFont()
        title_font.setFamilies(
            ["Cascadia UI", "Segoe UI Variable", "Segoe UI", tok.FONT_APP]
        )
        title_font.setPointSize(22)
        title_font.setWeight(QFont.Weight.DemiBold)
        self._title.setFont(title_font)
        root.addWidget(self._title)

        self._version = QLabel(f"v{APP_VERSION_STR}")
        self._version.setObjectName("LaunchSplashVersion")
        self._version.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ver_font = QFont(title_font)
        ver_font.setPointSize(11)
        ver_font.setWeight(QFont.Weight.Normal)
        self._version.setFont(ver_font)
        root.addWidget(self._version)
        root.addStretch(3)

        meta = QHBoxLayout()
        meta.setContentsMargins(0, 0, 0, 6)
        meta.setSpacing(8)
        self._spinner = _SplashBusySpinner()
        self._status = QLabel("Starting…")
        self._status.setObjectName("LaunchSplashStatus")
        status_font = QFont()
        status_font.setFamilies([tok.FONT_APP, "Segoe UI"])
        status_font.setPointSize(10)
        self._status.setFont(status_font)
        self._status.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        self._percent = QLabel("0%")
        self._percent.setObjectName("LaunchSplashPercent")
        self._percent.setFont(status_font)
        self._percent.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        meta.addWidget(self._spinner, 0, Qt.AlignmentFlag.AlignVCenter)
        meta.addWidget(self._status, 1)
        meta.addWidget(self._percent, 0)
        root.addLayout(meta)

        self._bar = _SplashProgressBar()
        root.addWidget(self._bar)

        self.setStyleSheet(
            f"""
            QWidget#SteempegLaunchSplash {{
                background: transparent;
                border: none;
            }}
            QLabel#LaunchSplashTitle {{
                color: {tok.TEXT_TITLE};
                background: transparent;
                border: none;
            }}
            QLabel#LaunchSplashVersion {{
                color: {tok.TEXT_MUTED};
                background: transparent;
                border: none;
            }}
            QLabel#LaunchSplashStatus {{
                color: {tok.TEXT_MUTED};
                background: transparent;
                border: none;
            }}
            QLabel#LaunchSplashPercent {{
                color: {tok.ACCENT_PRIMARY};
                background: transparent;
                border: none;
                font-weight: bold;
            }}
            """
        )

        self._author = _SplashAuthor(self)
        self._repo = _SplashRepoMark(self)
        self._place_credits()

        self._pct_sync = QTimer(self)
        self._pct_sync.setInterval(16)
        self._pct_sync.timeout.connect(self._sync_percent_label)
        self._pct_sync.start()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._place_credits()

    def _place_credits(self) -> None:
        m = 14
        self._author.adjustSize()
        self._repo.adjustSize()
        self._author.move(m, m)
        self._repo.move(self.width() - self._repo.width() - m, m)
        self._author.raise_()
        self._repo.raise_()

    def paintEvent(self, event) -> None:  # noqa: N802
        del event
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        r = QRectF(self.rect())
        path = QPainterPath()
        path.addRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), 14, 14)
        top = _lerp_color(_BG_EDGE, _BG_EDGE_PURPLE, self._wash_t)
        mid = _lerp_color(_BG_MID, QColor("#2c2836"), self._wash_t * 0.55)
        grad = QLinearGradient(r.topLeft(), r.bottomLeft())
        grad.setColorAt(0.0, top)
        grad.setColorAt(0.4, mid)
        grad.setColorAt(1.0, _BG_BOTTOM)
        p.fillPath(path, grad)
        p.setPen(QColor("#3a3a3a"))
        p.drawPath(path)

    def set_progress(self, percent: float, status: str | None = None) -> None:
        if status is not None:
            self._status.setText(str(status).strip() or self._status.text())
        pct = max(0.0, min(100.0, float(percent)))
        self._bar.set_progress(pct, soft_ceiling=_soft_ceiling_for(pct))
        if not self._pct_sync.isActive():
            self._pct_sync.start()
        self._sync_percent_label()

    def mark_opening(self, status: str, *, hold_alive: bool = False) -> None:
        if status:
            self._status.setText(str(status).strip() or self._status.text())
        # Final stage always shows a true 100% — never leave the bar at 80–90.
        self._bar.snap_to(100.0, busy=bool(hold_alive))
        self._spinner.set_fast(bool(hold_alive))
        if not self._pct_sync.isActive():
            self._pct_sync.start()
        self._sync_percent_label()

    def _sync_percent_label(self) -> None:
        self._wash_t = self._bar.display_value() / 100.0
        self.update()
        self._percent.setText(f"{int(round(self._bar.display_value()))}%")

    def center_on_screen(self) -> None:
        app = QApplication.instance()
        screen = app.primaryScreen() if app is not None else None
        if screen is None:
            return
        geo = screen.availableGeometry()
        self.move(
            geo.center().x() - self.width() // 2,
            geo.center().y() - self.height() // 2,
        )


def show_launch_splash(*, force: bool = False) -> LaunchSplash | None:
    global _splash
    if _splash_disabled() and not force:
        return None
    if _splash is not None:
        try:
            if _splash.isVisible():
                return _splash
        except RuntimeError:
            _splash = None
    splash = LaunchSplash()
    splash.center_on_screen()
    splash.set_progress(0, "Starting…")
    splash.show()
    splash.raise_()
    _pump()
    _splash = splash
    return splash


def update_launch_splash(
    percent: float, status: str | None = None, *, force: bool = False
) -> None:
    global _splash
    if (_splash_disabled() and not force) or _splash is None:
        return
    try:
        _splash.set_progress(percent, status)
    except RuntimeError:
        _splash = None
        return
    _pump_progress()


def launch_splash_begin_preparing(
    *, status: str = "Preparing workspace…", force: bool = False
) -> None:
    """Last cold-start stage: fast spinner NOW + 100% (not after a freeze)."""
    global _splash
    if (_splash_disabled() and not force) or _splash is None:
        return
    try:
        _splash._status.setText(str(status).strip() or "Preparing workspace…")
        _splash._spinner.set_fast(True)
        _splash._bar.snap_to(100.0, busy=True)
        _splash._sync_percent_label()
        _splash.raise_()
        # Kick the circle immediately — QTimer will not run during blocking init.
        _pace_spinner_frames(4)
    except RuntimeError:
        _splash = None


def launch_splash_keepalive(*, force: bool = False) -> None:
    """Keep the fast spinner alive during long blocking work after Preparing starts."""
    global _splash
    if (_splash_disabled() and not force) or _splash is None:
        return
    try:
        _pace_spinner_frames(2)
    except RuntimeError:
        _splash = None


def launch_splash_is_holding() -> bool:
    global _splash
    if _splash is None:
        return False
    try:
        return bool(_splash.isVisible())
    except RuntimeError:
        _splash = None
        return False


def hold_launch_splash_opening(
    *, status: str = "Preparing workspace…", force: bool = False, hold_s: float = 1.0
) -> None:
    """100% + fast spin for ``hold_s``, then close — spinner never waits on QTimer."""
    global _splash
    if (_splash_disabled() and not force) or _splash is None:
        return
    try:
        _splash.mark_opening(status, hold_alive=True)
        _splash._spinner.set_fast(True)
        _splash.raise_()
        deadline = time.monotonic() + max(0.35, float(hold_s))
        frame_s = max(0.016, _SPINNER_INTERVAL_FAST_MS / 1000.0)
        while time.monotonic() < deadline:
            _splash._spinner.advance()
            _splash._bar.tick_once(allow_creep=False)
            _splash._sync_percent_label()
            _pump()
            time.sleep(frame_s)
        finish_launch_splash(status="Ready", force=force)
    except RuntimeError:
        _splash = None


def finish_launch_splash(*, status: str = "Opening…", force: bool = False) -> None:
    global _splash
    del force
    if _splash is None:
        return
    try:
        if status:
            try:
                _splash.mark_opening(status, hold_alive=False)
            except RuntimeError:
                pass
        _splash.close()
    except RuntimeError:
        pass
    _splash = None


def cancel_launch_splash_simulation() -> None:
    global _sim_timer, _sim_steps, _sim_index
    if _sim_timer is not None:
        try:
            _sim_timer.stop()
            _sim_timer.deleteLater()
        except RuntimeError:
            pass
        _sim_timer = None
    _sim_steps = []
    _sim_index = 0


def simulate_launch_splash(*, hold_open: bool = False, step_ms: int = 380) -> None:
    """DEV: replay cold-start script. Esc closes (clicks do not kill the bar)."""
    global _sim_timer, _sim_steps, _sim_index, _sim_hold, _splash

    cancel_launch_splash_simulation()
    _sim_hold = bool(hold_open)

    if _splash is not None:
        try:
            _splash.close()
        except RuntimeError:
            pass
        _splash = None

    splash = show_launch_splash(force=True)
    if splash is None:
        return

    splash.setToolTip("Esc to close (DEV preview)")
    splash.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
    splash.setFocus(Qt.FocusReason.OtherFocusReason)

    def _on_key(event) -> None:
        from PySide6.QtGui import QKeyEvent

        if isinstance(event, QKeyEvent) and event.key() == Qt.Key.Key_Escape:
            cancel_launch_splash_simulation()
            finish_launch_splash(status="Closed", force=True)
            event.accept()
            return
        QWidget.keyPressEvent(splash, event)

    splash.keyPressEvent = _on_key  # type: ignore[method-assign]

    _sim_steps = list(_SIM_SCRIPT)
    _sim_index = 0

    def _advance() -> None:
        global _sim_index, _sim_timer
        if _sim_index >= len(_sim_steps):
            if _sim_timer is not None:
                _sim_timer.stop()
            if not _sim_hold:
                finish_launch_splash(status="Opening workspace…", force=True)
            return
        pct, status = _sim_steps[_sim_index]
        _sim_index += 1
        update_launch_splash(pct, status, force=True)
        if _sim_index >= len(_sim_steps) and _sim_hold:
            if _sim_timer is not None:
                _sim_timer.stop()
            update_launch_splash(100, "Opening workspace… (DEV hold)", force=True)

    _sim_timer = QTimer()
    _sim_timer.setInterval(max(80, int(step_ms)))
    _sim_timer.timeout.connect(_advance)
    _advance()
    _sim_timer.start()


def _pace_spinner_frames(n: int) -> None:
    """Advance the spinner at the fast interval (not as fast as processEvents)."""
    global _splash
    if _splash is None or n <= 0:
        return
    frame_s = max(0.016, _SPINNER_INTERVAL_FAST_MS / 1000.0)
    for _ in range(n):
        _splash._spinner.advance()
        _pump()
        time.sleep(frame_s)


def _pump() -> None:
    app = QApplication.instance()
    if app is None:
        return
    try:
        from PySide6.QtCore import QEventLoop

        app.processEvents(QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents, 16)
    except Exception:
        app.processEvents()


def _pump_progress(*, max_frames: int | None = None) -> None:
    """Advance visible % in 1-point steps; keep spinner turning during the walk."""
    global _splash
    app = QApplication.instance()
    if app is None or _splash is None:
        return
    try:
        from PySide6.QtCore import QEventLoop

        gap = abs(_splash._bar._target - _splash._bar.display_value())
        frames = max_frames
        if frames is None:
            # One frame per percent (capped) so 30→50 paints 31…50.
            frames = min(50, max(1, int(round(gap)) + 1))
        for _ in range(frames):
            still = _splash._bar.tick_once(allow_creep=False)
            _splash._spinner.advance()
            _splash._sync_percent_label()
            app.processEvents(
                QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents, 16
            )
            if not still:
                break
    except RuntimeError:
        _splash = None
    except Exception:
        _pump()
