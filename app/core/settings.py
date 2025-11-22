from __future__ import annotations
from typing import List, Dict, Any, Optional
from PyQt6.QtCore import QSettings, QByteArray

ORG = "LoPTools"
APP = "LiesOfPSaveEditor"


class Settings:
    """
    Thin wrapper around QSettings.

    It exposes a small dict-like API (get/set, __getitem__/__setitem__) so
    newer code in MainWindow can treat it like a key/value store, while still
    keeping the older convenience helpers (recent_files, guid_nicknames, …).

    Keys used from the main window:

      - "win_geo"              -> window/geometry   (QByteArray)
      - "win_state"            -> window/state      (QByteArray)
      - "dark_mode"            -> ui/theme          ("dark"/"light" or bool)
      - "recent_files"         -> files/recent      (list[str])
      - "last_dir"             -> files/last_dir    (str)
      - "default_template_sav" -> files/default_template_sav (str)
    """

    def __init__(self) -> None:
        self._s = QSettings(ORG, APP)

    # ----- dict-like API used by MainWindow -----
    def get(self, key: str, default: Any = None) -> Any:
        s = self._s

        if key == "win_geo":
            v = s.value("window/geometry")
            return v if isinstance(v, QByteArray) else default

        if key == "win_state":
            v = s.value("window/state")
            return v if isinstance(v, QByteArray) else default

        if key == "dark_mode":
            v = s.value("ui/theme", "dark")
            # allow both the older string style and a stored bool
            if isinstance(v, bool):
                return v
            if isinstance(v, str):
                return v.lower() != "light"
            return bool(default)

        if key == "recent_files":
            v = s.value("files/recent", [])
            return list(v) if isinstance(v, (list, tuple)) else []

        if key == "last_dir":
            v = s.value("files/last_dir", "")
            return str(v) if isinstance(v, str) else default

        if key == "default_template_sav":
            v = s.value("files/default_template_sav", "")
            return str(v) if isinstance(v, str) else default

        # Fallback: raw QSettings value
        return s.value(key, default)

    def set(self, key: str, value: Any) -> None:
        s = self._s

        if key == "win_geo":
            s.setValue("window/geometry", value)
            return

        if key == "win_state":
            s.setValue("window/state", value)
            return

        if key == "dark_mode":
            # stored as "dark" / "light" so it is easy to inspect
            name = "dark" if bool(value) else "light"
            s.setValue("ui/theme", name)
            return

        if key == "recent_files":
            s.setValue("files/recent", list(value or []))
            return

        if key == "last_dir":
            s.setValue("files/last_dir", str(value or ""))
            return

        if key == "default_template_sav":
            s.setValue("files/default_template_sav", str(value or ""))
            return

        # Fallback: raw QSettings value
        s.setValue(key, value)

    # Allow settings["key"] syntax if we ever want it
    def __getitem__(self, key: str) -> Any:
        return self.get(key)

    def __setitem__(self, key: str, value: Any) -> None:
        self.set(key, value)

    # ---------- Window (legacy helpers) ----------
    def save_geometry(self, geo: QByteArray) -> None:
        self.set("win_geo", geo)

    def load_geometry(self) -> Optional[QByteArray]:
        return self.get("win_geo", None)

    # ---------- Theme (legacy helpers) ----------
    def theme(self) -> str:
        # keep original string form to avoid breaking older code
        return "dark" if self.get("dark_mode", True) else "light"

    def set_theme(self, name: str) -> None:
        self.set("dark_mode", name.lower() != "light")

    # ---------- UESAVE (legacy helpers) ----------
    def uesave_bin(self) -> str:
        v = self.get("tools/uesave_bin", "")
        return str(v) if isinstance(v, str) else ""

    def set_uesave_bin(self, path: str) -> None:
        self.set("tools/uesave_bin", str(path))

    # ---------- MRU (legacy helpers) ----------
    def recent_files(self) -> List[str]:
        return self.get("recent_files", [])

    def push_recent(self, path: str, max_items: int = 10) -> None:
        items = [p for p in self.recent_files() if p != path]
        items.insert(0, path)
        self.set("recent_files", items[: max(1, int(max_items))])

    # ---------- GUID Nicknames ----------
    def guid_nicknames(self) -> Dict[str, str]:
        v = self.get("nicknames/guid_map", {})
        return dict(v) if isinstance(v, dict) else {}

    def set_guid_nickname(self, guid: str, nickname: str) -> None:
        m = self.guid_nicknames()
        if nickname:
            m[guid] = nickname
        else:
            m.pop(guid, None)
        self.set("nicknames/guid_map", m)

    def resolve_guid(self, guid: str) -> str:
        return self.guid_nicknames().get(guid, guid)
