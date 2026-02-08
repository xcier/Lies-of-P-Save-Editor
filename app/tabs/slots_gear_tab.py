from __future__ import annotations
from typing import Any, Dict, List, Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGroupBox,
    QGridLayout,
    QLabel,
    QComboBox,
    QPushButton,
    QCheckBox,
    QMessageBox,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
)

JSON = Dict[str, Any]

# ---------- small helpers ----------


def _norm_code(s: Any) -> str:
    return ("" if s is None else str(s)).strip().rstrip(",").casefold()


def _category_for_ingame(code: str) -> str:
    if not code:
        return "Items"
    c = code.casefold()
    if c.startswith(
        (
            "wp_",
            "weapon_",
            "handle_",
            "blade_",
            "grinder_",
            "venigni",
            "legionplug",
            "slavearm",
        )
    ):
        return "Weapons"
    if c.startswith(
        (
            "consume_",
            "throw_",
            "grenade",
            "monard",
            "buff_",
            "grinder_",
        )
    ):
        return "Consumables"
    if c.startswith(
        (
            "reinforce_",
            "quartz",
            "exchange_",
            "plug_",
            "material",
            "infusionstone",
            "venignicoin",
        )
    ):
        return "Materials"
    if c.startswith(
        (
            "collection_",
            "letter_",
            "key_",
            "map_",
            "record_",
            "journal_",
            "note_",
            "lore_",
        )
    ):
        return "Keys/Lore"
    if c.startswith(
        (
            "hatcostume_",
            "head_",
            "mask_",
            "costume_",
            "gesture_",
        )
    ):
        return "Cosmetics"
    return "Items"


def _items_array(root: JSON) -> List[Dict[str, Any]]:
    try:
        return (
            root["root"]["properties"]["CharacterSaveData_0"]["Struct"]["Struct"][
                "CharacterItem_0"
            ]["Struct"]["Struct"]["PlayerItems_0"]["Array"]["Struct"]["value"]
        )
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

    Layout is grouped into card-like sections so QSS can style them in a
    modern way. Behaviour is unchanged from the previous version.
    """

    def __init__(self, main_window):
        super().__init__(main_window)
        self.main_window = main_window
        self.data: Optional[JSON] = None

        # caches
        self.inv_list: List[Dict[str, Any]] = []
        self.owned_consumables: List[str] = []

        # UI refs
        self.qs_combos: List[List[QComboBox]] = [[], []]  # [line][slotIdx]
        self.qs_locks: List[List[QCheckBox]] = [[], []]
        self.assist_combos: Dict[str, QComboBox] = {}  # Up/Down/Left/Right
        self.slot_lock_checks: Dict[str, QCheckBox] = {}
        self._locks_layout: Optional[QGridLayout] = None

        # Equipped Overview UI
        self.tbl_equipped: Optional[QTableWidget] = None
        # row -> list of wrapped equipped refs: {"entry": <dict>, "source": "Inventory"|"Weapons"}
        self._equipped_row_ref: Dict[int, List[Dict[str, Any]]] = {}

        # ---------- layout skeleton ----------
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        hdr = QLabel("Manage consumable quick slots, assist wheel, and equip slot locks.")
        hdr.setObjectName("SlotsHeaderLabel")
        hdr.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        root.addWidget(hdr)

        # --- Equipped Overview ----------------------------------------------
        gb_eq = QGroupBox("Equipped Overview")
        gb_eq.setObjectName("CardEquippedOverview")
        gb_eq.setFlat(True)
        ev = QVBoxLayout(gb_eq)
        ev.setContentsMargins(10, 8, 10, 8)
        ev.setSpacing(6)

        self.tbl_equipped = QTableWidget(0, 5, self)
        self.tbl_equipped.setObjectName("EquippedOverviewTable")
        self.tbl_equipped.setAlternatingRowColors(True)
        self.tbl_equipped.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.tbl_equipped.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        # Actions column intentionally kept minimal (Unequip only).
        self.tbl_equipped.setHorizontalHeaderLabels(["Slot", "Equipped", "Code", "Source", "Actions"])
        eh = self.tbl_equipped.horizontalHeader()
        eh.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        eh.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        eh.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        eh.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        eh.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        try:
            self.tbl_equipped.verticalHeader().setVisible(False)
        except Exception:
            pass
        self.tbl_equipped.setMinimumHeight(160)
        ev.addWidget(self.tbl_equipped)
        root.addWidget(gb_eq)

        # --- Quick-use --------------------------------------------------------
        gb_quick = QGroupBox("Quick Slots")
        gb_quick.setObjectName("CardQuickSlots")
        gb_quick.setFlat(True)
        gl = QGridLayout(gb_quick)
        gl.setContentsMargins(10, 8, 10, 8)
        gl.setHorizontalSpacing(10)
        gl.setVerticalSpacing(6)

        # Column headers
        gl.addWidget(QLabel("Line"), 0, 0, alignment=Qt.AlignmentFlag.AlignLeft)
        for idx in range(5):
            lbl = QLabel(f"Slot {idx + 1}")
            lbl.setObjectName("QuickSlotHeaderLabel")
            lbl.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter)
            gl.addWidget(lbl, 0, idx + 1)

        # Lines 1 & 2
        for line in (0, 1):
            line_label = QLabel(f"Line {line + 1}")
            line_label.setObjectName("QuickLineLabel")
            gl.addWidget(line_label, line + 1, 0, alignment=Qt.AlignmentFlag.AlignVCenter)

            for idx in range(5):  # indices 0..4 observed in saves
                box = QComboBox()
                box.setMinimumWidth(190)
                box.setObjectName("QuickSlotCombo")

                # For clarity: checked = Unlocked
                lock = QCheckBox("Unlocked")
                lock.setObjectName("QuickSlotUnlockCheck")
                lock.setToolTip("Checked = slot unlocked")

                self.qs_combos[line].append(box)
                self.qs_locks[line].append(lock)

                cell = QVBoxLayout()
                cell.setContentsMargins(0, 0, 0, 0)
                cell.setSpacing(2)
                cellw = QWidget()
                cell.addWidget(box)
                cell.addWidget(lock, alignment=Qt.AlignmentFlag.AlignRight)
                cellw.setLayout(cell)
                gl.addWidget(cellw, line + 1, idx + 1)

        # Quick-use buttons row
        btns = QHBoxLayout()
        btns.setContentsMargins(0, 4, 0, 0)
        self.btn_unlock_all = QPushButton("Unlock all")
        self.btn_unlock_all.setObjectName("QuickUnlockAllButton")
        self.btn_lock_all = QPushButton("Lock all")
        self.btn_lock_all.setObjectName("QuickLockAllButton")
        self.btn_save_quick = QPushButton("Apply quick slots")
        self.btn_save_quick.setObjectName("QuickApplyButton")
        self.btn_unlock_all.clicked.connect(self._unlock_all_quick_slots)
        self.btn_lock_all.clicked.connect(self._lock_all_quick_slots)
        self.btn_save_quick.clicked.connect(self._apply_quick_use_changes)
        btns.addWidget(self.btn_unlock_all)
        btns.addWidget(self.btn_lock_all)
        btns.addStretch(1)
        btns.addWidget(self.btn_save_quick)
        gl.addLayout(btns, 3, 0, 1, 6)

        root.addWidget(gb_quick)

        # --- Assist radial ----------------------------------------------------
        gb_assist = QGroupBox("Assist Wheel")
        gb_assist.setObjectName("CardAssistWheel")
        gb_assist.setFlat(True)
        hl = QGridLayout(gb_assist)
        hl.setContentsMargins(10, 8, 10, 8)
        hl.setHorizontalSpacing(12)
        hl.setVerticalSpacing(4)

        for r, key in enumerate(("Up", "Down", "Left", "Right")):
            lab = QLabel(key)
            lab.setObjectName("AssistDirectionLabel")
            hl.addWidget(lab, r, 0)
            cb = QComboBox()
            cb.setMinimumWidth(220)
            cb.setObjectName("AssistCombo")
            self.assist_combos[key] = cb
            hl.addWidget(cb, r, 1)

        hb = QHBoxLayout()
        self.btn_save_assist = QPushButton("Apply assist wheel")
        self.btn_save_assist.setObjectName("AssistApplyButton")
        hb.addStretch(1)
        hb.addWidget(self.btn_save_assist)
        self.btn_save_assist.clicked.connect(self._apply_assist_changes)
        hl.addLayout(hb, 4, 0, 1, 2)

        root.addWidget(gb_assist)

        # --- Equip slot locks -------------------------------------------------
        gb_locks = QGroupBox("Equip Slot Locks")
        gb_locks.setObjectName("CardEquipLocks")
        gb_locks.setFlat(True)
        ll = QGridLayout(gb_locks)
        ll.setContentsMargins(10, 8, 10, 8)
        ll.setHorizontalSpacing(14)
        ll.setVerticalSpacing(4)
        self._locks_layout = ll

        self.btn_unlock_all_slots = QPushButton("Unlock all slots")
        self.btn_unlock_all_slots.setObjectName("EquipUnlockAllButton")
        self.btn_lock_all_slots = QPushButton("Lock all slots")
        self.btn_lock_all_slots.setObjectName("EquipLockAllButton")
        self.btn_apply_slot_locks = QPushButton("Apply slot locks")
        self.btn_apply_slot_locks.setObjectName("EquipApplyButton")
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
        self._populate_equipped_overview()
        self._populate_quick_use()
        self._populate_assist_radial()
        self._populate_slot_locks()

    # ---------- Equipped Overview ----------

    @staticmethod
    def _slot_value_from_struct(st: Dict[str, Any]) -> str:
        """Find the first ELEquipSlotType enum in a struct."""
        for v in (st or {}).values():
            if isinstance(v, dict) and isinstance(v.get("Enum"), str) and v["Enum"].startswith("ELEquipSlotType::"):
                return v["Enum"]
        return "ELEquipSlotType::E_NONE"

    @staticmethod
    def _set_slot_enum(st: Dict[str, Any], new_enum: str) -> None:
        if not isinstance(new_enum, str) or not new_enum.startswith("ELEquipSlotType::"):
            return
        key = None
        for k, v in (st or {}).items():
            if isinstance(v, dict) and isinstance(v.get("Enum"), str) and v["Enum"].startswith("ELEquipSlotType::"):
                key = k
                break
        if key is None:
            key = "EquipItemSlotType_0"
            st[key] = {"tag": {"data": {"Enum": ["ELEquipSlotType", None]}}, "Enum": "ELEquipSlotType::E_NONE"}
        st[key]["Enum"] = new_enum
        st[key]["tag"] = {"data": {"Enum": ["ELEquipSlotType", None]}}

    def _label_for_item_code(self, code: str) -> str:
        code = (code or "").strip()
        if not code or code.lower() == "none":
            return "None"
        try:
            name = (getattr(self.main_window, "inventory_tab", None) and self.main_window.inventory_tab.names.get(code))
        except Exception:
            name = None
        if name:
            return str(name).strip().rstrip(",")
        return code

    def _gather_equipped(self) -> Dict[str, List[Dict[str, Any]]]:
        """Return slot_enum -> list of wrapped refs: {entry, source}."""
        out: Dict[str, List[Dict[str, Any]]] = {}

        def add(entry: Dict[str, Any], source: str) -> None:
            st = entry.get("Struct", {}) if isinstance(entry, dict) else {}
            slot = self._slot_value_from_struct(st)
            if not isinstance(slot, str) or slot.endswith("E_NONE"):
                return
            out.setdefault(slot, []).append({"entry": entry, "source": source})

        for e in (self.inv_list or []):
            add(e, "Inventory")

        # weapon builds (if present)
        try:
            build_rows = getattr(getattr(self.main_window, "build_tab", None), "build_rows", [])
            for e in (build_rows or []):
                add(e, "Weapons")
        except Exception:
            pass

        return out

    def _populate_equipped_overview(self) -> None:
        if not self.tbl_equipped:
            return

        eq = self._gather_equipped()

        # show canonical slots first, then any extras discovered
        ordered = list(CANON_EQUIP_SLOTS)
        for k in sorted(eq.keys(), key=str.casefold):
            if k not in ordered:
                ordered.append(k)

        self.tbl_equipped.setRowCount(0)
        self._equipped_row_ref.clear()

        def _desc_for_entry(w: Dict[str, Any]) -> tuple[str, str]:
            e = w.get("entry") or {}
            st = e.get("Struct", {})
            h = (st.get("FirstCodeName_0") or {}).get("Name", "")
            b = (st.get("SecondCodeName_0") or {}).get("Name", "")
            if h and b and h.startswith("WP_") and b.startswith("WP_"):
                return f"{h} / {b}", f"{h} + {b}"
            code = (st.get("FirstCodeName_0") or {}).get("Name", "")
            return self._label_for_item_code(code), code or ""

        row = 0
        for slot in ordered:
            entries = eq.get(slot, [])
            if not entries:
                self.tbl_equipped.insertRow(row)
                self.tbl_equipped.setItem(row, 0, QTableWidgetItem(slot))
                self.tbl_equipped.setItem(row, 1, QTableWidgetItem("Empty"))
                self.tbl_equipped.setItem(row, 2, QTableWidgetItem(""))
                self.tbl_equipped.setItem(row, 3, QTableWidgetItem(""))
                self.tbl_equipped.setItem(row, 4, QTableWidgetItem(""))
                row += 1
                continue

            primary = entries[0]
            label, code = _desc_for_entry(primary)
            src = str(primary.get("source", ""))
            if len(entries) > 1:
                label = f"{label}  (⚠ {len(entries)} items)"

            self.tbl_equipped.insertRow(row)
            self.tbl_equipped.setItem(row, 0, QTableWidgetItem(slot))
            self.tbl_equipped.setItem(row, 1, QTableWidgetItem(label))
            self.tbl_equipped.setItem(row, 2, QTableWidgetItem(code))
            self.tbl_equipped.setItem(row, 3, QTableWidgetItem(src))

            actions = QWidget(self.tbl_equipped)
            ah = QHBoxLayout(actions)
            ah.setContentsMargins(0, 0, 0, 0)
            ah.setSpacing(6)
            btn_unequip = QPushButton("Unequip")
            btn_unequip.setObjectName("MiniButton")

            def _do(_checked: bool = False, _slot=slot):
                self._unequip_slot(_slot)

            btn_unequip.clicked.connect(_do)
            ah.addWidget(btn_unequip)
            ah.addStretch(1)
            self.tbl_equipped.setCellWidget(row, 4, actions)

            self._equipped_row_ref[row] = entries
            row += 1

        try:
            self.tbl_equipped.resizeRowsToContents()
        except Exception:
            pass

    def _unequip_slot(self, slot_enum: str) -> None:
        slot_enum = (slot_enum or "").strip()
        if not slot_enum.startswith("ELEquipSlotType::"):
            return
        eq = self._gather_equipped().get(slot_enum, [])
        if not eq:
            return
        for w in eq:
            e = w.get("entry") or {}
            st = e.get("Struct", {})
            self._set_slot_enum(st, "ELEquipSlotType::E_NONE")
        self._populate_equipped_overview()
        try:
            self.main_window.inventory_tab._build_equipped_table()
        except Exception:
            pass

    # ---------- create-missing initializers ----------

    def _init_use_slots_if_missing(self) -> None:
        """Ensure UseSlotData_0 → {UseSlots1_0, UseSlots2_0} exist with indices 0..4."""
        if not self.data:
            return
        try:
            root = self.data["root"]["properties"]["CharacterSaveData_0"]["Struct"]["Struct"]
        except Exception:
            return
        use = (
            root.setdefault("UseSlotData_0", {})
            .setdefault("Struct", {})
            .setdefault("Struct", {})
        )

        def make_line():
            arr = []
            for i in range(5):
                arr.append(
                    {
                        "Struct": {
                            "SlotIndex_0": {
                                "tag": {"data": {"Other": "IntProperty"}},
                                "Int": i,
                            },
                            "ItemCodeName_0": {
                                "tag": {"data": {"Other": "NameProperty"}},
                                "Name": "None",
                            },
                            "bUnlock_0": {
                                "tag": {"data": {"Other": "BoolProperty"}},
                                "Bool": False,
                            },
                        }
                    }
                )
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
        blk = (
            root.setdefault("AssistUseSlot_0", {})
            .setdefault("Struct", {})
            .setdefault("Struct", {})
        )
        amap = blk.setdefault("AssistUseSlots_0", {}).setdefault("Map", [])

        have = {(e.get("key", {}) or {}).get("Enum", "").split("::", 1)[-1] for e in amap}
        for d in ("Up", "Down", "Left", "Right"):
            if d in have:
                continue
            amap.append(
                {
                    "key": {"Enum": f"ELAssistUseItemSlotType::{d}"},
                    "value": {
                        "Struct": {
                            "Struct": {
                                "ItemCodeName_0": {
                                    "tag": {"data": {"Other": "NameProperty"}},
                                    "Name": "None",
                                }
                            }
                        }
                    },
                }
            )

    def _init_equip_slot_saves_if_missing(self) -> None:
        """Ensure CharacterItem_0 → EquipSlotSaveDatas_0 exists with canonical slots."""
        if not self.data:
            return
        try:
            base = (
                self.data["root"]["properties"]["CharacterSaveData_0"]["Struct"]["Struct"][
                    "CharacterItem_0"
                ]["Struct"]["Struct"]
            )
        except Exception:
            return
        arrnode = (
            base.setdefault("EquipSlotSaveDatas_0", {})
            .setdefault("Array", {})
            .setdefault("Struct", {})
        )
        if "value" not in arrnode or not isinstance(arrnode.get("value"), list):
            arrnode["value"] = []
            for enum in CANON_EQUIP_SLOTS:
                arrnode["value"].append(
                    {
                        "Struct": {
                            "EquipSlotType_0": {
                                "tag": {"data": {"Enum": ["ELEquipSlotType", None]}},
                                "Enum": enum,
                            },
                            "bUnlock_0": {
                                "tag": {"data": {"Other": "BoolProperty"}},
                                "Bool": False,
                            },
                        }
                    }
                )

    # ---------- quick-use ----------

    def _use_slots_block(self) -> Optional[Dict[str, Any]]:
        try:
            return (
                self.data["root"]["properties"]["CharacterSaveData_0"]["Struct"]["Struct"][
                    "UseSlotData_0"
                ]["Struct"]["Struct"]
            )
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
            QMessageBox.warning(self, "Quick Slots", "UseSlotData_0 not found in save.")
            return

        def read_line(key: str) -> List[Dict[str, Any]]:
            arr = (
                (((block.get(key, {}) or {}).get("Array", {}) or {}).get("Struct", {}) or {}).get(
                    "value", []
                )
            )
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
                cb.setEnabled(False)
                ck.setEnabled(False)
                # find slot by SlotIndex_0 == i
                sdict = None
                for s in slots:
                    st = s.get("Struct", {})
                    if int((st.get("SlotIndex_0", {}) or {}).get("Int", -1)) == i:
                        sdict = st
                        break
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
                    cb.setEnabled(True)
                    ck.setEnabled(True)

    def _unlock_all_quick_slots(self) -> None:
        block = self._use_slots_block()
        if block is None:
            return
        for key in ("UseSlots1_0", "UseSlots2_0"):
            slots = (
                (((block.get(key, {}) or {}).get("Array", {}) or {}).get("Struct", {}) or {}).get(
                    "value", []
                )
            )
            for s in slots:
                st = s.get("Struct", {})
                _ensure_bool_node(st, "bUnlock_0", True)
        self._populate_quick_use()

    def _lock_all_quick_slots(self) -> None:
        block = self._use_slots_block()
        if block is None:
            return
        for key in ("UseSlots1_0", "UseSlots2_0"):
            slots = (
                (((block.get(key, {}) or {}).get("Array", {}) or {}).get("Struct", {}) or {}).get(
                    "value", []
                )
            )
            for s in slots:
                st = s.get("Struct", {})
                _ensure_bool_node(st, "bUnlock_0", False)
        self._populate_quick_use()

    def _set_item_index_for_line(self, line: int, idx: int, code: str) -> None:
        """
        line: 1 or 2, idx: 0..4, code: item id (or 'None').

        Sets UseItemSlotIndex{First|Second}_0 on the chosen item; clears others
        claiming that slot.
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
            slots = (
                (((block.get(key, {}) or {}).get("Array", {}) or {}).get("Struct", {}) or {}).get(
                    "value", []
                )
            )
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
            self._set_item_index_for_line(
                1, i, self.qs_combos[0][i].currentText() or "None"
            )
            self._set_item_index_for_line(
                2, i, self.qs_combos[1][i].currentText() or "None"
            )

        QMessageBox.information(self, "Quick Slots", "Quick slot changes applied.")

    # ---------- assist radial ----------

    def _assist_block(self) -> Optional[Dict[str, Any]]:
        try:
            return (
                self.data["root"]["properties"]["CharacterSaveData_0"]["Struct"]["Struct"][
                    "AssistUseSlot_0"
                ]["Struct"]["Struct"]
            )
        except Exception:
            return None

    def _populate_assist_radial(self) -> None:
        blk = self._assist_block()
        for combo in self.assist_combos.values():
            combo.clear()
            combo.addItems(self.owned_consumables)
            combo.setCurrentText("None")
            combo.setEnabled(False)
        if blk is None:
            return
        amap = (blk.get("AssistUseSlots_0", {}) or {}).get("Map", [])
        for entry in amap or []:
            k = (entry.get("key", {}) or {}).get("Enum", "")
            vst = (
                ((entry.get("value", {}) or {}).get("Struct", {}) or {}).get(
                    "Struct", {}
                )
                or {}
            )
            item = (vst.get("ItemCodeName_0", {}) or {}).get("Name", "None") or "None"
            target = None
            if k.endswith("::Up"):
                target = "Up"
            elif k.endswith("::Down"):
                target = "Down"
            elif k.endswith("::Left"):
                target = "Left"
            elif k.endswith("::Right"):
                target = "Right"
            if target and target in self.assist_combos:
                cb = self.assist_combos[target]
                cb.setEnabled(True)
                cb.setCurrentText(item if item in self.owned_consumables else "None")

    def _apply_assist_changes(self) -> None:
        blk = self._assist_block()
        if blk is None:
            return
        amap = blk.setdefault("AssistUseSlots_0", {}).setdefault("Map", [])
        # build index by direction
        idx_by_dir: Dict[str, int] = {}
        for i, entry in enumerate(amap):
            k = (entry.get("key", {}) or {}).get("Enum", "")
            if k.endswith("::Up"):
                idx_by_dir["Up"] = i
            elif k.endswith("::Down"):
                idx_by_dir["Down"] = i
            elif k.endswith("::Left"):
                idx_by_dir["Left"] = i
            elif k.endswith("::Right"):
                idx_by_dir["Right"] = i
        for d in ("Up", "Down", "Left", "Right"):
            if d not in self.assist_combos or d not in idx_by_dir:
                continue
            i = idx_by_dir[d]
            vst = (
                amap[i]
                .setdefault("value", {})
                .setdefault("Struct", {})
                .setdefault("Struct", {})
            )
            _ensure_name_node(
                vst, "ItemCodeName_0", self.assist_combos[d].currentText() or "None"
            )
        QMessageBox.information(self, "Assist Wheel", "Assist wheel updated.")

    # ---------- equip slot locks ----------

    def _equip_slot_saves(self) -> List[Dict[str, Any]]:
        try:
            return (
                self.data["root"]["properties"]["CharacterSaveData_0"]["Struct"]["Struct"][
                    "CharacterItem_0"
                ]["Struct"]["Struct"]["EquipSlotSaveDatas_0"]["Array"]["Struct"]["value"]
            )
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
        col = 0
        row = 0
        for entry in arr:
            st = entry.get("Struct", {})
            enum = (st.get("EquipSlotType_0", {}) or {}).get(
                "Enum", "ELEquipSlotType::E_NONE"
            )
            tail = enum.split("::", 1)[-1]
            unlocked = bool((st.get("bUnlock_0", {}) or {}).get("Bool", False))
            cb = QCheckBox(tail.replace("E_", ""))
            cb.setObjectName("EquipLockCheck")
            cb.setChecked(unlocked)
            self.slot_lock_checks[enum] = cb
            ll.addWidget(cb, row, col)
            col += 1
            if col >= 4:
                col = 0
                row += 1

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
            enum = (st.get("EquipSlotType_0", {}) or {}).get(
                "Enum", "ELEquipSlotType::E_NONE"
            )
            if enum in self.slot_lock_checks:
                want = self.slot_lock_checks[enum].isChecked()
                b = st.setdefault(
                    "bUnlock_0",
                    {"tag": {"data": {"Other": "BoolProperty"}}, "Bool": False},
                )
                if bool(b.get("Bool", False)) != want:
                    b["Bool"] = bool(want)
                    changed += 1
        QMessageBox.information(
            self,
            "Equip Slots",
            f"Applied slot locks. Changed {changed} entr"
            f"{'y' if changed == 1 else 'ies'}.",
        )
