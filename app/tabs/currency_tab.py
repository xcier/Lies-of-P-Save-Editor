from __future__ import annotations
from typing import Any, Dict, List, Tuple, Optional
import re

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QHeaderView, QPushButton, QSpinBox
)

# ---------- shared helpers ----------

INT32_MAX = (2**31) - 1
JSON = Dict[str, Any]

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

def _char_struct(root: JSON) -> Dict[str, Any]:
    return _g(root, "root","properties","CharacterSaveData_0","Struct","Struct", default={}) or {}

def _items_array(root: JSON) -> List[Dict[str, Any]]:
    base = _g(root, "root","properties","CharacterSaveData_0","Struct","Struct",
                   "CharacterItem_0","Struct","Struct", default=None)
    if isinstance(base, dict):
        arr = _g(base, "PlayerItems_0","Array","Struct","value") or _g(base, "PlayerItems_0","Array","value")
        if isinstance(arr, list):
            return arr
    base = _g(root, "root","properties","CharacterItem_0","Struct","Struct", default=None)
    if isinstance(base, dict):
        arr = _g(base, "PlayerItems_0","Array","Struct","value") or _g(base, "PlayerItems_0","Array","value")
        if isinstance(arr, list):
            return arr
    return []

def _item_code(entry: Dict[str, Any]) -> str:
    return str(entry.get("Struct", {}).get("FirstCodeName_0", {}).get("Name") or "")

def _count_read(entry: Dict[str, Any]) -> int:
    node = entry.get("Struct", {}).get("Count_0", {})
    if "Int64" in node:
        try: return int(node.get("Int64") or 0)
        except Exception: return 0
    try: return int(node.get("Int") or 0)
    except Exception: return 0

def _count_write(entry: Dict[str, Any], value: int) -> None:
    st = entry.setdefault("Struct", {})
    node = st.setdefault("Count_0", {})
    v = max(0, min(INT32_MAX, int(value)))
    if "Int64" in node and "Int" not in node:
        node["Int64"] = v
        node["tag"]   = {"data": {"Other": "Int64Property"}}
    else:
        node["Int"]   = v
        node["tag"]   = {"data": {"Other": "IntProperty"}}

def _ensure_item(root: JSON, code: str) -> Dict[str, Any]:
    items = _items_array(root)
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

def _norm(s: str) -> str:
    return "".join(ch for ch in (s or "").casefold() if ch.isalnum())

# ---------- currency families (positive filter) ----------

BOSS_RX       = re.compile(r"(CH\d+_Boss_Ergo|Boss.*Ergo|Ergo.*Boss|_BossErgo|Nameless.*Ergo)", re.I)
QUARTZ_RX     = re.compile(r"^Quartz$", re.I)
LEGION_CAL_RX = re.compile(r"^Reinforce[\s_]?SlaveArm_?G(?P<g>[1-4])$", re.I)
LEGION_PLUG_F = [re.compile(r"^Legion[\s_]?Plug$", re.I),
                 re.compile(r"^Exchange[\s_]?SlaveArm[\s_]?Parts[\s_]?4$", re.I)]
GOLD_FRUIT_F  = [re.compile(r"^Gold(?:en)?[\s_]?Coin[\s_]?Fruit$", re.I),
                 re.compile(r"^Exchange[\s_]?Golden[\s_]?Fruit$", re.I)]
PLAT_RX       = re.compile(r"^Consume[\s_]?Etc[\s_]?Platinumcoin_?(?P<kind>Fancy|Hidden|Low)$", re.I)
VEN_RX        = re.compile(r"Venigni", re.I)

CANON = {
    "quartz": "quartz",
    "legionplug": "Exchange_SlaveArm_Parts_4",
    "goldcoinfruit": "Exchange_GoldenFruit",
    "plat:fancy": "Consume_Etc_Platinumcoin_Fancy",
    "plat:hidden": "Consume_Etc_Platinumcoin_Hidden",
    "plat:low": "Consume_Etc_Platinumcoin_Low",
    "venigni": "VenigniCommemorativeCoin",
}

def _is_currency_code(code: str) -> bool:
    if not code:
        return False
    return (
        QUARTZ_RX.match(code) or
        LEGION_CAL_RX.match(code) or
        any(rx.match(code) for rx in LEGION_PLUG_F) or
        any(rx.match(code) for rx in GOLD_FRUIT_F) or
        PLAT_RX.match(code) or
        VEN_RX.search(code) or
        BOSS_RX.search(code)
    )

def _group_key_for_code(code: str) -> Tuple[str, str]:
    """Return (group_key, display_label). Boss ergos remain separate per code."""
    if BOSS_RX.search(code):
        return (f"boss::{code}", _pretty_from_code(code))
    if QUARTZ_RX.match(code):
        return ("quartz", "Quartz")
    m = LEGION_CAL_RX.match(code)
    if m:
        g = m.group("g")
        return (f"caliber:g{g}", f"Reinforce Slavearm G{g}")
    if any(rx.match(code) for rx in LEGION_PLUG_F):
        return ("legionplug", "Legion Plug")
    if any(rx.match(code) for rx in GOLD_FRUIT_F):
        return ("goldcoinfruit", "Gold Coin Fruit")
    mp = PLAT_RX.match(code)
    if mp:
        kind = mp.group("kind").lower()
        return (f"plat:{kind}", f"Consume Etc Platinumcoin {kind.title()}")
    if VEN_RX.search(code):
        return ("venigni", "Venigni Commemorative Coin")
    # fallback — shouldn’t happen because we prefilter, but keep safe:
    return (f"code::{_norm(code)}", _pretty_from_code(code))

def _pretty_from_code(code: str) -> str:
    if not code:
        return ""
    s = code.replace("_", " ").strip()
    s = s.replace("Reinforce SlaveArm", "Reinforce Slavearm")
    s = s.replace("GoldenCoinFruit", "Gold Coin Fruit")
    s = s.replace("LegionPlug", "Legion Plug")
    s = s.replace("Consume Etc Platinumcoin", "Consume Etc Platinumcoin")
    return s

# ---------- the tab ----------

class CurrencyTab(QWidget):
    def __init__(self, main_window):
        super().__init__(main_window)
        self.main = main_window
        self._save: Optional[JSON] = None

        self.tbl = QTableWidget(0, 2, self)
        self.tbl.setAlternatingRowColors(True)
        self.tbl.setHorizontalHeaderLabels(["Currency", "Count"])
        hdr = self.tbl.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)

        self.btn_rescan = QPushButton("Rescan")
        self.btn_rescan.clicked.connect(self.rebuild)

        top = QHBoxLayout()
        top.addStretch(1)
        top.addWidget(self.btn_rescan)

        wrap = QVBoxLayout(self)
        wrap.addLayout(top)
        wrap.addWidget(self.tbl)

    def load_data(self, data: JSON) -> None:
        self._save = data
        self.rebuild()

    def rebuild(self) -> None:
        self.tbl.setRowCount(0)
        if not self._save:
            return

        # ---- Ergo (Souls) as first row ----
        souls = int(_g(_char_struct(self._save), "AcquisitionSoul_0","Int", default=0))
        r = self.tbl.rowCount(); self.tbl.insertRow(r)
        self.tbl.setItem(r, 0, self._ro("Ergo (Souls)"))
        sb = QSpinBox(self.tbl); sb.setRange(0, INT32_MAX); sb.setValue(min(souls, INT32_MAX))
        sb.valueChanged.connect(lambda v: self._set_souls(int(v)))
        self.tbl.setCellWidget(r, 1, sb)

        # ---- group currency-like items only ----
        items = _items_array(self._save)
        groups: Dict[str, Dict[str, Any]] = {}
        for e in items:
            code = _item_code(e)
            if not _is_currency_code(code):
                continue
            gkey, label = _group_key_for_code(code)
            bucket = groups.setdefault(gkey, {"codes": [], "label": label})
            if code not in bucket["codes"]:
                bucket["codes"].append(code)

        # Ensure canonical groups so user can create them by editing the spinner
        for k, canon in CANON.items():
            groups.setdefault(k, {"codes": [], "label": _pretty_from_code(canon)})
        for g in ("1","2","3","4"):
            groups.setdefault(f"caliber:g{g}", {"codes": [], "label": f"Reinforce Slavearm G{g}"})

        def sort_key(pair):
            k, meta = pair
            return (k.startswith("boss::"), meta["label"].lower())

        for key, meta in sorted(groups.items(), key=sort_key):
            if key == "boss_total_synthetic":
                continue
            label, codes = meta["label"], meta["codes"]

            r = self.tbl.rowCount(); self.tbl.insertRow(r)
            self.tbl.setItem(r, 0, self._ro(label))

            spin = QSpinBox(self.tbl)
            spin.setRange(0, INT32_MAX)
            total = self._sum_codes(codes)
            spin.setValue(min(total, INT32_MAX))
            if len(codes) > 1:
                spin.setToolTip(f"Variants: {', '.join(codes)}\nActual total: {total:,}")
            elif codes:
                spin.setToolTip(f"Code: {codes[0]}\nActual total: {total:,}")
            else:
                spin.setToolTip(f"Code: {self._canonical_for(key)}\nActual total: {total:,}")

            spin.valueChanged.connect(lambda v, k=key, cs=list(codes): self._write_group(k, cs, int(v)))
            self.tbl.setCellWidget(r, 1, spin)

        # ---- Boss total (read-only) ----
        total = self._boss_total()
        r = self.tbl.rowCount(); self.tbl.insertRow(r)
        self.tbl.setItem(r, 0, self._ro("Boss Ergos (total)"))
        ro = QSpinBox(self.tbl); ro.setEnabled(False); ro.setRange(0, INT32_MAX)
        ro.setValue(min(total, INT32_MAX)); ro.setToolTip(f"Actual total: {total:,}")
        self.tbl.setCellWidget(r, 1, ro)

    # ----- helpers -----
    def _ro(self, text: str) -> QTableWidgetItem:
        it = QTableWidgetItem(text)
        it.setFlags(Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled)
        return it

    def _canonical_for(self, key: str) -> Optional[str]:
        if key.startswith("boss::"): return None
        if key.startswith("caliber:g"):
            g = key.split(":",1)[1][-1]
            return f"Reinforce_SlaveArm_G{g}"
        return CANON.get(key)

    def _sum_codes(self, codes: List[str]) -> int:
        if not codes: return 0
        wanted = set(codes); total = 0
        for e in _items_array(self._save):
            if _item_code(e) in wanted:
                total += _count_read(e)
        return total

    def _write_group(self, key: str, codes: List[str], value: int) -> None:
        if not self._save: return
        v = max(0, min(INT32_MAX, int(value)))
        items = _items_array(self._save)

        wrote = False
        wanted = set(codes or [])
        for e in items:
            if _item_code(e) in wanted:
                _count_write(e, v); wrote = True

        if not wrote:
            canon = self._canonical_for(key)
            if canon:
                e = _ensure_item(self._save, canon)
                _count_write(e, v)

    def _boss_total(self) -> int:
        total = 0
        for e in _items_array(self._save or {}):
            c = _item_code(e)
            if c and BOSS_RX.search(c):
                total += _count_read(e)
        return total

    def _set_souls(self, v: int) -> None:
        ch = _char_struct(self._save or {})
        node = ch.setdefault("AcquisitionSoul_0", {"tag":{"data":{"Other":"IntProperty"}}, "Int": 0})
        node["Int"] = max(0, min(INT32_MAX, int(v)))

# ----- factory for MainWindow -----

def create_tab(main_window) -> CurrencyTab:
    return CurrencyTab(main_window)
