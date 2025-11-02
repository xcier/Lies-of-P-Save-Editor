from __future__ import annotations
from typing import List, Dict
from PyQt6.QtCore import QSettings, QByteArray

ORG = "LoPTools"
APP = "LiesOfPSaveEditor"

class Settings:
    def __init__(self):
        self._s = QSettings(ORG, APP)

    # ---------- Window ----------
    def save_geometry(self, geo: QByteArray):
        self._s.setValue("window/geometry", geo)
    def load_geometry(self) -> QByteArray | None:
        v = self._s.value("window/geometry")
        return v if isinstance(v, QByteArray) else None

    # ---------- Theme ----------
    def theme(self) -> str:
        return self._s.value("ui/theme", "dark")
    def set_theme(self, name: str):
        self._s.setValue("ui/theme", name)

    # ---------- UESAVE ----------
    def uesave_bin(self) -> str:
        return self._s.value("tools/uesave_bin", "")
    def set_uesave_bin(self, path: str):
        self._s.setValue("tools/uesave_bin", path)

    # ---------- MRU ----------
    def recent_files(self) -> List[str]:
        v = self._s.value("files/recent", [])
        return list(v) if isinstance(v, (list, tuple)) else []
    def push_recent(self, path: str, max_items: int = 10):
        items = [p for p in self.recent_files() if p != path]
        items.insert(0, path)
        self._s.setValue("files/recent", items[:max_items])

    # ---------- GUID Nicknames ----------
    def guid_nicknames(self) -> Dict[str, str]:
        v = self._s.value("nicknames/guid_map", {})
        return dict(v) if isinstance(v, dict) else {}
    def set_guid_nickname(self, guid: str, nickname: str):
        m = self.guid_nicknames()
        if nickname:
            m[guid] = nickname
        else:
            m.pop(guid, None)
        self._s.setValue("nicknames/guid_map", m)
    def resolve_guid(self, guid: str) -> str:
        m = self.guid_nicknames()
        return m.get(guid, guid)