from __future__ import annotations
import os, sys
from pathlib import Path
from typing import Iterable, Callable

from PyQt6.QtCore import QThread, Qt
from PyQt6.QtWidgets import (
    QApplication, QMessageBox, QFileDialog, QMainWindow, QMenu, QAction
)

# ---- Optional lightweight logger (safe fallback) ----
def init_basic_logger():
    import logging, logging.handlers, os
    logs_dir = Path("logs"); logs_dir.mkdir(exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(
        logs_dir / "app.log", maxBytes=262_144, backupCount=3, encoding="utf-8"
    )
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    handler.setFormatter(fmt)
    root = logging.getLogger()
    if not root.handlers:
        root.setLevel(logging.INFO)
        root.addHandler(handler)
    return root

# ----------------- Mixins -----------------

class BusyMixin:
    """Disable a set of actions while work is running; show wait cursor."""
    def _init_busy(self, actions: Iterable[QAction] = ()):
        self._busy = False
        self._all_actions = list(actions)

    def _register_actions(self, actions: Iterable[QAction]):
        self._all_actions.extend(actions)

    def _set_busy(self, busy: bool):
        if getattr(self, "_busy", False) == busy:
            return
        self._busy = busy
        for act in getattr(self, "_all_actions", []):
            try: act.setEnabled(not busy)
            except Exception: pass
        try:
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor if busy else Qt.CursorShape.ArrowCursor)
        except Exception:
            pass


class WorkerRunnerMixin:
    """Start a worker in a thread with safe cleanup; returns (thread, worker)."""
    def _run_worker(self, worker_obj, finished_cb: Callable, error_cb: Callable):
        t = QThread(self)
        w = worker_obj
        w.moveToThread(t)
        t.started.connect(w.run)
        w.finished.connect(finished_cb)
        w.error.connect(error_cb)
        w.finished.connect(t.quit); w.error.connect(t.quit)
        t.finished.connect(w.deleteLater); t.finished.connect(t.deleteLater)
        t.start()
        return t, w


class RecentFilesMixin:
    """Persist a small list of recent files in Settings."""
    _recent_key = "recent_files"
    _last_dir_key = "last_dir"

    def _init_recent_menu(self, menubar, settings, max_items: int = 5):
        self._recent_max = max(1, int(max_items))
        self._settings = settings
        self._recent_menu: QMenu = menubar.addMenu("&Recent")
        self._refresh_recent_menu()

    def _push_recent(self, path: str):
        rec = list(self._settings.get(self._recent_key, []) or [])
        if path in rec: rec.remove(path)
        rec.insert(0, path)
        rec = rec[: self._recent_max]
        self._settings.set(self._recent_key, rec)
        if hasattr(self._settings, "save"): self._settings.save()
        self._settings.set(self._last_dir_key, os.path.dirname(path))
        if hasattr(self._settings, "save"): self._settings.save()
        self._refresh_recent_menu()

    def _refresh_recent_menu(self):
        self._recent_menu.clear()
        rec = self._settings.get(self._recent_key, []) or []
        if not rec:
            a = QAction("(Empty)", self); a.setEnabled(False)
            self._recent_menu.addAction(a); return
        for p in rec:
            a = QAction(p, self)
            a.triggered.connect(lambda _, x=p: self._open_path(x))
            self._recent_menu.addAction(a)

    def _choose_open_path(self, parent: QMainWindow):
        start = self._settings.get(self._last_dir_key, "") or ""
        path, _ = QFileDialog.getOpenFileName(parent, "Open Save File", start, "Save Files (*.sav *.json)")
        if path:
            self._push_recent(path)
        return path

    def _choose_save_path(self, parent: QMainWindow, title: str, suggested: str, filt: str):
        start_dir = self._settings.get(self._last_dir_key, "") or ""
        start = os.path.join(start_dir, suggested) if start_dir else suggested
        path, _ = QFileDialog.getSaveFileName(parent, title, start, filt)
        if path:
            self._settings.set(self._last_dir_key, os.path.dirname(path))
            if hasattr(self._settings, "save"): self._settings.save()
        return path


class GeometryPersistMixin:
    """Save/restore window geometry/state via Settings."""
    def _restore_geometry(self, settings):
        try:
            geo = settings.get("win_geo", None)
            if geo: self.restoreGeometry(geo)
            state = settings.get("win_state", None)
            if state: self.restoreState(state)
        except Exception:
            pass

    def _save_geometry(self, settings):
        try:
            settings.set("win_geo", self.saveGeometry())
            settings.set("win_state", self.saveState())
            if hasattr(settings, "save"): settings.save()
        except Exception:
            pass


class DragDropOpenMixin:
    """Enable drag & drop of .sav/.json onto the main window."""
    def enable_drag_drop(self):
        self.setAcceptDrops(True)

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            for u in e.mimeData().urls():
                if u.toLocalFile().lower().endswith((".sav", ".json")):
                    e.acceptProposedAction(); return
        e.ignore()

    def dropEvent(self, e):
        for u in e.mimeData().urls():
            p = u.toLocalFile()
            if p.lower().endswith((".sav", ".json")):
                self._open_path(p); break
