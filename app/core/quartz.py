from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple
import json
import os

import sys
from pathlib import Path

GUID0 = "00000000-0000-0000-0000-000000000000"

def _tail(key: str) -> str:
    if not isinstance(key, str):
        return ""
    return key.split(".", 1)[-1]

def _find_key_by_tail(d: Dict[str, Any], wanted_tail: str) -> Optional[str]:
    wanted = wanted_tail.lower()
    for k in d.keys():
        if _tail(k).lower() == wanted:
            return k
    return None

def find_quartz_node(root_json: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Return the dict value for QuartzData_0 (the wrapper containing tag + Struct)."""
    stack = [root_json]
    seen = 0
    while stack:
        cur = stack.pop()
        seen += 1
        if seen > 500000:
            break
        if isinstance(cur, dict):
            for k, v in cur.items():
                if isinstance(k, str) and _tail(k).lower() == "quartzdata_0":
                    return v if isinstance(v, dict) else None
                if isinstance(v, (dict, list)):
                    stack.append(v)
        elif isinstance(cur, list):
            stack.extend(cur)
    return None

def find_quartz_struct(root_json: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Return the inner quartz struct dict: QuartzData_0 -> Struct -> Struct -> (fields)."""
    node = find_quartz_node(root_json)
    if not isinstance(node, dict):
        return None
    s = node.get("Struct", {}).get("Struct", {})
    return s if isinstance(s, dict) else None


def ensure_quartz_data(root_json: Dict[str, Any]) -> Dict[str, Any]:
    """Ensure QuartzData_0 wrapper exists in the save. Returns QuartzData_0 dict."""
    node = find_quartz_node(root_json)
    if isinstance(node, dict):
        return node

    # Prefer a packaged template (captures exact layout from a known-good save).
    tmpl = _load_quartzdata_template()
    if isinstance(tmpl, dict) and "Struct" in tmpl:
        # deep copy (avoid mutating the template in memory)
        wrapper = json.loads(json.dumps(tmpl))
    else:
        # Fallback: minimal wrapper schema uesave emits
        wrapper = {
            "tag": {"data": {"Struct": {"struct_type": {"Struct": "LQuartzSaveData"}, "id": GUID0}}},
            "Struct": {"Struct": {}},
        }
    # Insert at top-level when possible, otherwise attach to root
    root_json["QuartzData_0"] = wrapper
    return wrapper

def ensure_quartz_struct(root_json: Dict[str, Any]) -> Dict[str, Any]:
    """Ensure the inner Quartz struct dict exists and has required fields."""
    wrapper = ensure_quartz_data(root_json)
    qstruct = wrapper.setdefault("Struct", {}).setdefault("Struct", {})
    if not isinstance(qstruct, dict):
        wrapper["Struct"]["Struct"] = {}
        qstruct = wrapper["Struct"]["Struct"]

    # baseline fields (safe defaults)
    ensure_prop_bool(qstruct, "ActivateQuartzSystem_0", True)
    ensure_prop_int(qstruct, "CoreLevel_0", 7)
    ensure_prop_int(qstruct, "CoreLevelupType_0", 2)
    # ensure the array exists (empty ok)
    _ensure_effect_list(qstruct)
    return qstruct

def ensure_prop_bool(struct: Dict[str, Any], tail_name: str, default: bool = False) -> Dict[str, Any]:
    k = _find_key_by_tail(struct, tail_name) or tail_name
    node = struct.get(k)
    if not isinstance(node, dict) or "Bool" not in node:
        node = {"tag": {"data": {"Other": "BoolProperty"}}, "Bool": bool(default)}
        struct[k] = node
    return node

def ensure_prop_int(struct: Dict[str, Any], tail_name: str, default: int = 0) -> Dict[str, Any]:
    k = _find_key_by_tail(struct, tail_name) or tail_name
    node = struct.get(k)
    if not isinstance(node, dict) or "Int" not in node:
        node = {"tag": {"data": {"Other": "IntProperty"}}, "Int": int(default)}
        struct[k] = node
    return node

def ensure_prop_name(struct: Dict[str, Any], tail_name: str, default: str = "None") -> Dict[str, Any]:
    k = _find_key_by_tail(struct, tail_name) or tail_name
    node = struct.get(k)
    if not isinstance(node, dict) or "Name" not in node:
        node = {"tag": {"data": {"Other": "NameProperty"}}, "Name": str(default)}
        struct[k] = node
    return node

def _ensure_effect_list(quartz_struct: Dict[str, Any]) -> Tuple[str, List[Dict[str, Any]]]:
    """Create (if missing) and return (key, list_of_entry_struct_dicts)."""
    k = _find_key_by_tail(quartz_struct, "EffectSaveDataList_0") or "EffectSaveDataList_0"
    node = quartz_struct.get(k)
    if not isinstance(node, dict):
        node = {}
        quartz_struct[k] = node

    node.setdefault(
        "tag",
        {"data": {"Array": {"Struct": {"struct_type": {"Struct": None}, "id": GUID0}}}},
    )
    arr = node.setdefault("Array", {})
    stwrap = arr.setdefault("Struct", {})
    stwrap.setdefault("type_", "StructProperty")
    stwrap.setdefault("struct_type", {"Struct": "LQuartzEffectSaveData"})
    stwrap.setdefault("id", GUID0)
    value = stwrap.setdefault("value", [])
    if not isinstance(value, list):
        value = []
        stwrap["value"] = value

    # normalize to list[{"Struct": {...}}]
    new_value = []
    entries: List[Dict[str, Any]] = []
    for it in value:
        if isinstance(it, dict) and isinstance(it.get("Struct"), dict):
            new_value.append(it)
            entries.append(it["Struct"])
        elif isinstance(it, dict):
            new_value.append({"Struct": it})
            entries.append(it)
    stwrap["value"] = new_value
    return k, entries

def get_effect_list(quartz_struct: Dict[str, Any], create: bool = False) -> List[Dict[str, Any]]:
    """Return list of LQuartzEffectSaveData inner structs."""
    if not isinstance(quartz_struct, dict):
        return []
    k = _find_key_by_tail(quartz_struct, "EffectSaveDataList_0") or "EffectSaveDataList_0"
    node = quartz_struct.get(k)
    if not isinstance(node, dict):
        if not create:
            return []
        _, entries = _ensure_effect_list(quartz_struct)
        return entries
    try:
        value = node.get("Array", {}).get("Struct", {}).get("value", [])
        if not isinstance(value, list):
            return []
        out = []
        for it in value:
            if isinstance(it, dict) and isinstance(it.get("Struct"), dict):
                out.append(it["Struct"])
            elif isinstance(it, dict):
                out.append(it)
        return out
    except Exception:
        return []

def build_index_map(entries: List[Dict[str, Any]]) -> Dict[Tuple[str, int], Dict[str, Any]]:
    """(pocket, slot)->entry_struct"""
    out: Dict[Tuple[str, int], Dict[str, Any]] = {}
    for e in entries or []:
        if not isinstance(e, dict):
            continue
        p = (e.get(_find_key_by_tail(e, "QuartzPocketCodeName_0") or "QuartzPocketCodeName_0") or {}).get("Name")
        s = (e.get(_find_key_by_tail(e, "SlotIndex_0") or "SlotIndex_0") or {}).get("Int")
        if isinstance(p, str) and isinstance(s, int):
            out[(p, s)] = e
    return out

def make_effect_struct(pocket: str, slot: int, effect: str) -> Dict[str, Any]:
    """Create a new LQuartzEffectSaveData entry struct."""
    st: Dict[str, Any] = {}
    ensure_prop_name(st, "QuartzPocketCodeName_0", pocket)["Name"] = pocket
    ensure_prop_name(st, "QuartzEffectCodename_0", effect)["Name"] = effect
    ensure_prop_int(st, "SlotIndex_0", slot)["Int"] = int(slot)
    return st


# ---------------- Defaults DB ----------------

def _default_user_db_path() -> Path:
    """Where to store persistent Quartz defaults for 'golden save' behavior.

    Mirrors InventoryTab's db strategy:
      - If LOP_USER_DB_PATH env var is set:
          * directory -> <dir>/quartz_defaults.json
          * file      -> that file
      - Windows: %APPDATA%/LoPSaveEditor/quartz_defaults.json
      - Other: ~/.lop_save_editor/quartz_defaults.json
    """
    env = os.environ.get("LOP_USER_DB_PATH", "").strip()
    if env:
        p = Path(env).expanduser()
        if p.is_dir():
            return p / "quartz_defaults.json"
        return p

    if sys.platform.startswith("win"):
        base = Path(os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming")))
        return base / "LoPSaveEditor" / "quartz_defaults.json"

    return Path.home() / ".lop_save_editor" / "quartz_defaults.json"

def _builtin_defaults_path() -> Optional[Path]:
    """Packaged defaults shipped with the app (optional)."""
    try:
        # quartz.py = app/core/quartz.py -> resources is ../resources
        p = Path(__file__).resolve().parents[1] / "resources" / "quartz_defaults_builtin.json"
        return p if p.exists() else None
    except Exception:
        return None

def _builtin_quartzdata_template_path() -> Optional[Path]:
    """Optional packaged QuartzData_0 wrapper template (exact uesave layout)."""
    try:
        p = Path(__file__).resolve().parents[1] / "resources" / "quartzdata_template.json"
        return p if p.exists() else None
    except Exception:
        return None

def _load_quartzdata_template() -> Optional[Dict[str, Any]]:
    p = _builtin_quartzdata_template_path()
    if not p:
        return None
    try:
        obj = json.loads(p.read_text(encoding="utf-8", errors="ignore"))
        return obj if isinstance(obj, dict) else None
    except Exception:
        return None

def _defaults_path(app_dir: Optional[str] = None) -> Path:
    """Preferred path to the writable defaults db file."""
    if app_dir:
        return Path(app_dir) / "data" / "quartz_defaults.json"
    return _default_user_db_path()

def load_defaults_db(app_dir: Optional[str] = None) -> Dict[str, Dict[str, str]]:
    """Load defaults mapping.

    Search order:
      1) packaged builtin defaults (app/resources/quartz_defaults_builtin.json)
      2) user writable db (app_dir/data or user db path) **overrides** builtin

    Rationale:
      - The builtin file is the canonical "full grid" of all Quartz pockets/slots.
      - The user db is treated as an overlay (customizations / learned values).
        This prevents a partial user db from shrinking the UI grid.
    """
    path = _defaults_path(app_dir)

    out: Dict[str, Dict[str, str]] = {}

    # 1) builtin (canonical)
    b = _builtin_defaults_path()
    if b:
        try:
            data = json.loads(b.read_text(encoding="utf-8", errors="ignore"))
            if isinstance(data, dict):
                for p, slots in data.items():
                    if not isinstance(p, str) or not isinstance(slots, dict):
                        continue
                    out[p] = {str(k): str(v) for k, v in slots.items() if v is not None and str(v) != ""}
        except Exception:
            pass

    # 2) user db (overlay)
    try:
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8", errors="ignore"))
            if isinstance(data, dict):
                for p, slots in data.items():
                    if not isinstance(p, str) or not isinstance(slots, dict):
                        continue
                    out.setdefault(p, {})
                    for k, v in slots.items():
                        if v is None:
                            continue
                        sv = str(v)
                        if sv == "":
                            continue
                        out[p][str(k)] = sv
    except Exception:
        pass

    return out

def save_defaults_db(db: Dict[str, Dict[str, str]], app_dir: Optional[str] = None) -> str:
    path = _defaults_path(app_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    out: Dict[str, Dict[str, str]] = {}
    for p, slots in (db or {}).items():
        if not isinstance(p, str) or not isinstance(slots, dict):
            continue
        out[p] = {str(k): str(v) for k, v in slots.items() if v is not None and str(v) != ""}
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return str(path)

def merge_defaults_db(existing: Dict[str, Dict[str, str]], incoming: Dict[str, Dict[str, str]]) -> Dict[str, Dict[str, str]]:
    """Merge pocket/slot defaults, preferring existing values when conflicts occur."""
    out = {p: dict(slots) for p, slots in (existing or {}).items() if isinstance(slots, dict)}
    for p, slots in (incoming or {}).items():
        if not isinstance(p, str) or not isinstance(slots, dict):
            continue
        out.setdefault(p, {})
        for s, eff in slots.items():
            if str(s) not in out[p] and eff is not None:
                out[p][str(s)] = str(eff)
    return out

def derive_defaults_from_quartz(quartz_struct: Dict[str, Any]) -> Dict[str, Dict[str, str]]:
    """Build defaults mapping from current save (only slots present)."""
    entries = get_effect_list(quartz_struct, create=False)
    db: Dict[str, Dict[str, str]] = {}
    for e in entries:
        if not isinstance(e, dict):
            continue
        p = (e.get(_find_key_by_tail(e, "QuartzPocketCodeName_0") or "QuartzPocketCodeName_0") or {}).get("Name")
        s = (e.get(_find_key_by_tail(e, "SlotIndex_0") or "SlotIndex_0") or {}).get("Int")
        eff = (e.get(_find_key_by_tail(e, "QuartzEffectCodename_0") or "QuartzEffectCodename_0") or {}).get("Name")
        if isinstance(p, str) and isinstance(s, int) and isinstance(eff, str):
            db.setdefault(p, {})[str(s)] = eff
    return db
