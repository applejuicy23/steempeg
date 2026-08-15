"""Shared queue context-menu actions for user export presets."""
from __future__ import annotations

from typing import Any

from PySide6.QtWidgets import QMenu


def resolve_steempeg_app(seed: Any) -> Any | None:
    """Walk parents for SteempegApp (methods live on the app, not the QDialog)."""
    w = seed
    seen: set[int] = set()
    while w is not None and id(w) not in seen:
        seen.add(id(w))
        if hasattr(w, "apply_export_preset_to_queue_job"):
            return w
        app = getattr(w, "_app", None)
        if app is not None and hasattr(app, "apply_export_preset_to_queue_job"):
            return app
        parent = getattr(w, "parentWidget", None)
        w = parent() if callable(parent) else None
    return None


def add_export_preset_menu_actions(menu: QMenu, seed: Any, job_id: str) -> None:
    """Insert Apply preset / Apply panel settings under Select in editor."""
    from steempeg.render.export_presets import (
        format_preset_summary,
        get_preset_settings,
        list_preset_names,
        load_favourite_names,
    )

    app = resolve_steempeg_app(seed)
    names: list[str] = []
    fav_set: set[str] = set()
    if app is not None and hasattr(app, "load_user_settings"):
        try:
            names = list_preset_names(app.load_user_settings)
            fav_set = set(load_favourite_names(app.load_user_settings))
        except Exception:
            names = []
            fav_set = set()

    apply_menu = menu.addMenu("📦  Apply preset")
    if app is None:
        empty = apply_menu.addAction("App not ready")
        empty.setEnabled(False)
    elif not names:
        empty = apply_menu.addAction("No saved presets")
        empty.setEnabled(False)
    else:
        for name in names:
            label = f"★ {name}" if name in fav_set else name
            act = apply_menu.addAction(label)
            try:
                tip = format_preset_summary(get_preset_settings(name, app.load_user_settings))
                if tip:
                    act.setToolTip(tip)
            except Exception:
                pass
            act.triggered.connect(
                lambda checked=False, n=name, jid=job_id, a=app: a.apply_export_preset_to_queue_job(
                    jid, n
                )
            )

    act_panel = menu.addAction("📥  Apply panel settings to job")
    act_panel.setEnabled(app is not None)
    if app is not None:
        act_panel.triggered.connect(
            lambda checked=False, jid=job_id, a=app: a.apply_panel_settings_to_queue_job(jid)
        )
