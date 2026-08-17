"""PySide signal helpers."""
from __future__ import annotations

import warnings


def safe_disconnect(signal) -> None:
    """Disconnect all slots without the libpyside 'Failed to disconnect (None)' warning."""
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message=r".*Failed to disconnect.*",
            category=RuntimeWarning,
        )
        try:
            signal.disconnect()
        except (RuntimeError, TypeError, SystemError):
            pass
