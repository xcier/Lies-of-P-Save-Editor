# app/core/cheats.py
from __future__ import annotations
from typing import Any, Dict, List, Tuple, Callable, Optional
import re

JSON = Dict[str, Any]
INT32_MAX = (2**31) - 1

# ======================== generic helpers ========================

def _lk(d: Dict[str, Any]) -> Dict[str, str]:
    return {k.lower(): k for k in d} if isinstance(d, dict) else {}

def _g(d: Dict[str, Any], *keys: str, default=None):
    cur = d
    for k in keys:
        if not isinstance(cur, dict):
            return default
        lk = _lk(cur); key = lk.get(k.lower())
        if key is None:
            return default
        cur = cur.get(key)
    return cur if cur is not None else default

def _ensure_dict(parent: Dict[str, Any], key: str) -> Dict[str, Any]:
    if key not in parent or not isinstance(parent[key], dict):
        parent[key] = {}
    return parent[key]

def _clamp32(v: Any) -> int:
    try:
        v = int(v)
    except Exception:
        return 0
    return max(0, min(INT32_MAX, v))

# --- normalized setters (support dry_run & consistent change counting) ---

def _set_int(node: Dict[str, Any], value: int, *, apply: bool) -> bool:
    """Set node to an Int/Int64 with clamped value; return True if change."""
    v = _clamp32(value)
    cur: Optional[int] = None
    if "Int" in node:
        try: cur = int(node.get("Int") or 0)
        except Exception: cur = 0
        if cur == v:  # already correct
            return False
        if apply:
            node["Int"] = v
            node["tag"] = {"data": {"Other": "IntProperty"}}
        return True

    if "Int64" in node:
        try: cur = int(node.get("Int64") or 0)
        except Exception: cur = 0
        if cur == v:
            return False
        if apply:
            node["Int64"] = v
            node["tag"] = {"data": {"Other": "Int64Property"}}
        return True

    # no numeric value present — create Int
    if apply:
        node["Int"] = v
        node["tag"] = {"data": {"Other": "IntProperty"}}
    return True

def _set_bool(node: Dict[str, Any], value: bool, *, apply: bool) -> bool:
    cur = node.get("Bool", None)
    if cur is value:
        return False
    if apply:
        node["Bool"] = bool(value)
        node.setdefault("tag", {"data": {"Other": "BoolProperty"}})
    return True

def _set_enum(node: Dict[str, Any], enum_type: str, enum_value: str, *, apply: bool) -> bool:
    """Ensure Enum has the required type and value."""
    cur = node.get("Enum")
    target = f"{enum_type}::{enum_value}" if "::" not in enum_value else enum_value
    # If current matches exactly, no change
    if isinstance(cur, str) and cur == target:
        return False
    if apply:
        node["Enum"] = target
        node["tag"] = {"data": {"Enum": [enum_type, None]}}
    return True

def _ensure_int_property(container: Dict[str, Any], key: str) -> Dict[str, Any]:
    node = _ensure_dict(container, key)
    # prefer Int; normalize if only Int64 present
    if "Int" not in node and "Int64" in node:
        try:
            node["Int"] = int(node.get("Int64") or 0)
        except Exception:
            node["Int"] = 0
        node.pop("Int64", None)
    node.setdefault("tag", {"data": {"Other": "IntProperty"}})
    node.setdefault("Int", 0)
    return node

def _ensure_bool_property(container: Dict[str, Any], key: str) -> Dict[str, Any]:
    node = _ensure_dict(container, key)
    node.setdefault("tag", {"data": {"Other": "BoolProperty"}})
    node.setdefault("Bool", False)
    return node

def _ensure_enum_property(container: Dict[str, Any], key: str, etype: str) -> Dict[str, Any]:
    node = _ensure_dict(container, key)
    node["tag"] = {"data": {"Enum": [etype, None]}}
    node.setdefault("Enum", f"{etype}::")
    return node

# ======================== save structure helpers ========================

def _char_struct(root: JSON) -> Dict[str, Any]:
    return _g(root, "root","properties","CharacterSaveData_0","Struct","Struct", default={}) or {}

def _items_array(root: JSON) -> List[Dict[str, Any]]:
    base = _g(root, "root","properties","CharacterSaveData_0","Struct","Struct",
                   "CharacterItem_0","Struct","Struct", default=None)
    if isinstance(base, dict):
        arr = _g(base, "PlayerItems_0","Array","Struct","value")
        if isinstance(arr, list): return arr
        arr = _g(base, "PlayerItems_0","Array","value")
        if isinstance(arr, list): return arr
    base = _g(root, "root","properties","CharacterItem_0","Struct","Struct", default=None)
    if isinstance(base, dict):
        arr = _g(base, "PlayerItems_0","Array","Struct","value")
        if isinstance(arr, list): return arr
        arr = _g(base, "PlayerItems_0","Array","value")
        if isinstance(arr, list): return arr
    return []

def _item_code(entry: Dict[str, Any]) -> str:
    st = entry.get("Struct", {})
    nm = st.get("FirstCodeName_0", {})
    return str(nm.get("Name") or "")

def _ensure_item(code: str, items: List[Dict[str, Any]]) -> Dict[str, Any]:
    for e in items:
        if _item_code(e) == code:
            return e
    new_entry = {"Struct": {
        "FirstCodeName_0": {"tag":{"data":{"Other":"NameProperty"}}, "Name": code},
        "Count_0":        {"tag":{"data":{"Other":"IntProperty"}},   "Int": 0},
        "EquipItemSlotType_0": {"tag":{"data":{"Enum":["ELEquipSlotType", None]}}, "Enum":"ELEquipSlotType::E_NONE"},
    }}
    items.append(new_entry)
    return new_entry

def _norm_code(s: str) -> str:
    return "".join(ch for ch in (s or "").casefold() if ch.isalnum())

def _set_count(entry: Dict[str, Any], value: int, *, apply: bool) -> bool:
    st = entry.setdefault("Struct", {})
    node = st.setdefault("Count_0", {})
    return _set_int(node, value, apply=apply)

# ============================ cheats ============================

def godmode(data: JSON, *, dry_run: bool = False) -> int:
    """
    Sets health points to INT32_MAX for both common keys.
    Returns number of fields changed (or that would change in dry_run).
    """
    ch = _char_struct(data)
    changed = 0
    for key in ("SecondStat_HeadthPoint_0", "SecondStat_HealthPoint_0"):
        node = _ensure_int_property(ch, key)
        if _set_int(node, INT32_MAX, apply=not dry_run):
            changed += 1
    return changed

def _set_primary_stats_100(data: JSON, *, dry_run: bool) -> int:
    ch = _char_struct(data)
    arr = _g(ch, "FirstStatSimpleList_0","Array","Struct","value")
    if not isinstance(arr, list):
        arr = _g(ch, "FirstStatSimpleList_0","Array","value")
    if not isinstance(arr, list):
        return 0
    changed = 0
    for e in arr:
        st = e.get("Struct", {})
        node = st.get("StatData_0")
        if isinstance(node, dict):
            if _set_int(node, 100, apply=not dry_run):
                changed += 1
    return changed

def insane_stats(data: JSON, *, dry_run: bool = False) -> Dict[str, int]:
    """
    Super-charges many player stats. Returns a counters dict:
      {"character": X, "lamp": 0, "stats_primary": Y, "stats_secondary": Z}
    (lamp kept for compatibility/future use)
    """
    counters = {"character": 0, "lamp": 0, "stats_primary": 0, "stats_secondary": 0}
    ch = _char_struct(data)

    counters["stats_primary"] += _set_primary_stats_100(data, dry_run=dry_run)

    for key, val in (
        ("PlayerLevel_0",                 999),
        ("AcquisitionSoul_0",             999_999_999),
        ("NextLevelUpRequireSoul_0",      0),
        ("HumanityLevel_0",               999),
        ("AcquisitionHumanity_0",         999_999_999),
        ("NewGamePlus_Round_0",           999),
    ):
        if _set_int(_ensure_int_property(ch, key), val, apply=not dry_run):
            counters["character"] += 1

    # Reset playtime to 0.0 (Double)
    pt = ch.setdefault("CharacterPlayTime_0", {"tag":{"data":{"Other":"DoubleProperty"}}, "Double": 0.0})
    if isinstance(pt, dict):
        cur = pt.get("Double", 0.0)
        if cur != 0.0:
            if not dry_run:
                pt["Double"] = 0.0
            counters["character"] += 1

    for key in (
        "YouDieCount_0",
        "TotalReceiveDamage_0",
    ):
        if _set_int(_ensure_int_property(ch, key), 0, apply=not dry_run):
            counters["character"] += 1

    secondary = (
        "SecondStat_HeadthPoint_0", "SecondStat_HealthPoint_0",
        "SecondStat_FrenzyPoint_0",
        "SecondStat_SlaveMagazinePoint_0", "SecondStat_SlaveMagazine_0",
        "SecondStat_PulseRechargePoint_0", "SecondStat_PulseRecharge_0",
    )
    for k in secondary:
        if _set_int(_ensure_int_property(ch, k), 999_999_999, apply=not dry_run):
            counters["stats_secondary"] += 1

    return counters

def max_currency(
    data: JSON,
    max_value: int = 999_999_999,
    *,
    create_missing: bool = True,
    dry_run: bool = False
) -> int:
    """
    Raise souls and many currency-like inventory items to max_value.
    Returns the number of item/field updates.
    """
    changed = 0
    ch = _char_struct(data)
    items = _items_array(data)
    v = _clamp32(max_value)

    # Soul count in character struct
    souls = _ensure_int_property(ch, "AcquisitionSoul_0")
    if _set_int(souls, v, apply=not dry_run):
        changed += 1

    def norm(s: str) -> str:
        return "".join(c for c in (s or "").casefold() if c.isalnum())

    by_norm: Dict[str, List[Dict[str, Any]]] = {}
    for e in items:
        by_norm.setdefault(norm(_item_code(e)), []).append(e)

    def set_all_matching(regexes: List[re.Pattern]) -> int:
        hits = 0
        for e in items:
            code = _item_code(e)
            if code and any(rx.search(code) for rx in regexes):
                if _set_count(e, v, apply=not dry_run):
                    hits += 1
        return hits

    def ensure_canonical(code: str):
        nonlocal changed
        key = norm(code)
        if key in by_norm or not create_missing:
            return
        e = _ensure_item(code, items)
        by_norm.setdefault(key, []).append(e)
        if _set_count(e, v, apply=not dry_run):
            changed += 1

    CANON = [
        "quartz",
        "Reinforce_SlaveArm_G1", "Reinforce_SlaveArm_G2", "Reinforce_SlaveArm_G3", "Reinforce_SlaveArm_G4",
        "Exchange_SlaveArm_Parts_4",
        "Exchange_GoldenFruit",
        "Consume_Etc_Platinumcoin_Fancy", "Consume_Etc_Platinumcoin_Hidden", "Consume_Etc_Platinumcoin_Low",
        "VenigniCommemorativeCoin",
    ]

    FAMS = [
        [re.compile(r"^Quartz$", re.I)],
        [re.compile(r"^Reinforce[\s_]?SlaveArm_", re.I)],
        [re.compile(r"Legion[\s_]?Plug|^Exchange[\s_]?SlaveArm[\s_]?Parts[\s_]?4$", re.I)],
        [re.compile(r"Gold(?:en)?[\s_]?Coin[\s_]?Fruit|^Exchange[\s_]?Golden[\s_]?Fruit$", re.I)],
        [re.compile(r"^Consume[\s_]?Etc[\s_]?Platinumcoin(?:$|[\s_].*)", re.I)],
        [re.compile(r"Venigni", re.I)],
    ]

    for fam in FAMS:
        changed += set_all_matching(fam)

    for code in CANON:
        ensure_canonical(code)

    boss_pat = re.compile(r"(CH\d+_Boss_Ergo|Boss.*Ergo|Ergo.*Boss|_BossErgo|Nameless.*Ergo)", re.I)
    for e in items:
        code = _item_code(e)
        if code and boss_pat.search(code):
            if _set_count(e, v, apply=not dry_run):
                changed += 1

    return changed

def unlock_all_locations(data: JSON, *, dry_run: bool = False) -> int:
    """
    Sets all stargazers to ACTIVE/IDLE and toggles necessary flags.
    Returns the number of fields updated.
    """
    changed = 0
    spot = _g(data, "root","properties","SpotSaveData_0","Struct","Struct", default={})
    arr = _g(spot, "TeleportObjectSpotList_0","Array","Struct","value")
    if not isinstance(arr, list):
        arr = _g(spot, "TeleportObjectSpotList_0","Array","value")
    if not isinstance(arr, list):
        return 0

    for e in arr:
        st = e.get("Struct", {})
        en = _ensure_enum_property(st, "StargazerType_0", "ELStargazerType")
        if _set_enum(en, "ELStargazerType", "E_ACTIVE_IDLE", apply=not dry_run):
            changed += 1
        if _set_bool(_ensure_bool_property(st, "ActorSpawnable_0"), True, apply=not dry_run):
            changed += 1
        if _set_bool(_ensure_bool_property(st, "ReserveActorSpawn_0"), False, apply=not dry_run):
            changed += 1
        if _set_bool(_ensure_bool_property(st, "ReserveActorDespawn_0"), False, apply=not dry_run):
            changed += 1
        if _set_bool(_ensure_bool_property(st, "TorsionCoilActivate_0"), True, apply=not dry_run):
            changed += 1
    return changed

# ===================== achievements helpers =====================

def _flip_all_bools(node: Any, *, apply: bool) -> int:
    """
    Recursively set scalar BoolProperties to True.
    IMPORTANT: does NOT touch Bool *lists* (handled elsewhere).
    """
    changed = 0
    if isinstance(node, dict):
        if "Bool" in node and isinstance(node.get("Bool"), bool):
            if _set_bool(node, True, apply=apply):
                changed += 1
        for v in node.values():
            changed += _flip_all_bools(v, apply=apply)
    elif isinstance(node, list):
        for v in node:
            changed += _flip_all_bools(v, apply=apply)
    return changed

def _set_statuslist_true(status_node: Any, *, apply: bool) -> int:
    changed = 0
    if not isinstance(status_node, dict):
        return 0
    arr = status_node.get("Array")
    if isinstance(arr, dict):
        base = arr.get("Base")
        if isinstance(base, dict) and isinstance(base.get("Bool"), list):
            bl = base["Bool"]
            for i, b in enumerate(bl):
                if b is not True:
                    if apply:
                        bl[i] = True
                    changed += 1
        bl = arr.get("Bool")
        if isinstance(bl, list):
            for i, b in enumerate(bl):
                if b is not True:
                    if apply:
                        bl[i] = True
                    changed += 1
    return changed

def auto_plat_achievements(data: JSON, *, dry_run: bool = False) -> Tuple[bool, int]:
    """
    - For any dict containing AchievementCodeName_0, set every Bool in that subtree to True.
    - For every StatusList_0 anywhere, set its Bool arrays to all True.
    Returns (found_any_achievement_blocks, total_bools_changed).
    """
    found = False
    changed = 0

    def walk(node: Any):
        nonlocal found, changed
        if isinstance(node, dict):
            lk = _lk(node)
            if "achievementcodename_0" in lk:
                found = True
                changed += _flip_all_bools(node, apply=not dry_run)
            if "statuslist_0" in lk:
                sl_node = node[lk["statuslist_0"]]
                changed += _set_statuslist_true(sl_node, apply=not dry_run)
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(data)
    return (found, changed)
