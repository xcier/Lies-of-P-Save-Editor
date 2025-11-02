from __future__ import annotations

import os, traceback
from typing import Optional, Dict, Any

from PyQt6.QtCore import QObject, QThread, pyqtSignal

from app.core.file_manager import FileManager

class _SaveWorker(QObject):
    finished = pyqtSignal(str)
    error    = pyqtSignal(str)
    progress = pyqtSignal(int, str)

    def __init__(self, data: Dict[str, Any], target_path: str, src_path: str, mode: str):
        super().__init__(None)  # no parent -> safe to moveToThread
        self._data   = data
        self._target = target_path
        self._src    = src_path
        self._mode   = (mode or "auto").lower()

    def run(self):
        try:
            self.progress.emit(10, "Preparing JSON")
            if self._mode in ("raw","fixed","auto"):
                os.environ["UESAVE_SAVE_MODE"] = self._mode

            def ping(p: int, m: str):
                self.progress.emit(p, m)

            self.progress.emit(40, "Starting uesave")
            FileManager.save_sav(
                self._target,
                self._data,
                self._src,
                on_progress=ping,
            )
            self.progress.emit(100, "Done")
            self.finished.emit(self._target)

        except Exception:
            self.error.emit(traceback.format_exc())

class SaveSavAsync(QObject):
    finished = pyqtSignal(str)
    error    = pyqtSignal(str)
    progress = pyqtSignal(int, str)
    canceled = pyqtSignal()

    def __init__(self, *, data: Dict[str, Any], target_path: str, src_path: str = "",
                 mode: str = "auto", parent: Optional[QObject] = None):
        super().__init__(parent)
        self._data   = data
        self._target = target_path
        self._src    = src_path
        self._mode   = mode
        self._thread: Optional[QThread] = None
        self._worker: Optional[_SaveWorker] = None
        self._cancel_requested = False

    def start(self):
        if self._cancel_requested:
            self.canceled.emit()
            return
        if self._thread is not None:
            return

        self._thread = QThread()
        self._worker = _SaveWorker(self._data, self._target, self._src, self._mode)
        self._worker.moveToThread(self._thread)

        self._thread.started.connect(self._worker.run)
        self._worker.finished.connect(self._thread.quit)
        self._worker.error.connect(self._thread.quit)

        self._worker.finished.connect(self.finished)
        self._worker.error.connect(self.error)
        self._worker.progress.connect(self.progress)

        self._thread.finished.connect(self._cleanup)
        self._thread.start()

    def cancel(self):
        self._cancel_requested = True
        self.canceled.emit()

    def _cleanup(self):
        try:
            if self._worker is not None:
                self._worker.deleteLater()
        finally:
            self._worker = None
            if self._thread is not None:
                self._thread.deleteLater()
                self._thread = None