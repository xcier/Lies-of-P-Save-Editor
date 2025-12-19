# app/core/weapon_parts_db.py
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
import json

from app.core.settings import Settings


@dataclass(frozen=True)
class PartInfo:
    code: str
    name: str
    tooltip: str
    kind: str  # "handle" or "blade"


class WeaponPartsDB:
    """
    Weapon parts database.

    - Base DB lives in app/resources/weapon_parts_db.json (generated from item_list.csv).
    - User additions/overrides are stored in QSettings as JSON under key 'weapons/user_db'.
      This keeps the DB portable even if the app is installed in Program Files.
    """

    def __init__(self, base_json: Path, settings: Optional[Settings] = None) -> None:
        self._base_json = Path(base_json)
        self._settings = settings or Settings()
        self._handles: Dict[str, PartInfo] = {}
        self._blades: Dict[str, PartInfo] = {}
        self.reload()

    def reload(self) -> None:
        base = self._load_json(self._base_json)
        self._handles = self._to_parts(base.get("handles", {}), "handle")
        self._blades  = self._to_parts(base.get("blades", {}), "blade")

        # Apply user overrides/additions
        user = self._settings.get("weapons/user_db", None)
        if user:
            try:
                u = json.loads(str(user))
                self._apply_user(u)
            except Exception:
                # Ignore bad user DB; keep base
                pass

    def export_user_db(self) -> Dict[str, Any]:
        """Return the user DB (overrides/additions) as a dict."""
        raw = self._settings.get("weapons/user_db", None)
        if not raw:
            return {"handles": {}, "blades": {}}
        try:
            return json.loads(str(raw))
        except Exception:
            return {"handles": {}, "blades": {}}

    def import_user_db(self, obj: Dict[str, Any]) -> None:
        """Replace user DB and reload."""
        self._settings.set("weapons/user_db", json.dumps(obj, ensure_ascii=False, indent=2))
        self.reload()

    def upsert_user_part(self, kind: str, code: str, name: str = "", tooltip: str = "") -> None:
        """
        Add or override a part in the user DB.
        kind: 'handle' or 'blade'
        """
        kind = "handle" if kind.lower().startswith("h") else "blade"
        db = self.export_user_db()
        bucket = db.setdefault("handles" if kind == "handle" else "blades", {})
        bucket[code] = {"name": name, "tooltip": tooltip}
        self.import_user_db(db)

    def get_handles(self) -> List[PartInfo]:
        return sorted(self._handles.values(), key=lambda p: (p.name.lower() or p.code.lower(), p.code.lower()))

    def get_blades(self) -> List[PartInfo]:
        return sorted(self._blades.values(), key=lambda p: (p.name.lower() or p.code.lower(), p.code.lower()))

    def lookup(self, code: str) -> Optional[PartInfo]:
        if code in self._handles:
            return self._handles[code]
        if code in self._blades:
            return self._blades[code]
        return None

    def label_for_code(self, code: str) -> str:
        info = self.lookup(code)
        if not info:
            return code
        n = info.name.strip() or code
        return f"{n}  [{code}]"

    # ---------------- internal ----------------
    @staticmethod
    def _load_json(path: Path) -> Dict[str, Any]:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    @staticmethod
    def _to_parts(bucket: Dict[str, Any], kind: str) -> Dict[str, PartInfo]:
        out: Dict[str, PartInfo] = {}
        for code, meta in (bucket or {}).items():
            if not isinstance(meta, dict):
                meta = {}
            out[code] = PartInfo(
                code=code,
                name=str(meta.get("name", "") or ""),
                tooltip=str(meta.get("tooltip", "") or ""),
                kind=kind,
            )
        return out

    def _apply_user(self, user: Dict[str, Any]) -> None:
        # Merge overrides/additions
        for kind, dest in (("handles", self._handles), ("blades", self._blades)):
            bucket = user.get(kind, {})
            if not isinstance(bucket, dict):
                continue
            real_kind = "handle" if kind == "handles" else "blade"
            for code, meta in bucket.items():
                if not isinstance(meta, dict):
                    meta = {}
                dest[code] = PartInfo(
                    code=code,
                    name=str(meta.get("name", "") or ""),
                    tooltip=str(meta.get("tooltip", "") or ""),
                    kind=real_kind,
                )
