# app/tabs/builds_tab.py
from __future__ import annotations
from typing import Any, Dict, List, Optional
import copy
import random

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QIntValidator
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem, QHeaderView,
    QGroupBox, QFormLayout, QLineEdit, QComboBox, QPushButton, QCheckBox, QMessageBox
)

JSON = Dict[str, Any]

# ---------- tiny helpers ----------
def _items_array(root: JSON) -> List[Dict[str, Any]]:
    try:
        return root["root"]["properties"]["CharacterSaveData_0"]["Struct"]["Struct"] \
                   ["CharacterItem_0"]["Struct"]["Struct"]["PlayerItems_0"]["Array"] \
                   ["Struct"]["value"]
    except Exception:
        return []

def _ensure_name(st: Dict[str, Any], key: str, value: str) -> None:
    node = st.setdefault(key, {"tag": {"data": {"Other": "NameProperty"}}})
    node["Name"] = value

def _ensure_enum(st: Dict[str, Any], key: str, etype: str, value: str) -> None:
    node = st.setdefault(key, {"tag": {"data": {"Enum": [etype, None]}}})
    node["Enum"] = value

def _ensure_int(st: Dict[str, Any], key: str, value: int) -> None:
    node = st.setdefault(key, {"tag": {"data": {"Other": "IntProperty"}}})
    node["Int"] = int(value)

def _ensure_int64(st: Dict[str, Any], key: str, value: int) -> None:
    node = st.setdefault(key, {"tag": {"data": {"Other": "Int64Property"}}})
    node["Int64"] = int(value)

def _get_int(st: Dict[str, Any], key: str, default: int = 0) -> int:
    node = st.get(key, {})
    if "Int64" in node:
        try: return int(node.get("Int64") or 0)
        except Exception: return default
    if "Int" in node:
        try: return int(node.get("Int") or 0)
        except Exception: return default
    return default

def _read_name(st: Dict[str, Any], key: str) -> str:
    return (st.get(key, {}) or {}).get("Name", "") or ""

def _read_enum(st: Dict[str, Any], key: str) -> str:
    return (st.get(key, {}) or {}).get("Enum", "") or ""

def _fmt(code: str) -> str:
    return code.replace("_0", "").replace("_", " ").title()

def _none_like(s: str) -> bool:
    return s.strip().lower() in ("", "none", "null")

def _looks_like_weapon_build(st: Dict[str, Any]) -> bool:
    """Strict weapon-only filter: has real WP_PC_HND_* and WP_PC_BLD_*."""
    h = _read_name(st, "FirstCodeName_0")
    b = _read_name(st, "SecondCodeName_0")
    if _none_like(h) or _none_like(b):
        return False
    return h.startswith("WP_PC_HND_") and b.startswith("WP_PC_BLD_")

# ---------- main tab ----------
class BuildsTab(QWidget):
    """
    Weapon build editor (handle + blade + slot + sharpness + unique id).
    - Table shows **weapons only** (WP_PC_HND_* + WP_PC_BLD_*).
    - Click anywhere (incl. Display) to load row into editor.
    - Inline editing for Handle/Blade/Slot via table comboboxes.
    - Bottom editor for sharpness/id and precise text edits.
    """
    def __init__(self, main_window):
        super().__init__(main_window)
        self.main_window = main_window
        self.data: Optional[JSON] = None
        self.items: List[Dict[str, Any]] = []
        self.build_rows: List[Dict[str, Any]] = []
        self.row_to_entry: Dict[int, Dict[str, Any]] = {}
        self._populating = False

        self._all_handles: List[str] = []
        self._all_blades: List[str] = []
        self._all_slots: List[str] = ["ELEquipSlotType::E_NONE",
                                      "ELEquipSlotType::E_WEAPON_1",
                                      "ELEquipSlotType::E_WEAPON_2",
                                      "ELEquipSlotType::E_WEAPON_3",
                                      "ELEquipSlotType::E_SLAVEARM",
                                      "ELEquipSlotType::E_SLAVEARM_2",
                                      "ELEquipSlotType::E_GEAR_EAR_1",
                                      "ELEquipSlotType::E_GEAR_EAR_2",
                                      "ELEquipSlotType::E_GEAR_EAR_3",
                                      "ELEquipSlotType::E_GEAR_EAR_4",
                                      "ELEquipSlotType::E_GEAR_WRIST",
                                      "ELEquipSlotType::E_CONVERTER",
                                      "ELEquipSlotType::E_LINER",
                                      "ELEquipSlotType::E_GRINDER_UNIT_SLOT",
                                      "ELEquipSlotType::E_MONAD_UNIT_SLOT",
                                      "ELEquipSlotType::E_EYEWEAR_COSTUME",
                                      "ELEquipSlotType::E_BODY_COSTUME",
                                      "ELEquipSlotType::E_BAG_COSTUM2",
                                      "ELEquipSlotType::E_BAG_COSTUM3",
                                     ]

        root = QVBoxLayout(self)

        # Table
        self.tbl = QTableWidget(0, 4, self)
        self.tbl.setAlternatingRowColors(True)
        self.tbl.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.tbl.setHorizontalHeaderLabels(["Display", "Handle", "Blade", "Slot"])
        hdr = self.tbl.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.tbl.itemSelectionChanged.connect(self._on_table_selection)
        self.tbl.cellClicked.connect(lambda *_: self._on_table_selection())  # clicking Display triggers editor
        root.addWidget(self.tbl)

        # Editor
        gb = QGroupBox("Build Editor")
        form = QFormLayout(gb)

        self.ed_display = QLineEdit(); self.ed_display.setReadOnly(True)
        self.cb_handle = QComboBox(); self.cb_handle.setEditable(True)
        self.cb_blade  = QComboBox(); self.cb_blade.setEditable(True)
        self.cb_slot   = QComboBox(); self.cb_slot.setEditable(False)

        self.ed_sharp  = QLineEdit(); self.ed_sharp.setValidator(QIntValidator(0, 999999, self))
        self.ed_uid    = QLineEdit(); self.ed_uid.setValidator(QIntValidator(0, 2**31 - 1, self))
        self.cb_autoid = QCheckBox("Auto-ID on Apply / New / Clone"); self.cb_autoid.setChecked(True)

        form.addRow("Display", self.ed_display)
        form.addRow("Handle",  self.cb_handle)
        form.addRow("Blade",   self.cb_blade)
        form.addRow("Slot",    self.cb_slot)
        form.addRow("SharpnessPoint_0", self.ed_sharp)
        form.addRow("UniqueId_0 (Int64; blank to remove)", self.ed_uid)
        form.addRow("", self.cb_autoid)
        root.addWidget(gb)

        # Buttons
        btns = QHBoxLayout()
        self.btn_new    = QPushButton("New")
        self.btn_clone  = QPushButton("Clone")
        self.btn_delete = QPushButton("Delete")
        btns.addWidget(self.btn_new); btns.addWidget(self.btn_clone); btns.addWidget(self.btn_delete)
        btns.addStretch(1)
        self.btn_apply  = QPushButton("Apply")
        btns.addWidget(self.btn_apply)
        root.addLayout(btns)

        self.btn_new.clicked.connect(self._new_build)
        self.btn_clone.clicked.connect(self._clone_build)
        self.btn_delete.clicked.connect(self._delete_build)
        self.btn_apply.clicked.connect(self._apply_build)

    # ---------- plumbing ----------
    def load_data(self, data: JSON) -> None:
        self.data = data
        self.items = _items_array(data)
        self._reindex_builds()
        self._collect_lookups()
        self._rebuild_table()

    def _reindex_builds(self) -> None:
        self.build_rows = []
        for e in self.items:
            st = e.get("Struct", {})
            if _looks_like_weapon_build(st):
                self.build_rows.append(e)

    def _collect_lookups(self) -> None:
        # Only from visible weapon builds (keeps combos tidy)
        handles, blades, slots = set(), set(), set(self._all_slots)
        for e in self.build_rows:
            st = e.get("Struct", {})
            h = _read_name(st, "FirstCodeName_0")
            b = _read_name(st, "SecondCodeName_0")
            s = _read_enum(st, "EquipItemSlotType_0")
            if h: handles.add(h)
            if b: blades.add(b)
            if s.startswith("ELEquipSlotType::"):
                slots.add(s)
        self._all_handles = sorted(handles)
        self._all_blades  = sorted(blades)
        self._all_slots   = sorted(slots)

        self.cb_handle.clear(); self.cb_handle.addItems(self._all_handles)
        self.cb_blade.clear();  self.cb_blade.addItems(self._all_blades)
        self.cb_slot.clear();   self.cb_slot.addItems(self._all_slots)

    # ---------- table build/edit ----------
    def _rebuild_table(self) -> None:
        self._populating = True
        try:
            self.tbl.setRowCount(0)
            self.row_to_entry.clear()
            for r, e in enumerate(self.build_rows):
                st = e.get("Struct", {})
                disp = f"{_fmt(_read_name(st,'FirstCodeName_0'))} / {_fmt(_read_name(st,'SecondCodeName_0'))}"
                self.tbl.insertRow(r)

                # Display (read-only)
                it = QTableWidgetItem(disp)
                it.setFlags(it.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.tbl.setItem(r, 0, it)

                # Handle combobox (editable)
                cbh = QComboBox(); cbh.setEditable(True); cbh.addItems(self._all_handles)
                cur_h = _read_name(st, "FirstCodeName_0")
                if cur_h and cur_h not in self._all_handles:
                    cbh.insertItem(0, cur_h)
                cbh.setCurrentText(cur_h)
                cbh.currentTextChanged.connect(lambda _, row=r: self._on_row_handle_changed(row))
                self.tbl.setCellWidget(r, 1, cbh)

                # Blade combobox (editable)
                cbb = QComboBox(); cbb.setEditable(True); cbb.addItems(self._all_blades)
                cur_b = _read_name(st, "SecondCodeName_0")
                if cur_b and cur_b not in self._all_blades:
                    cbb.insertItem(0, cur_b)
                cbb.setCurrentText(cur_b)
                cbb.currentTextChanged.connect(lambda _, row=r: self._on_row_blade_changed(row))
                self.tbl.setCellWidget(r, 2, cbb)

                # Slot combobox
                cbs = QComboBox(); cbs.setEditable(False); cbs.addItems(self._all_slots)
                cur_s = _read_enum(st, "EquipItemSlotType_0") or "ELEquipSlotType::E_NONE"
                if cur_s not in self._all_slots:
                    cbs.insertItem(0, cur_s)
                cbs.setCurrentText(cur_s)
                cbs.currentTextChanged.connect(lambda _, row=r: self._on_row_slot_changed(row))
                self.tbl.setCellWidget(r, 3, cbs)

                self.row_to_entry[r] = e
        finally:
            self._populating = False

    # inline row change handlers
    def _on_row_handle_changed(self, row: int) -> None:
        if self._populating: return
        e = self.row_to_entry.get(row); 
        if not e: return
        st = e.setdefault("Struct", {})
        cb: QComboBox = self.tbl.cellWidget(row, 1)  # type: ignore
        new = (cb.currentText() or "").strip()
        _ensure_name(st, "FirstCodeName_0", new)
        self._update_row_display(row, st)
        if self._current_row() == row:
            self.cb_handle.setCurrentText(new); self._refresh_display(st)

    def _on_row_blade_changed(self, row: int) -> None:
        if self._populating: return
        e = self.row_to_entry.get(row); 
        if not e: return
        st = e.setdefault("Struct", {})
        cb: QComboBox = self.tbl.cellWidget(row, 2)  # type: ignore
        new = (cb.currentText() or "").strip()
        _ensure_name(st, "SecondCodeName_0", new)
        self._update_row_display(row, st)
        if self._current_row() == row:
            self.cb_blade.setCurrentText(new); self._refresh_display(st)

    def _on_row_slot_changed(self, row: int) -> None:
        if self._populating: return
        e = self.row_to_entry.get(row); 
        if not e: return
        st = e.setdefault("Struct", {})
        cb: QComboBox = self.tbl.cellWidget(row, 3)  # type: ignore
        new = (cb.currentText() or "ELEquipSlotType::E_NONE").strip()
        _ensure_enum(st, "EquipItemSlotType_0", "ELEquipSlotType", new)
        if self._current_row() == row:
            self.cb_slot.setCurrentText(new)

    def _update_row_display(self, row: int, st: Dict[str, Any]) -> None:
        disp = f"{_fmt(_read_name(st,'FirstCodeName_0'))} / {_fmt(_read_name(st,'SecondCodeName_0'))}"
        it = self.tbl.item(row, 0)
        if it: it.setText(disp)

    def _current_row(self) -> int:
        sel = self.tbl.selectionModel().selectedRows()
        return sel[0].row() if sel else -1

    def _on_table_selection(self) -> None:
        r = self._current_row()
        if r < 0: return
        e = self.row_to_entry.get(r)
        if not e: return
        st = e.get("Struct", {})
        self._populate_editor_from(st)

    # ---------- editor ----------
    def _populate_editor_from(self, st: Dict[str, Any]) -> None:
        self._refresh_display(st)
        h = _read_name(st, "FirstCodeName_0")
        b = _read_name(st, "SecondCodeName_0")
        s = _read_enum(st, "EquipItemSlotType_0") or "ELEquipSlotType::E_NONE"
        if h and h not in [self.cb_handle.itemText(i) for i in range(self.cb_handle.count())]:
            self.cb_handle.insertItem(0, h)
        if b and b not in [self.cb_blade.itemText(i) for i in range(self.cb_blade.count())]:
            self.cb_blade.insertItem(0, b)
        if s and s not in [self.cb_slot.itemText(i) for i in range(self.cb_slot.count())]:
            self.cb_slot.insertItem(0, s)
        self.cb_handle.setCurrentText(h)
        self.cb_blade.setCurrentText(b)
        self.cb_slot.setCurrentText(s)
        self.ed_sharp.setText(str(_get_int(st, "SharpnessPoint_0", 0)))
        uid = (st.get("UniqueId_0", {}) or {}).get("Int64", None)
        self.ed_uid.setText("" if uid is None else str(uid))

    def _refresh_display(self, st: Dict[str, Any]) -> None:
        disp = f"{_fmt(_read_name(st,'FirstCodeName_0'))} / {_fmt(_read_name(st,'SecondCodeName_0'))}"
        self.ed_display.setText(disp)

    def _apply_build(self) -> None:
        r = self._current_row()
        if r < 0:
            QMessageBox.information(self, "Build", "Select a build first.")
            return
        e = self.row_to_entry.get(r); 
        if not e: return
        st = e.setdefault("Struct", {})

        h = (self.cb_handle.currentText() or "").strip()
        b = (self.cb_blade.currentText() or "").strip()
        s = (self.cb_slot.currentText() or "ELEquipSlotType::E_NONE").strip()
        sp = (self.ed_sharp.text() or "0").strip()
        uid_txt = (self.ed_uid.text() or "").strip()

        if not _looks_like_weapon_build({"FirstCodeName_0":{"Name":h},"SecondCodeName_0":{"Name":b}}):
            QMessageBox.warning(self, "Build", "Handle must start with WP_PC_HND_ and Blade with WP_PC_BLD_.")
            return

        _ensure_name(st, "FirstCodeName_0", h)
        _ensure_name(st, "SecondCodeName_0", b)
        _ensure_enum(st, "EquipItemSlotType_0", "ELEquipSlotType", s)
        try: _ensure_int(st, "SharpnessPoint_0", int(sp or 0))
        except Exception:
            QMessageBox.warning(self, "Build", "SharpnessPoint_0 must be an integer.")
            return

        # Unique id
        if uid_txt == "":
            st.pop("UniqueId_0", None)
            if self.cb_autoid.isChecked():
                _ensure_int64(st, "UniqueId_0", self._generate_unique_id())
        else:
            try:
                uid_val = int(uid_txt)
            except Exception:
                QMessageBox.warning(self, "Build", "UniqueId must be an integer (or leave blank).")
                return
            if self.cb_autoid.isChecked() and uid_val == 0:
                uid_val = self._generate_unique_id()
            _ensure_int64(st, "UniqueId_0", uid_val)

        # refresh caches/table and keep selection
        self._reindex_builds()
        self._collect_lookups()
        cur = self._current_row()
        self._rebuild_table()
        if 0 <= cur < self.tbl.rowCount():
            self.tbl.selectRow(cur)

    # ---------- new / clone / delete ----------
    def _generate_unique_id(self) -> int:
        taken = set()
        for e in self.build_rows:
            st = e.get("Struct", {})
            node = st.get("UniqueId_0", {})
            if "Int64" in node:
                try: taken.add(int(node["Int64"]))
                except Exception: pass
        if taken:
            cand = max(taken) + 1
            if cand not in taken:
                return cand
        for _ in range(100):
            cand = random.randint(1, (1 << 53) - 1)
            if cand not in taken:
                return cand
        return random.randint(1, (1 << 31) - 1)

    def _new_build(self) -> None:
        if not self.data:
            return
        arr = _items_array(self.data)
        e = {"Struct": {}}
        st = e["Struct"]
        # start with current editor values (must look like a weapon)
        h = self.cb_handle.currentText().strip() or "WP_PC_HND_Hwando"
        b = self.cb_blade.currentText().strip() or "WP_PC_BLD_Hwando"
        if not _looks_like_weapon_build({"FirstCodeName_0":{"Name":h},"SecondCodeName_0":{"Name":b}}):
            h, b = "WP_PC_HND_Hwando", "WP_PC_BLD_Hwando"
        _ensure_name(st, "FirstCodeName_0", h)
        _ensure_name(st, "SecondCodeName_0", b)
        _ensure_enum(st, "EquipItemSlotType_0", "ELEquipSlotType",
                     self.cb_slot.currentText().strip() or "ELEquipSlotType::E_NONE")
        try:
            _ensure_int(st, "SharpnessPoint_0", int(self.ed_sharp.text() or 0))
        except Exception:
            _ensure_int(st, "SharpnessPoint_0", 0)
        if self.cb_autoid.isChecked() or (self.ed_uid.text() or "").strip() != "":
            uid_txt = (self.ed_uid.text() or "").strip()
            uid = self._generate_unique_id() if uid_txt == "" else int(uid_txt)
            _ensure_int64(st, "UniqueId_0", uid)

        arr.append(e)
        self._reindex_builds()
        self._collect_lookups()
        self._rebuild_table()
        r = self.tbl.rowCount() - 1
        if r >= 0: self.tbl.selectRow(r)

    def _clone_build(self) -> None:
        r = self._current_row()
        if r < 0:
            QMessageBox.information(self, "Clone", "Select a build to clone.")
            return
        src = self.row_to_entry.get(r)
        if not src:
            return
        arr = _items_array(self.data)
        new_e = copy.deepcopy(src)
        st = new_e.setdefault("Struct", {})
        if self.cb_autoid.isChecked():
            _ensure_int64(st, "UniqueId_0", self._generate_unique_id())
        else:
            uid_txt = (self.ed_uid.text() or "").strip()
            if uid_txt == "":
                st.pop("UniqueId_0", None)
            else:
                _ensure_int64(st, "UniqueId_0", int(uid_txt))
        arr.append(new_e)
        self._reindex_builds()
        self._collect_lookups()
        self._rebuild_table()
        self.tbl.selectRow(self.tbl.rowCount() - 1)

    def _delete_build(self) -> None:
        r = self._current_row()
        if r < 0: 
            return
        e = self.row_to_entry.get(r)
        if not e:
            return
        arr = _items_array(self.data)
        try:
            arr.remove(e)
        except ValueError:
            pass
        self._reindex_builds()
        self._collect_lookups()
        self._rebuild_table()
