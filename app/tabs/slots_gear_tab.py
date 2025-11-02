from __future__ import annotations
from typing import Any, Dict, List, Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QGridLayout, QLabel, QComboBox,
    QPushButton, QCheckBox, QMessageBox
)

JSON = Dict[str, Any]

# ---------- small helpers ----------

def _norm_code(s: Any) -> str:
    return ("" if s is None else str(s)).strip().rstrip(",").casefold()

def _format_display(code: str) -> str:
    return code.replace("_0", "").replace("_", " ").title()

def _category_for_ingame(code: str) -> str:
    if not code:
        return "Items"
    c = code.casefold()
    if c.startswith(("wp_", "weapon_", "handle_", "blade_", "grinder_", "venigni", "legionplug", "slavearm")):
        return "Weapons"
    if c.startswith(("consume_", "throw_", "grenade", "monard", "buff_", "grinder_")):
        return "Consumables"
    if c.startswith(("reinforce_", "quartz", "exchange_", "plug_", "material", "infusionstone", "venignicoin")):
        return "Materials"
    if c.startswith(("collection_", "letter_", "key_", "map_", "record_", "journal_", "note_", "lore_")):
        return "Keys/Lore"
    if c.startswith(("hatcostume_", "head_", "mask_", "costume_", "gesture_")):
        return "Cosmetics"
    return "Items"

def _items_array(root: JSON) -> List[Dict[str, Any]]:
    try:
        return root["root"]["properties"]["CharacterSaveData_0"]["Struct"]["Struct"]\
                   ["CharacterItem_0"]["Struct"]["Struct"]["PlayerItems_0"]["Array"]\
                   ["Struct"]["value"]
    except Exception:
        return []

def _ensure_name_node(st: Dict[str, Any], key: str, value: str) -> None:
    node = st.setdefault(key, {"tag": {"data": {"Other": "NameProperty"}}})
    node["Name"] = value

def _ensure_bool_node(st: Dict[str, Any], key: str, value: bool) -> None:
    node = st.setdefault(key, {"tag": {"data": {"Other": "BoolProperty"}}})
    node["Bool"] = bool(value)

def _ensure_int_node(st: Dict[str, Any], key: str, value: int) -> None:
    node = st.setdefault(key, {"tag": {"data": {"Other": "IntProperty"}}})
    node["Int"] = int(value)

# --- canonical slot list (for initialising EquipSlotSaveDatas_0 if missing) ---
CANON_EQUIP_SLOTS = [
    # Weapons / Legion
    "ELEquipSlotType::E_WEAPON_1",
    "ELEquipSlotType::E_WEAPON_2",
    "ELEquipSlotType::E_WEAPON_3",
    "ELEquipSlotType::E_SLAVEARM",
    "ELEquipSlotType::E_SLAVEARM_2",
    "ELEquipSlotType::E_SLAVEARM_3",

    # Amulets / accessories
    "ELEquipSlotType::E_GEAR_EAR_1",
    "ELEquipSlotType::E_GEAR_EAR_2",
    "ELEquipSlotType::E_GEAR_EAR_3",
    "ELEquipSlotType::E_GEAR_EAR_4",
    "ELEquipSlotType::E_GEAR_WRIST",
    "ELEquipSlotType::E_CONVERTER",
    "ELEquipSlotType::E_CARTRIDGE",

    # Outfit/frame (cosmetic)
    "ELEquipSlotType::E_BODY_COSTUME",
    "ELEquipSlotType::E_HEAD_COSTUME",
    "ELEquipSlotType::E_EYEWEAR_COSTUME",
    "ELEquipSlotType::E_FREAM",
    "ELEquipSlotType::E_LINER",
    "ELEquipSlotType::E_BAG_COSTUME",
    "ELEquipSlotType::E_BAG_COSTUME_2",
    "ELEquipSlotType::E_BAG_COSTUME_3",
]

# ---------- main tab ----------

class SlotsGearTab(QWidget):
    """
    Character-only tab for:
      • Quick-Use (UseSlots1/2) with per-item index sync,
      • Assist radial (Up/Down/Left/Right),
      • Equip Slot Locks (bUnlock flags).
    """
    def __init__(self, main_window):
        super().__init__(main_window)
        self.main_window = main_window
        self.data: Optional[JSON] = None

        # caches
        self.inv_list: List[Dict[str, Any]] = []
        self.owned_consumables: List[str] = []

        # UI refs
        self.qs_combos: List[List[QComboBox]] = [[], []]   # [line][slotIdx]
        self.qs_locks:  List[List[QCheckBox]] = [[], []]
        self.assist_combos: Dict[str, QComboBox] = {}      # Up/Down/Left/Right
        self.slot_lock_checks: Dict[str, QCheckBox] = {}
        self._locks_layout: Optional[QGridLayout] = None

        root = QVBoxLayout(self)

        # Quick-use ------------------------------------------------------------
        gb_quick = QGroupBox("Quick-Use Slots")
        gl = QGridLayout(gb_quick)
        gl.addWidget(QLabel("Line 1"), 0, 0)
        gl.addWidget(QLabel("Line 2"), 1, 0)
        for line in (0, 1):
            for idx in range(5):  # indices 0..4 observed in saves
                box = QComboBox(); box.setMinimumWidth(220)
                lock = QCheckBox("Unlocked")
                self.qs_combos[line].append(box)
                self.qs_locks[line].append(lock)
                cell = QVBoxLayout(); cellw = QWidget()
                cell.addWidget(box); cell.addWidget(lock); cellw.setLayout(cell)
                gl.addWidget(cellw, line, idx + 1)
        btns = QHBoxLayout()
        self.btn_unlock_all = QPushButton("Unlock all")
        self.btn_lock_all   = QPushButton("Lock all")
        self.btn_save_quick = QPushButton("Apply quick-use")
        self.btn_unlock_all.clicked.connect(self._unlock_all_quick_slots)
        self.btn_lock_all.clicked.connect(self._lock_all_quick_slots)
        self.btn_save_quick.clicked.connect(self._apply_quick_use_changes)
        btns.addWidget(self.btn_unlock_all); btns.addWidget(self.btn_lock_all)
        btns.addStretch(1); btns.addWidget(self.btn_save_quick)
        gl.addLayout(btns, 2, 0, 1, 6)
        root.addWidget(gb_quick)

        # Assist radial --------------------------------------------------------
        gb_assist = QGroupBox("Assist Radial")
        hl = QGridLayout(gb_assist)
        for r, key in enumerate(("Up", "Down", "Left", "Right")):
            hl.addWidget(QLabel(key), r, 0)
            cb = QComboBox(); cb.setMinimumWidth(220)
            self.assist_combos[key] = cb
            hl.addWidget(cb, r, 1)
        hb = QHBoxLayout()
        self.btn_save_assist = QPushButton("Apply assist")
        hb.addStretch(1); hb.addWidget(self.btn_save_assist)
        self.btn_save_assist.clicked.connect(self._apply_assist_changes)
        hl.addLayout(hb, 4, 0, 1, 2)
        root.addWidget(gb_assist)

        # Equip slot locks -----------------------------------------------------
        gb_locks = QGroupBox("Equip Slot Locks")
        ll = QGridLayout(gb_locks)
        self._locks_layout = ll
        self.btn_unlock_all_slots = QPushButton("Unlock all slots")
        self.btn_lock_all_slots   = QPushButton("Lock all slots")
        self.btn_apply_slot_locks = QPushButton("Apply slot locks")
        self.btn_unlock_all_slots.clicked.connect(self._unlock_all_equip_slots_ui)
        self.btn_lock_all_slots.clicked.connect(self._lock_all_equip_slots_ui)
        self.btn_apply_slot_locks.clicked.connect(self._apply_slot_locks)
        btn_row = QHBoxLayout()
        btn_row.addWidget(self.btn_unlock_all_slots)
        btn_row.addWidget(self.btn_lock_all_slots)
        btn_row.addStretch(1)
        btn_row.addWidget(self.btn_apply_slot_locks)
        ll.addLayout(btn_row, 99, 0, 1, 8)
        root.addWidget(gb_locks)

        root.addStretch(1)

    # ---------- data plumbing ----------

    def load_data(self, data: JSON) -> None:
        self.data = data

        # Ensure the structs exist so controls can enable
        self._init_use_slots_if_missing()
        self._init_assist_if_missing()
        self._init_equip_slot_saves_if_missing()

        self.inv_list = _items_array(data)

        # Owned consumables for pickers
        owned_consume: List[str] = []
        for e in self.inv_list:
            st = e.get("Struct", {})
            code = (st.get("FirstCodeName_0", {}) or {}).get("Name", "")
            if not code:
                continue
            cnt_node = st.get("Count_0", {})
            count = int(cnt_node.get("Int", cnt_node.get("Int64", 0)) or 0)
            if count > 0 and _category_for_ingame(code) == "Consumables":
                owned_consume.append(code)
        self.owned_consumables = ["None"] + sorted(set(owned_consume), key=str.casefold)

        # populate UI
        self._populate_quick_use()
        self._populate_assist_radial()
        self._populate_slot_locks()

    # ---------- create-missing initializers ----------

    def _init_use_slots_if_missing(self) -> None:
        """Ensure UseSlotData_0 → {UseSlots1_0, UseSlots2_0} exist with indices 0..4."""
        if not self.data:
            return
        try:
            root = self.data["root"]["properties"]["CharacterSaveData_0"]["Struct"]["Struct"]
        except Exception:
            return
        use = root.setdefault("UseSlotData_0", {}).setdefault("Struct", {}).setdefault("Struct", {})

        def make_line():
            arr = []
            for i in range(5):
                arr.append({
                    "Struct": {
                        "SlotIndex_0":    {"tag": {"data": {"Other": "IntProperty"}},  "Int": i},
                        "ItemCodeName_0": {"tag": {"data": {"Other": "NameProperty"}}, "Name": "None"},
                        "bUnlock_0":      {"tag": {"data": {"Other": "BoolProperty"}}, "Bool": False},
                    }
                })
            return {"Array": {"Struct": {"value": arr}}}

        if "UseSlots1_0" not in use or "Array" not in (use.get("UseSlots1_0") or {}):
            use["UseSlots1_0"] = make_line()
        if "UseSlots2_0" not in use or "Array" not in (use.get("UseSlots2_0") or {}):
            use["UseSlots2_0"] = make_line()

    def _init_assist_if_missing(self) -> None:
        """Ensure AssistUseSlot_0 → AssistUseSlots_0 has Up/Down/Left/Right entries."""
        if not self.data:
            return
        try:
            root = self.data["root"]["properties"]["CharacterSaveData_0"]["Struct"]["Struct"]
        except Exception:
            return
        blk = root.setdefault("AssistUseSlot_0", {}).setdefault("Struct", {}).setdefault("Struct", {})
        amap = blk.setdefault("AssistUseSlots_0", {}).setdefault("Map", [])

        have = { (e.get("key", {}) or {}).get("Enum", "").split("::",1)[-1] for e in amap }
        for d in ("Up", "Down", "Left", "Right"):
            if d in have:
                continue
            amap.append({
                "key":   {"Enum": f"ELAssistUseItemSlotType::{d}"},
                "value": {"Struct": {"Struct": {
                    "ItemCodeName_0": {"tag": {"data": {"Other": "NameProperty"}}, "Name": "None"}
                }}}
            })

    def _init_equip_slot_saves_if_missing(self) -> None:
        """Ensure CharacterItem_0 → EquipSlotSaveDatas_0 exists with canonical slots."""
        if not self.data:
            return
        try:
            base = self.data["root"]["properties"]["CharacterSaveData_0"]["Struct"]["Struct"]\
                          ["CharacterItem_0"]["Struct"]["Struct"]
        except Exception:
            return
        arrnode = base.setdefault("EquipSlotSaveDatas_0", {}).setdefault("Array", {}).setdefault("Struct", {})
        if "value" not in arrnode or not isinstance(arrnode.get("value"), list):
            arrnode["value"] = []
            for enum in CANON_EQUIP_SLOTS:
                arrnode["value"].append({
                    "Struct": {
                        "EquipSlotType_0": {"tag": {"data": {"Enum": ["ELEquipSlotType", None]}} , "Enum": enum},
                        "bUnlock_0": {"tag": {"data": {"Other": "BoolProperty"}}, "Bool": False},
                    }
                })

    # ---------- quick-use ----------

    def _use_slots_block(self) -> Optional[Dict[str, Any]]:
        try:
            return self.data["root"]["properties"]["CharacterSaveData_0"]["Struct"]["Struct"]["UseSlotData_0"]["Struct"]["Struct"]
        except Exception:
            return None

    def _index_maps_from_items(self) -> tuple[dict[int, str], dict[int, str]]:
        """Return (first_line_map, second_line_map) from per-item index fields."""
        first: dict[int, str] = {}
        second: dict[int, str] = {}
        for e in self.inv_list:
            st = e.get("Struct", {})
            code = (st.get("FirstCodeName_0", {}) or {}).get("Name", "")
            if not code:
                continue
            f = st.get("UseItemSlotIndexFirst_0", {})
            s = st.get("UseItemSlotIndexSecond_0", {})
            fi = int(f.get("Int", f.get("Int64", -1)) or -1) if isinstance(f, dict) else -1
            si = int(s.get("Int", s.get("Int64", -1)) or -1) if isinstance(s, dict) else -1
            if 0 <= fi <= 4:
                first.setdefault(fi, code)
            if 0 <= si <= 4:
                second.setdefault(si, code)
        return first, second

    def _populate_quick_use(self) -> None:
        block = self._use_slots_block()
        if block is None:
            QMessageBox.warning(self, "Quick-Use", "UseSlotData_0 not found in save.")
            return

        def read_line(key: str) -> List[Dict[str, Any]]:
            arr = (((block.get(key, {}) or {}).get("Array", {}) or {}).get("Struct", {}) or {}).get("value", [])
            return arr if isinstance(arr, list) else []

        line1 = read_line("UseSlots1_0")
        line2 = read_line("UseSlots2_0")
        lines = [line1, line2]

        # Are arrays effectively empty ("None" everywhere)?
        arrays_empty = True
        for slots in lines:
            for s in slots:
                st = s.get("Struct", {})
                nm = (st.get("ItemCodeName_0", {}) or {}).get("Name", "None") or "None"
                if nm != "None":
                    arrays_empty = False
                    break

        # Prefer per-item indices if arrays are empty
        idx_first, idx_second = self._index_maps_from_items()

        # fill combos/locks
        for line_idx, slots in enumerate(lines):
            for i in range(5):
                cb = self.qs_combos[line_idx][i]
                ck = self.qs_locks[line_idx][i]
                cb.clear()
                cb.addItems(self.owned_consumables)
                cb.setEnabled(False); ck.setEnabled(False)
                # find slot by SlotIndex_0 == i
                sdict = None
                for s in slots:
                    st = s.get("Struct", {})
                    if int((st.get("SlotIndex_0", {}) or {}).get("Int", -1)) == i:
                        sdict = st; break
                if sdict:
                    item = (sdict.get("ItemCodeName_0", {}) or {}).get("Name", "None") or "None"
                    unlock = bool((sdict.get("bUnlock_0", {}) or {}).get("Bool", False))
                    if arrays_empty:
                        mapped = (idx_first if line_idx == 0 else idx_second).get(i, "None")
                        if mapped != "None":
                            item = mapped
                            unlock = True
                    cb.setCurrentText(item if item in self.owned_consumables else "None")
                    ck.setChecked(unlock)
                    cb.setEnabled(True); ck.setEnabled(True)

    def _unlock_all_quick_slots(self) -> None:
        block = self._use_slots_block()
        if block is None: return
        for key in ("UseSlots1_0", "UseSlots2_0"):
            slots = (((block.get(key, {}) or {}).get("Array", {}) or {}).get("Struct", {}) or {}).get("value", [])
            for s in slots:
                st = s.get("Struct", {})
                _ensure_bool_node(st, "bUnlock_0", True)
        self._populate_quick_use()

    def _lock_all_quick_slots(self) -> None:
        block = self._use_slots_block()
        if block is None: return
        for key in ("UseSlots1_0", "UseSlots2_0"):
            slots = (((block.get(key, {}) or {}).get("Array", {}) or {}).get("Struct", {}) or {}).get("value", [])
            for s in slots:
                st = s.get("Struct", {})
                _ensure_bool_node(st, "bUnlock_0", False)
        self._populate_quick_use()

    def _set_item_index_for_line(self, line: int, idx: int, code: str) -> None:
        """
        line: 1 or 2, idx: 0..4, code: item id (or 'None').
        Sets UseItemSlotIndex{First|Second}_0 on the chosen item; clears others claiming that slot.
        """
        field = "UseItemSlotIndexFirst_0" if line == 1 else "UseItemSlotIndexSecond_0"
        # clear anyone currently pointing at this idx
        for e in self.inv_list:
            st = e.get("Struct", {})
            node = st.get(field)
            if isinstance(node, dict):
                cur = int(node.get("Int", node.get("Int64", -1)) or -1)
                if cur == idx:
                    _ensure_int_node(st, field, -1)
        # set the chosen item
        if code and code != "None":
            for e in self.inv_list:
                st = e.get("Struct", {})
                c = (st.get("FirstCodeName_0", {}) or {}).get("Name", "")
                if c == code:
                    _ensure_int_node(st, field, idx)
                    break

    def _apply_quick_use_changes(self) -> None:
        block = self._use_slots_block()
        if block is None:
            return

        # 1) Write arrays from UI
        for key, line_idx in (("UseSlots1_0", 0), ("UseSlots2_0", 1)):
            slots = (((block.get(key, {}) or {}).get("Array", {}) or {}).get("Struct", {}) or {}).get("value", [])
            for s in slots:
                st = s.get("Struct", {})
                idx = int((st.get("SlotIndex_0", {}) or {}).get("Int", -1))
                if 0 <= idx < 5:
                    chosen = self.qs_combos[line_idx][idx].currentText() or "None"
                    unlocked = self.qs_locks[line_idx][idx].isChecked()
                    _ensure_name_node(st, "ItemCodeName_0", chosen)
                    _ensure_bool_node(st, "bUnlock_0", unlocked)

        # 2) Sync per-item indices to match UI selections (character chunk only)
        for i in range(5):
            self._set_item_index_for_line(1, i, self.qs_combos[0][i].currentText() or "None")
            self._set_item_index_for_line(2, i, self.qs_combos[1][i].currentText() or "None")

        QMessageBox.information(self, "Quick-Use", "Quick-use changes applied.")

    # ---------- assist radial ----------

    def _assist_block(self) -> Optional[Dict[str, Any]]:
        try:
            return self.data["root"]["properties"]["CharacterSaveData_0"]["Struct"]["Struct"]["AssistUseSlot_0"]["Struct"]["Struct"]
        except Exception:
            return None

    def _populate_assist_radial(self) -> None:
        blk = self._assist_block()
        for key in self.assist_combos.values():
            key.clear()
            key.addItems(self.owned_consumables)
            key.setCurrentText("None")
            key.setEnabled(False)
        if blk is None:
            return
        amap = (blk.get("AssistUseSlots_0", {}) or {}).get("Map", [])
        for entry in amap or []:
            k = (entry.get("key", {}) or {}).get("Enum", "")
            vst = (((entry.get("value", {}) or {}).get("Struct", {}) or {}).get("Struct", {}) or {})
            item = (vst.get("ItemCodeName_0", {}) or {}).get("Name", "None") or "None"
            if k.endswith("::Up") and "Up" in self.assist_combos:
                self.assist_combos["Up"].setEnabled(True)
                self.assist_combos["Up"].setCurrentText(item if item in self.owned_consumables else "None")
            elif k.endswith("::Down") and "Down" in self.assist_combos:
                self.assist_combos["Down"].setEnabled(True)
                self.assist_combos["Down"].setCurrentText(item if item in self.owned_consumables else "None")
            elif k.endswith("::Left") and "Left" in self.assist_combos:
                self.assist_combos["Left"].setEnabled(True)
                self.assist_combos["Left"].setCurrentText(item if item in self.owned_consumables else "None")
            elif k.endswith("::Right") and "Right" in self.assist_combos:
                self.assist_combos["Right"].setEnabled(True)
                self.assist_combos["Right"].setCurrentText(item if item in self.owned_consumables else "None")

    def _apply_assist_changes(self) -> None:
        blk = self._assist_block()
        if blk is None:
            return
        amap = blk.setdefault("AssistUseSlots_0", {}).setdefault("Map", [])
        # build index by direction
        idx_by_dir: Dict[str, int] = {}
        for i, entry in enumerate(amap):
            k = (entry.get("key", {}) or {}).get("Enum", "")
            if k.endswith("::Up"): idx_by_dir["Up"] = i
            elif k.endswith("::Down"): idx_by_dir["Down"] = i
            elif k.endswith("::Left"): idx_by_dir["Left"] = i
            elif k.endswith("::Right"): idx_by_dir["Right"] = i
        for d in ("Up", "Down", "Left", "Right"):
            if d not in self.assist_combos or d not in idx_by_dir:
                continue
            i = idx_by_dir[d]
            vst = (((amap[i].setdefault("value", {}).setdefault("Struct", {}).setdefault("Struct", {}))))
            _ensure_name_node(vst, "ItemCodeName_0", self.assist_combos[d].currentText() or "None")
        QMessageBox.information(self, "Assist", "Assist radial updated.")

    # ---------- equip slot locks ----------

    def _equip_slot_saves(self) -> List[Dict[str, Any]]:
        try:
            return self.data["root"]["properties"]["CharacterSaveData_0"]["Struct"]["Struct"]\
                       ["CharacterItem_0"]["Struct"]["Struct"]["EquipSlotSaveDatas_0"]\
                       ["Array"]["Struct"]["value"]
        except Exception:
            return []

    def _populate_slot_locks(self) -> None:
        # clear prior checkboxes from grid (keep the button row at 99)
        ll = self._locks_layout
        if ll is None:
            return
        for i in reversed(range(ll.count())):
            item = ll.itemAt(i)
            w = item.widget()
            if isinstance(w, QCheckBox):
                ll.removeWidget(w)
                w.deleteLater()
        self.slot_lock_checks.clear()

        arr = self._equip_slot_saves()
        if not arr:
            return

        # Build rows of checkboxes, 4 per row for readability
        col = 0; row = 0
        for entry in arr:
            st = entry.get("Struct", {})
            enum = (st.get("EquipSlotType_0", {}) or {}).get("Enum", "ELEquipSlotType::E_NONE")
            tail = enum.split("::", 1)[-1]
            unlocked = bool((st.get("bUnlock_0", {}) or {}).get("Bool", False))
            cb = QCheckBox(tail.replace("E_", ""))
            cb.setChecked(unlocked)
            self.slot_lock_checks[enum] = cb
            ll.addWidget(cb, row, col)
            col += 1
            if col >= 4:
                col = 0; row += 1

    def _unlock_all_equip_slots_ui(self) -> None:
        for cb in self.slot_lock_checks.values():
            cb.setChecked(True)

    def _lock_all_equip_slots_ui(self) -> None:
        for cb in self.slot_lock_checks.values():
            cb.setChecked(False)

    def _apply_slot_locks(self) -> None:
        arr = self._equip_slot_saves()
        if not arr:
            return
        changed = 0
        for entry in arr:
            st = entry.get("Struct", {})
            enum = (st.get("EquipSlotType_0", {}) or {}).get("Enum", "ELEquipSlotType::E_NONE")
            if enum in self.slot_lock_checks:
                want = self.slot_lock_checks[enum].isChecked()
                b = st.setdefault("bUnlock_0", {"tag": {"data": {"Other": "BoolProperty"}}, "Bool": False})
                if bool(b.get("Bool", False)) != want:
                    b["Bool"] = bool(want)
                    changed += 1
        QMessageBox.information(self, "Equip Slots", f"Applied slot locks. Changed {changed} entr{'y' if changed==1 else 'ies'}.")
