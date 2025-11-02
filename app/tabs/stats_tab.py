from __future__ import annotations
from typing import Dict, Any, Optional, List, Tuple

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QGroupBox, QFormLayout, QLabel, QSpinBox
)

# ------------- helpers -------------

def _lk(d: Dict[str, Any]) -> Dict[str, str]:
    return {k.lower(): k for k in d} if isinstance(d, dict) else {}

def _g(d: Dict[str, Any], *keys: str, default=None):
    cur = d
    for k in keys:
        if not isinstance(cur, dict):
            return default
        lk = _lk(cur)
        key = lk.get(k.lower())
        if key is None:
            return default
        cur = cur.get(key)
    return cur if cur is not None else default

def _ensure_dict(parent: Dict[str, Any], key: str) -> Dict[str, Any]:
    if key not in parent or not isinstance(parent[key], dict):
        parent[key] = {}
    return parent[key]

def _enum_tail(e: Any) -> str:
    if not isinstance(e, str):
        return ""
    s = e.strip()
    if "::" in s:
        s = s.split("::", 1)[1]
    s = s.upper()
    if not s.startswith("E_"):
        s = "E_" + s
    return s

def _full_enum_for_tail(tail: str, existing_full: Optional[str], *, default_ns: str) -> str:
    if isinstance(existing_full, str) and "::" in existing_full:
        ns = existing_full.split("::", 1)[0]
        return f"{ns}::{tail}"
    return f"{default_ns}::{tail}"

def _ensure_int_property(container: Dict[str, Any], key: str) -> Dict[str, Any]:
    """
    Make sure container[key] exists and looks like a UE IntProperty:
      { "tag":{"data":{"Other":"IntProperty"}}, "Int": 0 }
    """
    node = _ensure_dict(container, key)
    if "tag" not in node:
        node["tag"] = {"data": {"Other": "IntProperty"}}
    if "Int" not in node:
        node["Int"] = 0
    return node

def _ensure_enum_property(container: Dict[str, Any], key: str, full_enum_value: str, enum_ns_fallback: str) -> Dict[str, Any]:
    """
    Ensure an Enum node with UE tag:
      { "tag":{"data":{"Enum":[ "TypeName", null ]}}, "Enum":"TypeName::E_VALUE" }
    """
    node = _ensure_dict(container, key)
    if "tag" not in node:
        # Derive type prefix from value
        if isinstance(full_enum_value, str) and "::" in full_enum_value:
            type_name = full_enum_value.split("::", 1)[0]
        else:
            type_name = enum_ns_fallback
        node["tag"] = {"data": {"Enum": [type_name, None]}}
    node["Enum"] = full_enum_value
    return node

# ------------- constants -------------

LABELS_FIRST: List[Tuple[str,str]] = [
    ("Vitality",  "E_VITALITY"),
    ("Vigor",     "E_VIGOR"),
    ("Tenacity",  "E_TENACITY"),
    ("Capacity",  "E_CAPACITY"),
    ("Motivity",  "E_MOTIVITY"),
    ("Technique", "E_TECHNIQUE"),
    ("Advance",   "E_ADVANCE"),
]
TAIL_BY_FIRST_LABEL = {lbl: tail for (lbl, tail) in LABELS_FIRST}

# Canonical secondaries + tolerant key search (handles game's typo "HeadthPoint")
SECOND_CANONICAL: List[Tuple[str, str]] = [
    ("SecondStat_HeadthPoint_0",        "Health Points"),
    ("SecondStat_FrenzyPoint_0",        "Frenzy Points"),
    ("SecondStat_SlaveMagazinePoint_0", "Slave Magazine"),
    ("SecondStat_PulseRechargePoint_0", "Pulse Recharge"),
]
SECOND_ALIASES: Dict[str, List[str]] = {
    "SecondStat_HeadthPoint_0": ["SecondStat_HeadthPoint_0", "SecondStat_HealthPoint_0"],
    "SecondStat_FrenzyPoint_0": ["SecondStat_FrenzyPoint_0"],
    "SecondStat_SlaveMagazinePoint_0": ["SecondStat_SlaveMagazinePoint_0"],
    "SecondStat_PulseRechargePoint_0": ["SecondStat_PulseRechargePoint_0"],
}

# ------------- widget -------------

class StatsTab(QWidget):
    def __init__(self, main_window):
        super().__init__(main_window)
        self.main_window = main_window
        self._char_struct: Dict[str, Any] | None = None
        self._first_entry_by_tail: Dict[str, Dict[str, Any]] = {}
        self._first_spins_by_label: Dict[str, QSpinBox] = {}
        self._second_entry_by_name: Dict[str, Dict[str, Any]] = {}
        self._second_actual_key: Dict[str, str] = {}  # canonical -> actual key in data
        self._second_spins_by_name: Dict[str, QSpinBox] = {}
        self.setFont(QFont("Segoe UI", 10))

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(20)

        # -------- primary attributes --------
        g_attr = QGroupBox("Attributes")
        g_attr.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        f = QFormLayout()
        f.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        f.setContentsMargins(8, 8, 8, 8)
        f.setSpacing(12)
        for label, _tail in LABELS_FIRST:
            spin = QSpinBox()
            spin.setRange(0, 100)  # main stats capped at 100
            spin.valueChanged.connect(lambda v, lab=label: self._on_first_changed(lab, v))
            f.addRow(QLabel(f"{label}:").setFont(QFont("Segoe UI", 10)) or QLabel(f"{label}:"), spin)
            self._first_spins_by_label[label] = spin
        g_attr.setLayout(f)
        root.addWidget(g_attr)

        # -------- secondary stats --------
        g_sec = QGroupBox("Secondary Stats")
        g_sec.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        f2 = QFormLayout()
        f2.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        f2.setContentsMargins(8, 8, 8, 8)
        f2.setSpacing(12)
        for raw_name, nice in SECOND_CANONICAL:
            spin = QSpinBox()
            spin.setRange(0, 999999999)
            spin.valueChanged.connect(lambda v, rn=raw_name: self._on_second_direct_changed(rn, v))
            f2.addRow(QLabel(f"{nice}:").setFont(QFont("Segoe UI", 10)) or QLabel(f"{nice}:"), spin)
            self._second_spins_by_name[raw_name] = spin
        g_sec.setLayout(f2)
        root.addWidget(g_sec)

    # -------- data binding --------

    def load_data(self, data: Dict[str, Any]):
        # Character struct root
        self._char_struct = _g(
            data, "root", "properties", "CharacterSaveData_0", "Struct", "Struct", default={}
        )

        # --- First stats list ---
        self._first_entry_by_tail.clear()
        # Handle both shapes: Array->Struct->value (preferred) or Array->value (older)
        flist = _g(self._char_struct, "FirstStatSimpleList_0", "Array", "Struct", "value")
        if not isinstance(flist, list):
            flist = _g(self._char_struct, "FirstStatSimpleList_0", "Array", "value")
        if not isinstance(flist, list):
            flist = []
        # Build lookup by tail (E_VITALITY, ...)
        for node in flist:
            st = _g(node, "Struct", default={})
            enum_full = _g(st, "StatType_0", default={}).get("Enum")
            tail = _enum_tail(enum_full)
            if tail:
                self._first_entry_by_tail[tail] = st

        # Populate spinners
        for label, tail in LABELS_FIRST:
            spin = self._first_spins_by_label[label]
            spin.blockSignals(True)
            entry = self._first_entry_by_tail.get(tail)
            val = 0
            if entry:
                val = int(_g(entry, "StatData_0", default={}).get("Int", 0) or 0)
            spin.setValue(max(0, min(100, val)))
            spin.blockSignals(False)

        # --- Secondary stats --- (tolerant key search + create if missing, with proper tag)
        self._second_entry_by_name.clear()
        self._second_actual_key.clear()
        for canonical, _nice in SECOND_CANONICAL:
            found_key = None
            for k in SECOND_ALIASES.get(canonical, [canonical]):
                node = _g(self._char_struct, k, default=None)
                if isinstance(node, dict):
                    found_key = k
                    break
            if found_key is None:
                # create under the canonical name
                found_key = canonical
                node = _ensure_int_property(self._char_struct, found_key)
            else:
                # ensure tag exists
                node = _ensure_int_property(self._char_struct, found_key)
            self._second_actual_key[canonical] = found_key
            self._second_entry_by_name[canonical] = node

        for canonical, _nice in SECOND_CANONICAL:
            spin = self._second_spins_by_name[canonical]
            spin.blockSignals(True)
            val = int(self._second_entry_by_name[canonical].get("Int", 0) or 0)
            spin.setValue(max(0, min(999999999, val)))
            spin.blockSignals(False)

    # --- change handlers ---

    def _on_first_changed(self, label: str, value: int):
        if not self._char_struct:
            return
        tail = TAIL_BY_FIRST_LABEL[label]

        # Ensure the array path exists and uses the Struct-wrapper shape
        arr_node = _ensure_dict(self._char_struct, "FirstStatSimpleList_0")
        arr = _ensure_dict(arr_node, "Array")
        stwrap = _ensure_dict(arr, "Struct")
        if "value" not in stwrap or not isinstance(stwrap["value"], list):
            stwrap["value"] = []

        entry = self._first_entry_by_tail.get(tail)
        if entry is None:
            # Determine full enum form using existing namespace if available
            any_full = None
            if self._first_entry_by_tail:
                any_full = _g(next(iter(self._first_entry_by_tail.values())), "StatType_0", default={}).get("Enum")
            full_enum = _full_enum_for_tail(tail, any_full, default_ns="ELFirstStat")

            # Create with proper UE tags
            entry = {}
            _ensure_enum_property(entry, "StatType_0", full_enum_value=full_enum, enum_ns_fallback="ELFirstStat")
            _ensure_int_property(entry, "StatData_0")

            stwrap["value"].append({"Struct": entry})
            self._first_entry_by_tail[tail] = entry

        # Clamp and set
        _ensure_int_property(entry, "StatData_0")["Int"] = int(max(0, min(100, value)))

    def _on_second_direct_changed(self, canonical: str, value: int):
        if not self._char_struct:
            return
        actual_key = self._second_actual_key.get(canonical, canonical)
        node = _ensure_int_property(self._char_struct, actual_key)
        node["Int"] = int(max(0, min(999999999, value)))