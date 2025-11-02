from __future__ import annotations

import traceback
from typing import Optional, Callable

from PyQt6.QtCore import QObject, pyqtSignal

from app.core.file_manager import FileManager

class LoadWorker(QObject):
    finished = pyqtSignal(dict, str)  # (data, path)
    error    = pyqtSignal(str)
    progress = pyqtSignal(int, str)

    def __init__(self, path: str, cancel_cb: Optional[Callable[[], bool]] = None):
        super().__init__(None)
        self._path = path
        self._cancel_cb = cancel_cb

    def run(self):
        try:
            self.progress.emit(20, "Reading file")
            data = FileManager.load_file(self._path)
            self.progress.emit(95, "Loaded")
            self.finished.emit(data, self._path)
        except Exception:
            self.error.emit(f"Failed to load file: {traceback.format_exc()}")

class SaveJsonWorker(QObject):
    finished = pyqtSignal(str)  # (path)
    error    = pyqtSignal(str)
    progress = pyqtSignal(int, str)

    def __init__(self, data: dict, path: str):
        super().__init__(None)
        self._data = data
        self._path = path

    def run(self):
        try:
            self.progress.emit(30, "Serializing JSON")
            FileManager.save_json(self._path, self._data)
            self.progress.emit(100, "Done")
            self.finished.emit(self._path)
        except Exception:
            self.error.emit(f"Failed to save JSON: {traceback.format_exc()}")