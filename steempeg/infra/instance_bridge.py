"""Local socket between Steempeg instances.

The primary instance listens; a second launch (Start menu, desktop shortcut,
toast click) connects and asks it to show its window instead of starting a
second copy. Needed once the main window can hide in the tray, because a
hidden window is invisible to the Win32 ``raise_steempeg_window`` path.
"""
from __future__ import annotations

import base64
import getpass
import logging
import re

from PySide6.QtCore import QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket

_log = logging.getLogger(__name__)

SHOW_COMMAND = b"show"
OPEN_CLIP_PREFIX = b"open-clip "
_CONNECT_TIMEOUT_MS = 800


def build_server_name() -> str:
    """Builds a per-user socket name so two Windows accounts never talk to each other."""
    try:
        user = getpass.getuser()
    except Exception:
        user = "user"
    safe_user = re.sub(r"[^A-Za-z0-9_.-]", "_", user) or "user"
    return f"steempeg-instance-{safe_user}"


def _send_command(payload: bytes, timeout_ms: int = _CONNECT_TIMEOUT_MS) -> bool:
    """Writes one command to the running instance. False when nobody is listening."""
    socket = QLocalSocket()
    socket.connectToServer(build_server_name())
    if not socket.waitForConnected(timeout_ms):
        return False
    socket.write(payload)
    socket.flush()
    socket.waitForBytesWritten(timeout_ms)
    socket.disconnectFromServer()
    return True


def ask_running_instance_to_show(timeout_ms: int = _CONNECT_TIMEOUT_MS) -> bool:
    """Sends «show» to the running Steempeg; returns False when nobody is listening."""
    if not _send_command(SHOW_COMMAND + b"\n", timeout_ms):
        return False
    _log.info("Asked the running Steempeg instance to show its window")
    return True


def ask_running_instance_to_open_clip(
    clip_path: str, timeout_ms: int = _CONNECT_TIMEOUT_MS
) -> bool:
    """Asks the running Steempeg to open ``clip_path``. False when nobody is listening."""
    token = base64.urlsafe_b64encode(clip_path.encode("utf-8"))
    if not _send_command(OPEN_CLIP_PREFIX + token + b"\n", timeout_ms):
        return False
    _log.info("Asked the running Steempeg instance to open a clip")
    return True


class InstanceBridge(QObject):
    """Listens for other launches and emits ``show_requested`` when one asks for the window."""

    show_requested = Signal()
    open_clip_requested = Signal(str)

    def __init__(self, parent: QObject | None = None):
        """Creates the server; nothing is accepted until ``listen()``."""
        super().__init__(parent)
        self._server = QLocalServer(self)
        self._server.newConnection.connect(self._accept_connections)
        # Set when a command arrives before the main window is connected.
        self.show_was_requested = False
        self.pending_open_clip = ""

    def listen(self) -> bool:
        """Starts listening under the per-user name (clears a stale socket left by a crash)."""
        name = build_server_name()
        QLocalServer.removeServer(name)
        if not self._server.listen(name):
            _log.warning("Instance bridge: listen failed: %s", self._server.errorString())
            return False
        _log.info("Instance bridge: listening as %s", name)
        return True

    def _accept_connections(self) -> None:
        """Reads every pending connection's command."""
        while self._server.hasPendingConnections():
            socket = self._server.nextPendingConnection()
            if socket is None:
                break
            socket.readyRead.connect(lambda s=socket: self._read_command(s))
            socket.disconnected.connect(socket.deleteLater)
            if socket.bytesAvailable():
                self._read_command(socket)

    def _read_command(self, socket: QLocalSocket) -> None:
        """Emits the signal for «show» or «open-clip» from the other launch."""
        data = bytes(socket.readAll())
        opened = False
        for line in data.splitlines():
            if not line.startswith(OPEN_CLIP_PREFIX):
                continue
            path = _decode_open_clip(line[len(OPEN_CLIP_PREFIX) :])
            if not path:
                continue
            self.pending_open_clip = path
            self.open_clip_requested.emit(path)
            opened = True
        if opened:
            return
        if SHOW_COMMAND in data:
            self.show_was_requested = True
            self.show_requested.emit()


def _decode_open_clip(payload: bytes) -> str:
    """Turns the base64 clip token back into a folder path."""
    try:
        return base64.urlsafe_b64decode(payload).decode("utf-8").strip()
    except Exception:
        _log.debug("Instance bridge: bad open-clip payload", exc_info=True)
        return ""
