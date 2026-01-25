# app/tabs/inventory_tab.py
from __future__ import annotations
from typing import Dict, Any, List, Tuple, Optional
import csv
import re
import os
import sys
import json

from pathlib import Path
import copy
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QIntValidator

INT32_MAX = 2_147_483_647
INT32_MIN = -2_147_483_648
from PyQt6.QtWidgets import (
    QWidget, QSplitter, QHBoxLayout, QVBoxLayout, QTabWidget,
    QTableWidget, QTableWidgetItem, QHeaderView, QGroupBox, QFormLayout,
    QLabel, QLineEdit, QCheckBox, QMessageBox, QToolButton, QStyle,
    QPushButton, QFileDialog, QTreeWidget, QTreeWidgetItem, QComboBox
)

# -------- simple helpers --------

def _clean(s: Any) -> str:
    return ("" if s is None else str(s)).strip()

def _clean_name_display(s: Any) -> str:
    return ("" if s is None else str(s)).strip().rstrip(",")

def _format_display(code: str) -> str:
    return code.replace("_0", "").replace("_", " ").title()

def _enum_slot_str(s: str) -> Optional[str]:
    if not isinstance(s, str):
        return None
    if s.startswith("ELEquipSlotType::"):
        tail = s.split("::", 1)[1]
        return None if tail.upper() == "E_NONE" else tail
    return None

def _norm_code(s: Any) -> str:
    base = ("" if s is None else str(s)).strip().rstrip(",")
    return base.casefold()

def _count_from_struct(st: Dict[str, Any]) -> int:
    """Read Count_0 from a Struct that may store Int or Int64."""
    c = (st.get("Count_0") or {})
    try:
        if "Int64" in c:
            return int(c.get("Int64") or 0)
        return int(c.get("Int") or 0)
    except Exception:
        return 0

UNION_KEYS = ("Int", "Int64", "Bool", "Name", "Str", "Enum")
ELE_SLOT_RE = re.compile(r"^ELEquipSlotType::E_(?!NONE\b).+", re.IGNORECASE)

# --- series/grouping heuristics (CSV can override later) ---
_SERIES_RX = re.compile(r'\bCH(\d{2})\b', re.I)  # chapter/boss series (e.g., CH01)

# -------- InventoryTab --------

class InventoryTab(QWidget):
    def __init__(self, main_window, master_csv_path: str = "app/resources/item_list.csv"):
        super().__init__(main_window)
        self.main_window = main_window
        self.master_csv_path = self._resolve_master_csv(master_csv_path)

        # master sheet
        self.names: Dict[str, str] = {}
        self.tips: Dict[str, str] = {}
        self._master_dupes: List[str] = []
        self._load_master_csv()


        # --- persistent 'seen codes' database (across saves) ---
        self._seen_db_dirty: bool = False
        self._seen_db: Dict[str, Any] = {"version": 1, "codes": {}}
        self._seen_codes: set[str] = set()
        self._seen_db_path: Path = self._default_seen_db_path()
        self._load_seen_db_into_memory()
        # merge 'seen' labels into display dictionaries (CSV remains authoritative)
        self._merge_seen_labels_into_master()
        # quick map: normalized ID -> canonical ID from CSV
        self._canon_by_norm: Dict[str, str] = {_norm_code(k): k for k in self.names.keys()}

        # --- persistent weapon templates database (across saves) ---
        # Stores full weapon entry templates observed in any loaded save. Used to re-add weapons
        # that may not exist in the current save without requiring master CSV coverage.
        self._weapon_db_dirty: bool = False
        self._weapon_db: Dict[str, Any] = {"version": 1, "weapons": {}}  # sig -> record
        self._weapon_db_keys: set[str] = set()
        self._weapon_db_path: Path = self._default_weapon_db_path()
        self._load_weapon_db_into_memory()


        # data
        self.data: Optional[Dict[str, Any]] = None
        self.inv_list: List[Dict[str, Any]] = []
        self._last_selected = None  # (cat: str, row: int, tbl: QTableWidget)
        self.entries_by_cat: Dict[str, List[Dict[str, Any]]] = {}
        self.tables_by_cat: Dict[str, QTableWidget] = {}
        self.row_entry_map_equipped: Dict[int, Dict[str, Any]] = {}

        # state for preserving UI focus
        self._restore_tab_title: Optional[str] = None
        self._restore_missing_row: Optional[int] = None
        self._prev_tab_title: Optional[str] = None

        # UI layout
        splitter = QSplitter(Qt.Orientation.Horizontal, self)

        # left: tabs + top toolbar
        left_container = QWidget()
        left_v = QVBoxLayout(left_container)
        left_v.setContentsMargins(0, 0, 0, 0)

        # Global search + mode
        topbar = QHBoxLayout()
        self.global_search = QLineEdit(self)
        self.global_search.setPlaceholderText("Search items, series (e.g., CH03), or categories…")
        self.cb_search_scope = QComboBox(self)
        self.cb_search_scope.addItems(["This Tab", "All Tabs"])
        self.btn_export = QPushButton("Export JSON…")
        self.btn_import = QPushButton("Import JSON…")
        self.btn_export.clicked.connect(self._export_inventory_dialog)
        self.btn_import.clicked.connect(self._import_inventory_dialog)
        self.global_search.textChanged.connect(self._apply_global_search)
        topbar.addWidget(self.global_search, 1)
        topbar.addWidget(self.cb_search_scope, 0)
        topbar.addWidget(self.btn_export, 0)
        topbar.addWidget(self.btn_import, 0)
        left_v.addLayout(topbar)

        self.tabs = QTabWidget()
        left_v.addWidget(self.tabs)
        splitter.addWidget(left_container)

        # ----- Missing tab -----
        self.missing_page = QWidget()
        mv = QVBoxLayout(self.missing_page)
        mh = QHBoxLayout()
        self.missing_filter = QLineEdit(self)
        self.missing_filter.setPlaceholderText("Search missing items…")
        self.btn_add_all = QPushButton("Add All (visible)")
        self.btn_add_all.clicked.connect(self._add_all_missing_visible)
        self.missing_filter.textChanged.connect(self._filter_missing)
        mh.addWidget(self.missing_filter, 1)
        mh.addWidget(self.btn_add_all, 0)
        mv.addLayout(mh)

        self.tbl_missing = QTableWidget(0, 2)
        self.tbl_missing.setAlternatingRowColors(True)
        self.tbl_missing.setHorizontalHeaderLabels(["Name", "Add"])
        mhdr = self.tbl_missing.horizontalHeader()
        mhdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        mhdr.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.tbl_missing.cellClicked.connect(self._missing_clicked)
        mv.addWidget(self.tbl_missing)

        self.tabs.addTab(self.missing_page, "Missing")

        # Equipped tab (read-only list)
        self.tbl_equipped = QTableWidget(0, 2)
        self.tbl_equipped.setAlternatingRowColors(True)
        self.tbl_equipped.setHorizontalHeaderLabels(["Name", "Slot"])
        eh = self.tbl_equipped.horizontalHeader()
        eh.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        eh.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.tbl_equipped.itemSelectionChanged.connect(self._equipped_selected)
        self.tabs.addTab(self.tbl_equipped, "Equipped")


        # ----- Weapon Database (observed across saves) -----
        # Built as a reusable page; it is inserted next to the Weapons tab during view rebuild.
        self.weapon_db_page = QWidget()
        wdv = QVBoxLayout(self.weapon_db_page)
        wdv.setContentsMargins(0, 0, 0, 0)

        wdb_top = QHBoxLayout()
        self.weapon_db_filter = QLineEdit()
        self.weapon_db_filter.setPlaceholderText("Search weapon database…")
        self.btn_weapon_db_add_selected = QPushButton("Add Selected")
        self.btn_weapon_db_remove_selected = QPushButton("Remove Selected")
        wdb_top.addWidget(self.weapon_db_filter, 1)
        wdb_top.addWidget(self.btn_weapon_db_add_selected, 0)
        wdb_top.addWidget(self.btn_weapon_db_remove_selected, 0)
        wdv.addLayout(wdb_top)

        self.tbl_weapon_db = QTableWidget(0, 5)
        self.tbl_weapon_db.setAlternatingRowColors(True)
        self.tbl_weapon_db.setHorizontalHeaderLabels(["Name", "Handle", "Blade", "Sharp", "Add"])
        wh = self.tbl_weapon_db.horizontalHeader()
        wh.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        wh.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        wh.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        wh.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        wh.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self.tbl_weapon_db.cellClicked.connect(self._weapon_db_clicked)
        wdv.addWidget(self.tbl_weapon_db)

        self.weapon_db_filter.textChanged.connect(self._filter_weapon_db)
        self.btn_weapon_db_add_selected.clicked.connect(self._weapon_db_add_selected_clicked)
        self.btn_weapon_db_remove_selected.clicked.connect(self._weapon_db_remove_selected_clicked)


        # right: details
        right = QWidget()
        vr = QVBoxLayout(right)
        vr.setContentsMargins(8, 8, 8, 8)

        self.toggle = QToolButton()
        self.toggle.setCheckable(True)
        self.toggle.setChecked(True)
        self.toggle.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_ArrowDown))
        self.toggle.toggled.connect(lambda b: self._toggle_details(b))
        vr.addWidget(self.toggle)

        self.details = QGroupBox("Item Details")
        self.form = QFormLayout()
        self.details.setLayout(self.form)
        vr.addWidget(self.details)

        splitter.addWidget(right)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)

        layout = QHBoxLayout(self)
        layout.addWidget(splitter)

        if self._master_dupes:
            try:
                QMessageBox.warning(self, "Inventory", f"Item list: skipped {len(self._master_dupes)} duplicate ID(s). Keeping first occurrence.")
            except Exception:
                print(f"[InventoryTab] duplicate IDs in CSV: {self._master_dupes[:5]} ...")

    # ---------- path resolution ----------
    def _resolve_master_csv(self, rel_or_abs: str) -> str:
        hint = os.environ.get("LOP_CSV_HINT")
        if hint and os.path.exists(hint):
            return hint
        if os.path.isabs(rel_or_abs) and os.path.exists(rel_or_abs):
            return rel_or_abs

        candidates: List[str] = []

        if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
            base = getattr(sys, '_MEIPASS')
            candidates += [
                os.path.join(base, "app", "resources", "item_list.csv"),
                os.path.join(base, "item_list.csv"),
                os.path.join(base, "app", "item_list.csv"),
            ]

        exe_dir = os.path.dirname(getattr(sys, 'executable', '') or '')
        if exe_dir:
            candidates += [
                os.path.join(exe_dir, "app", "resources", "item_list.csv"),
                os.path.join(exe_dir, "item_list.csv"),
                os.path.join(exe_dir, "app", "item_list.csv"),
            ]

        dev_base = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
        candidates += [
            os.path.join(dev_base, "app", "resources", "item_list.csv"),
            os.path.join(dev_base, "item_list.csv"),
            os.path.join(dev_base, "app", "item_list.csv"),
        ]

        for p in candidates:
            if os.path.exists(p):
                return p
        return rel_or_abs

    # ---------- master CSV ----------
    def _load_master_csv(self) -> None:
        self.names.clear()
        self.tips.clear()
        self._master_dupes.clear()
        seen: set[str] = set()
        try:
            with open(self.master_csv_path, newline="", encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                headers = [h.strip() for h in (reader.fieldnames or [])]
                low = [h.lower() for h in headers]
                id_col = headers[low.index("id")] if "id" in low else headers[low.index("code")]
                nm_col = headers[low.index("actual name")] if "actual name" in low else headers[low.index("name")]
                tip_col = headers[low.index("tooltip")] if "tooltip" in low else None
                for row in reader:
                    cid = _clean(row.get(id_col))
                    if not cid:
                        continue
                    if cid in seen:
                        self._master_dupes.append(cid); continue
                    seen.add(cid)
                    self.names[cid] = _clean_name_display(row.get(nm_col)) or _format_display(cid)
                    if tip_col:
                        self.tips[cid] = _clean(row.get(tip_col))
        except FileNotFoundError:
            print(f"[InventoryTab] CSV not found: {self.master_csv_path}")
        except Exception as e:
            print("CSV load error:", e)

    # ---------- data load ----------

    # ---------- persistent seen-db helpers ----------
    def _default_seen_db_path(self) -> Path:
        """Default location for persistent 'seen codes' database.

        Controlled via LOP_USER_DB_PATH env var. If set to a directory, the file
        is created inside it; if set to a file path, that file is used.
        """
        env = os.environ.get("LOP_USER_DB_PATH", "").strip()
        if env:
            p = Path(env).expanduser()
            if p.is_dir():
                return p / "inventory_seen_db.json"
            return p

        if sys.platform.startswith("win"):
            base = Path(os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming")))
            return base / "LoPSaveEditor" / "inventory_seen_db.json"

        return Path.home() / ".lop_save_editor" / "inventory_seen_db.json"

    def _load_seen_db_into_memory(self) -> None:
        # shape: {"version": 1, "codes": {"CODE": {"name": "...", "tip": "..."}, ...}}
        self._seen_db = {"version": 1, "codes": {}}
        self._seen_codes = set()
        try:
            path = self._seen_db_path
            path.parent.mkdir(parents=True, exist_ok=True)
            if not path.exists():
                return
            raw = path.read_text(encoding="utf-8", errors="ignore").strip()
            if not raw:
                return
            data = json.loads(raw)
            codes = data.get("codes", {})
            if isinstance(codes, list):
                # legacy: ["CODE", ...]
                codes = {str(c): {} for c in codes if c}
            if not isinstance(codes, dict):
                return
            self._seen_db = {"version": int(data.get("version") or 1), "codes": codes}
            self._seen_codes = set(map(str, codes.keys()))
        except Exception:
            # never break the editor if the db file is malformed
            self._seen_db = {"version": 1, "codes": {}}
            self._seen_codes = set()

    def _save_seen_db_if_dirty(self) -> None:
        if not getattr(self, "_seen_db_dirty", False):
            return
        try:
            path = self._seen_db_path
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(path.suffix + ".tmp")
            tmp.write_text(json.dumps(self._seen_db, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(path)
            self._seen_db_dirty = False
        except Exception:
            # ignore; db is a convenience feature
            pass

    def _merge_seen_labels_into_master(self) -> None:
        codes = (self._seen_db or {}).get("codes", {})
        if not isinstance(codes, dict):
            return
        for code, meta in codes.items():
            if not code:
                continue
            # canonicalize against master CSV ids when possible
            norm = _norm_code(code)
            canon = self._canon_by_norm.get(norm, code) if hasattr(self, "_canon_by_norm") else code
            if canon in self.names:
                continue
            nm = ""
            tip = ""
            if isinstance(meta, dict):
                nm = str(meta.get("name") or "")
                tip = str(meta.get("tip") or "")
            self.names[canon] = nm or _format_display(canon)
            if tip:
                self.tips[canon] = tip

    def _remember_code(self, code: str) -> None:
        if not code:
            return
        norm = _norm_code(code)
        canon = self._canon_by_norm.get(norm, code)
        if canon in self._seen_codes:
            return
        self._seen_codes.add(canon)
        codes = self._seen_db.setdefault("codes", {})
        if isinstance(codes, dict):
            codes[canon] = {
                "name": self.names.get(canon, _format_display(canon)),
                "tip": self.tips.get(canon, ""),
            }
        # make sure UI dictionaries can reference it immediately
        if canon not in self.names:
            self.names[canon] = _format_display(canon)
        self._canon_by_norm[_norm_code(canon)] = canon
        self._seen_db_dirty = True

    def _harvest_seen_from_loaded_save(self) -> None:
        """Harvest item codes from the currently loaded save into the persistent db."""
        if not self.data or not isinstance(self.inv_list, list):
            return
        for e in self.inv_list:
            st = (e or {}).get("Struct", {}) if isinstance(e, dict) else {}
            a = (st.get("FirstCodeName_0") or {}).get("Name", "")
            b = (st.get("SecondCodeName_0") or {}).get("Name", "")
            if isinstance(a, str) and a:
                self._remember_code(a)
            if isinstance(b, str) and b:
                self._remember_code(b)
        self._save_seen_db_if_dirty()

    # ---------- persistent weapon-db helpers ----------
    def _default_weapon_db_path(self) -> Path:
        """Default location for persistent weapon templates database.

        Controlled via LOP_USER_DB_PATH env var. If set to a directory, the file
        is created inside it; if set to a file path, that file is used.
        """
        env = os.environ.get("LOP_USER_DB_PATH", "").strip()
        if env:
            p = Path(env).expanduser()
            if p.is_dir():
                return p / "weapon_db.json"
            return p

        if sys.platform.startswith("win"):
            base = Path(os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming")))
            return base / "LoPSaveEditor" / "weapon_db.json"

        return Path.home() / ".lop_save_editor" / "weapon_db.json"

    def _load_weapon_db_into_memory(self) -> None:
        # shape: {"version": 1, "weapons": {"sig": {"display": "...", "entry": {...}, ...}, ...}}
        self._weapon_db = {"version": 1, "weapons": {}}
        self._weapon_db_keys = set()
        try:
            path = self._weapon_db_path
            path.parent.mkdir(parents=True, exist_ok=True)
            if not path.exists():
                return
            raw = path.read_text(encoding="utf-8", errors="ignore").strip()
            if not raw:
                return
            data = json.loads(raw)
            weapons = data.get("weapons", {})
            if isinstance(weapons, list):
                # legacy (unexpected): [{"sig": "...", ...}, ...]
                tmp: Dict[str, Any] = {}
                for it in weapons:
                    if isinstance(it, dict) and it.get("sig"):
                        tmp[str(it["sig"])] = {k: v for k, v in it.items() if k != "sig"}
                weapons = tmp
            if not isinstance(weapons, dict):
                return
            self._weapon_db = {"version": int(data.get("version") or 1), "weapons": weapons}
            self._weapon_db_keys = set(map(str, weapons.keys()))
        except Exception:
            # never break the editor if the db file is malformed
            self._weapon_db = {"version": 1, "weapons": {}}
            self._weapon_db_keys = set()

    def _save_weapon_db_if_dirty(self) -> None:
        if not getattr(self, "_weapon_db_dirty", False):
            return
        try:
            path = self._weapon_db_path
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(path.suffix + ".tmp")
            tmp.write_text(json.dumps(self._weapon_db, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(path)
            self._weapon_db_dirty = False
        except Exception:
            # ignore; db is a convenience
            pass

    def _weapon_sig_for_entry(self, st: Dict[str, Any]) -> str:
        a = (st.get("FirstCodeName_0") or {}).get("Name", "") or ""
        b = (st.get("SecondCodeName_0") or {}).get("Name", "") or ""
        # canonicalize against CSV when possible
        a = self._canon_by_norm.get(_norm_code(a), a)
        b = self._canon_by_norm.get(_norm_code(b), b) if b else ""
        sharp = 0
        try:
            node = (st.get("SharpnessPoint_0") or {})
            if "Int64" in node:
                sharp = int(node.get("Int64") or 0)
            else:
                sharp = int(node.get("Int") or 0)
        except Exception:
            sharp = 0
        is_build = self._is_build_struct(st)
        return f"{'build' if is_build else 'weapon'}|{_norm_code(a)}|{_norm_code(b)}|{int(sharp)}"

    def _weapon_display_for(self, a: str, b: str, sharp: int, is_build: bool) -> str:
        # Friendly-ish display: use CSV name if present, else code
        a_disp = self.names.get(a, _format_display(a))
        b_disp = self.names.get(b, _format_display(b)) if b else ""
        if is_build and b:
            base = f"{a_disp} + {b_disp}"
        else:
            base = a_disp if a_disp else (a or b_disp)
        if sharp:
            return f"{base}  [Sharp {sharp}]"
        return base

    def _sanitize_weapon_entry_template(self, entry: Dict[str, Any]) -> Dict[str, Any]:
        e = copy.deepcopy(entry)
        st = (e.get("Struct") or {})
        # normalize codes to canonical values (when possible)
        a = (st.get("FirstCodeName_0") or {}).get("Name", "") or ""
        b = (st.get("SecondCodeName_0") or {}).get("Name", "") or ""
        a = self._canon_by_norm.get(_norm_code(a), a)
        b = self._canon_by_norm.get(_norm_code(b), b) if b else ""
        if isinstance(st.get("FirstCodeName_0"), dict):
            st["FirstCodeName_0"]["Name"] = a
        if b and isinstance(st.get("SecondCodeName_0"), dict):
            st["SecondCodeName_0"]["Name"] = b

        # reset unique id (allocated at add-time)
        uid = st.get("UniqueId_0")
        if isinstance(uid, dict):
            if "Int64" in uid:
                uid["Int64"] = 0
            elif "Int" in uid:
                uid["Int"] = 0
            else:
                uid["Int"] = 0

        # ensure any equip slot enum is NONE
        for v in st.values():
            if isinstance(v, dict) and isinstance(v.get("Enum"), str) and v["Enum"].startswith("ELEquipSlotType::"):
                v["Enum"] = "ELEquipSlotType::E_NONE"

        # count (if present) to 1
        c = st.get("Count_0")
        if isinstance(c, dict):
            if "Int64" in c:
                c["Int64"] = 1
            elif "Int" in c:
                c["Int"] = 1
            else:
                c["Int"] = 1

        e["Struct"] = st
        return e

    def _harvest_weapon_db_from_loaded_save(self) -> None:
        """Harvest weapon entries from the currently loaded save into the persistent weapon db."""
        if not self.data or not isinstance(self.inv_list, list):
            return

        weapons = self._weapon_db.setdefault("weapons", {})
        changed = False

        for e in self.inv_list:
            if not isinstance(e, dict):
                continue
            st = (e.get("Struct") or {})
            if not isinstance(st, dict):
                continue

            a = (st.get("FirstCodeName_0") or {}).get("Name", "") or ""
            if not a:
                continue
            a_canon = self._canon_by_norm.get(_norm_code(a), a)
            cat = self._category_for_ingame(a_canon)
            is_build = self._is_build_struct(st)

            # Only store things that belong in the Weapons view
            if cat != "Weapons" and not is_build:
                continue

            b = (st.get("SecondCodeName_0") or {}).get("Name", "") or ""
            b_canon = self._canon_by_norm.get(_norm_code(b), b) if b else ""

            sharp = 0
            try:
                node = (st.get("SharpnessPoint_0") or {})
                if "Int64" in node:
                    sharp = int(node.get("Int64") or 0)
                else:
                    sharp = int(node.get("Int") or 0)
            except Exception:
                sharp = 0

            sig = self._weapon_sig_for_entry(st)
            if sig in weapons:
                continue

            disp = self._weapon_display_for(a_canon, b_canon, int(sharp), bool(is_build))
            tmpl = self._sanitize_weapon_entry_template(e)

            weapons[sig] = {
                "display": disp,
                "handle": a_canon,
                "blade": b_canon,
                "sharp": int(sharp),
                "is_build": bool(is_build),
                "entry": tmpl,
            }
            changed = True

        if changed:
            self._weapon_db_keys = set(map(str, weapons.keys()))
            self._weapon_db_dirty = True
            self._save_weapon_db_if_dirty()

    # ---------- weapon database UI ----------
    def _rebuild_weapon_db_table(self) -> None:
        if not hasattr(self, "tbl_weapon_db"):
            return
        weapons = (self._weapon_db or {}).get("weapons", {})
        if not isinstance(weapons, dict):
            weapons = {}

        self.tbl_weapon_db.setRowCount(0)
        plus = self.style().standardIcon(QStyle.StandardPixmap.SP_DialogYesButton)

        # Stable ordering by display then handle/blade
        def _sort_key(item):
            sig, rec = item
            if not isinstance(rec, dict):
                return ("", "", "", sig)
            return (
                str(rec.get("display") or "").lower(),
                str(rec.get("handle") or "").lower(),
                str(rec.get("blade") or "").lower(),
                sig,
            )

        for sig, rec in sorted(weapons.items(), key=_sort_key):
            if not isinstance(rec, dict):
                continue
            r = self.tbl_weapon_db.rowCount()
            self.tbl_weapon_db.insertRow(r)

            name = QTableWidgetItem(str(rec.get("display") or sig))
            name.setData(Qt.ItemDataRole.UserRole, sig)
            name.setFlags(name.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.tbl_weapon_db.setItem(r, 0, name)

            h = QTableWidgetItem(str(rec.get("handle") or ""))
            h.setFlags(h.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.tbl_weapon_db.setItem(r, 1, h)

            b = QTableWidgetItem(str(rec.get("blade") or ""))
            b.setFlags(b.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.tbl_weapon_db.setItem(r, 2, b)

            sh = QTableWidgetItem(str(rec.get("sharp") or 0))
            sh.setFlags(sh.flags() & ~Qt.ItemFlag.ItemIsEditable)
            sh.setTextAlignment(int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter))
            self.tbl_weapon_db.setItem(r, 3, sh)

            add = QTableWidgetItem()
            add.setData(Qt.ItemDataRole.DecorationRole, plus)
            add.setData(Qt.ItemDataRole.UserRole, sig)
            add.setFlags(Qt.ItemFlag.ItemIsEnabled)
            self.tbl_weapon_db.setItem(r, 4, add)

        self._filter_weapon_db()

    def _filter_weapon_db(self) -> None:
        needle = (self.weapon_db_filter.text() or "").strip().lower() if hasattr(self, "weapon_db_filter") else ""
        for r in range(self.tbl_weapon_db.rowCount()):
            namev = (self.tbl_weapon_db.item(r, 0) or QTableWidgetItem("")).text().lower()
            hv = (self.tbl_weapon_db.item(r, 1) or QTableWidgetItem("")).text().lower()
            bv = (self.tbl_weapon_db.item(r, 2) or QTableWidgetItem("")).text().lower()
            show = True if not needle else (needle in namev or needle in hv or needle in bv)
            self.tbl_weapon_db.setRowHidden(r, not show)

    def _weapon_db_clicked(self, row: int, col: int) -> None:
        if col != 4:
            return
        sig = self.tbl_weapon_db.item(row, col).data(Qt.ItemDataRole.UserRole) if self.tbl_weapon_db.item(row, col) else None
        if not sig:
            sig = self.tbl_weapon_db.item(row, 0).data(Qt.ItemDataRole.UserRole) if self.tbl_weapon_db.item(row, 0) else None
        if not sig:
            return
        self._add_weapon_from_db(str(sig))

    def _weapon_db_add_selected_clicked(self) -> None:
        rows = sorted({idx.row() for idx in self.tbl_weapon_db.selectionModel().selectedRows()}) if self.tbl_weapon_db.selectionModel() else []
        if not rows:
            return
        sig = self.tbl_weapon_db.item(rows[0], 0).data(Qt.ItemDataRole.UserRole) if self.tbl_weapon_db.item(rows[0], 0) else None
        if sig:
            self._add_weapon_from_db(str(sig))

    def _weapon_db_remove_selected_clicked(self) -> None:
        rows = sorted({idx.row() for idx in self.tbl_weapon_db.selectionModel().selectedRows()}) if self.tbl_weapon_db.selectionModel() else []
        if not rows:
            return
        weapons = (self._weapon_db or {}).get("weapons", {})
        if not isinstance(weapons, dict):
            return
        removed = 0
        for r in reversed(rows):
            sig = self.tbl_weapon_db.item(r, 0).data(Qt.ItemDataRole.UserRole) if self.tbl_weapon_db.item(r, 0) else None
            if sig and str(sig) in weapons:
                weapons.pop(str(sig), None)
                removed += 1
        if removed:
            self._weapon_db_dirty = True
            self._save_weapon_db_if_dirty()
            self._rebuild_weapon_db_table()

    def _alloc_next_unique_id(self) -> int:
        mx = 0
        try:
            for e in (self.inv_list or []):
                if not isinstance(e, dict):
                    continue
                st = e.get("Struct", {}) or {}
                if not isinstance(st, dict):
                    continue
                node = (st.get("UniqueId_0") or {})
                if isinstance(node, dict):
                    if "Int64" in node:
                        v = int(node.get("Int64") or 0)
                    else:
                        v = int(node.get("Int") or 0)
                    if v > mx:
                        mx = v
        except Exception:
            mx = 0
        return int(mx) + 1

    def _add_weapon_from_db(self, sig: str) -> None:
        if not self.data:
            return
        weapons = (self._weapon_db or {}).get("weapons", {})
        if not isinstance(weapons, dict) or sig not in weapons:
            return
        rec = weapons.get(sig) or {}
        tmpl = (rec.get("entry") if isinstance(rec, dict) else None)
        if not isinstance(tmpl, dict):
            return

        try:
            items = self._ensure_items_array()
        except Exception:
            QMessageBox.warning(self, "Weapon Database", "Could not access inventory list.")
            return

        new_entry = copy.deepcopy(tmpl)
        st = (new_entry.get("Struct") or {})
        if not isinstance(st, dict):
            st = {}
            new_entry["Struct"] = st

        # allocate a fresh UniqueId_0
        uid_val = self._alloc_next_unique_id()
        uid = st.get("UniqueId_0")
        if not isinstance(uid, dict):
            uid = {"tag": {"data": {"Other": "IntProperty"}}, "Int": 0}
            st["UniqueId_0"] = uid
        if "Int64" in uid:
            uid["Int64"] = int(uid_val)
        else:
            uid["Int"] = int(uid_val)

        # ensure unequipped
        for v in st.values():
            if isinstance(v, dict) and isinstance(v.get("Enum"), str) and v["Enum"].startswith("ELEquipSlotType::"):
                v["Enum"] = "ELEquipSlotType::E_NONE"

        # ensure count=1 if present
        c = st.get("Count_0")
        if isinstance(c, dict):
            if "Int64" in c:
                c["Int64"] = 1
            else:
                c["Int"] = 1

        items.append(new_entry)

        # mark dirty
        try:
            w = self.window()
            if w is not None and hasattr(w, "_mark_dirty"):
                w._mark_dirty(True)
        except Exception:
            pass

        # refresh views and keep db updated
        self._refresh_inv_list()
        self._dedupe_inventory_in_place()
        self._rebuild_all_views()



    def load_data(self, data: Dict[str, Any]) -> None:
        self.data = data
        self._refresh_inv_list()
        self._dedupe_inventory_in_place()
        self._harvest_seen_from_loaded_save()
        self._harvest_weapon_db_from_loaded_save()
        self._rebuild_all_views()

    def _refresh_inv_list(self) -> None:
        """Refresh self.inv_list using the *live* PlayerItems_0 array reference.

        The previous implementation used a hard-coded path into CharacterItem_0. On some saves
        (and after certain edits), that path can diverge from the actual serialized list that
        uesave/from-json writes back, which means the UI rebuilds against a stale list and the
        Missing tab does not update after bulk-add.
        """
        self.inv_list = []
        self.entries_by_cat.clear()
        self.tables_by_cat.clear()
        self.row_entry_map_equipped.clear()

        if not self.data:
            return

        try:
            # Prefer the path-agnostic DFS finder (returns the live list reference)
            live = self._find_items_array_ref(self.data)
            if isinstance(live, list):
                self.inv_list = live
                return

            # Fallback to legacy hard-coded path (older/edge save shapes)
            root = self.data["root"]["properties"]["CharacterSaveData_0"]["Struct"]["Struct"]
            self.inv_list = root["CharacterItem_0"]["Struct"]["Struct"]["PlayerItems_0"]["Array"]["Struct"]["value"]
        except Exception:
            self.inv_list = []


    # ---------- inventory array finder (path-agnostic) ----------
    def _find_items_array_ref(self, root: dict) -> Optional[list]:
        """
        DFS search for the exact inventory array the game uses:
          ... → "PlayerItems_0" → "Array" → "Struct" → "value"  (a list)
        Returns the *live* list reference or None.
        """
        stack = [root]
        while stack:
            cur = stack.pop()
            if isinstance(cur, dict):
                try:
                    arr = cur["PlayerItems_0"]["Array"]["Struct"]["value"]
                    if isinstance(arr, list):
                        return arr
                except Exception:
                    pass
                stack.extend(v for v in cur.values() if isinstance(v, (dict, list)))
            elif isinstance(cur, list):
                stack.extend(cur)
        return None

    # use the finder to ensure we always hit the serialized array
    def _ensure_items_array(self):
        """Return the *live* PlayerItems_0 list reference used by the save.

        Some saves contain more than one PlayerItems_0-shaped array. We prefer the known
        CharacterSaveData_0 → CharacterItem_0 path first (when present), then fall back
        to a DFS search.
        """
        if not self.data:
            raise RuntimeError("No save loaded.")
        # 1) Preferred/known path
        try:
            root = self.data["root"]["properties"]["CharacterSaveData_0"]["Struct"]["Struct"]
            arr = root["CharacterItem_0"]["Struct"]["Struct"]["PlayerItems_0"]["Array"]["Struct"]["value"]
            if isinstance(arr, list):
                return arr
        except Exception:
            pass

        # 2) DFS inside CharacterSaveData_0 subtree
        try:
            root = self.data["root"]["properties"]["CharacterSaveData_0"]["Struct"]["Struct"]
            arr = self._find_items_array_ref(root)
            if isinstance(arr, list):
                return arr
        except Exception:
            pass

        # 3) DFS anywhere (last resort)
        arr = self._find_items_array_ref(self.data)
        if isinstance(arr, list):
            return arr

        raise RuntimeError("Could not locate PlayerItems_0 array in the loaded save.")

    # ---------- build detection & keys ----------
    def _is_build_struct(self, st: Dict[str, Any]) -> bool:
        """True if this entry is an assembled weapon (handle+blade)."""
        return bool((st.get("bIsWeapon_0", {}) or {}).get("Bool", False))

    def _dedupe_key_for_struct(self, st: Dict[str, Any]) -> tuple:
        """Return a tuple key for dedupe/merge decisions."""
        if self._is_build_struct(st):
            uid = (st.get("UniqueId_0", {}) or {}).get("Int", None)
            h = (st.get("FirstCodeName_0", {}) or {}).get("Name", "")
            b = (st.get("SecondCodeName_0", {}) or {}).get("Name", "")
            return ("build", _norm_code(h), _norm_code(b), uid)
        code = (st.get("FirstCodeName_0", {}) or {}).get("Name", "")
        return ("code", _norm_code(code))

    def _dedupe_key_for_entry(self, e: Dict[str, Any]) -> tuple:
        return self._dedupe_key_for_struct(e.get("Struct", {}))

    # ---------- duplicate merge ----------
    def _dedupe_inventory_in_place(self) -> None:
        """
        Smarter de-dupe:

        • BUILDS (bIsWeapon_0 == True) and other NON-STACKABLES:
          Keep one row per exact identity:
            (FirstCodeName_0, SecondCodeName_0, SharpnessPoint_0, UniqueId_0).
          → Only true clones are removed. No count summing.

        • STACKABLES (Consumables, Materials):
          Merge by normalized FirstCodeName_0, sum counts, prefer Int64 if seen,
          and keep the first non-E_NONE equip slot.

        Writes the merged list back to the save while preserving first-seen order.
        """
        if not isinstance(self.inv_list, list) or not self.data:
            return

        def _read_int(node: Dict[str, Any], key: str) -> int:
            n = (node.get(key) or {})
            if "Int64" in n:
                try: return int(n.get("Int64") or 0)
                except Exception: return 0
            try: return int(n.get("Int") or 0)
            except Exception: return 0

        def _read_count(st: Dict[str, Any]) -> tuple[int, str]:
            c = (st.get("Count_0") or {})
            if "Int64" in c:
                try: return int(c.get("Int64") or 0), "Int64"
                except Exception: return 0, "Int64"
            try: return int(c.get("Int") or 0), "Int"
            except Exception: return 0, "Int"

        def _write_count(st: Dict[str, Any], value: int, kind: str) -> None:
            node = st.setdefault("Count_0", {})
            node.clear()
            if str(kind).lower() == "int64":
                node["Int64"] = int(value)
                node["tag"] = {"data": {"Other": "Int64Property"}}
            else:
                node["Int"] = int(value)
                node["tag"] = {"data": {"Other": "IntProperty"}}

        def _slot_value(st: Dict[str, Any]) -> str:
            for v in st.values():
                if isinstance(v, dict) and isinstance(v.get("Enum"), str) and v["Enum"].startswith("ELEquipSlotType::"):
                    return v["Enum"]
            return "ELEquipSlotType::E_NONE"

        def _set_slot_if_empty(st: Dict[str, Any], new_enum: str) -> None:
            if not isinstance(new_enum, str) or not new_enum.startswith("ELEquipSlotType::"):
                return
            if new_enum.endswith("E_NONE"):
                return
            key = None
            for k, v in st.items():
                if isinstance(v, dict) and isinstance(v.get("Enum"), str) and v["Enum"].startswith("ELEquipSlotType::"):
                    key = k; break
            if key is None:
                key = "EquipItemSlotType_0"
                st[key] = {"tag": {"data": {"Enum": ["ELEquipSlotType", None]}}, "Enum": "ELEquipSlotType::E_NONE"}
            if st[key].get("Enum", "ELEquipSlotType::E_NONE").endswith("E_NONE"):
                st[key]["Enum"] = new_enum
                st[key]["tag"] = {"data": {"Enum": ["ELEquipSlotType", None]}}

        def _is_build(st: Dict[str, Any]) -> bool:
            return bool((st.get("bIsWeapon_0") or {}).get("Bool", False))

        # --- First pass: normalize names, partition by type ---
        stackable_acc: Dict[str, Dict[str, Any]] = {}    # norm_code -> representative entry
        stackable_totals: Dict[str, int] = {}
        stackable_kind: Dict[str, str] = {}
        stackable_slot: Dict[str, str] = {}

        exact_seen: set[tuple] = set()
        kept_in_order: List[Dict[str, Any]] = []
        seen_norms_in_order: set[str] = set()

        for e in self.inv_list:
            st = e.get("Struct", {})
            raw_id = (st.get("FirstCodeName_0") or {}).get("Name", "") or ""
            norm = _norm_code(raw_id)
            if not norm:
                kept_in_order.append(e)
                continue

            # Canonicalize FirstCodeName via CSV (if present)
            canonical = self._canon_by_norm.get(norm, raw_id)
            st.setdefault("FirstCodeName_0", {"tag": {"data": {"Other": "NameProperty"}}})["Name"] = canonical

            second = (st.get("SecondCodeName_0") or {}).get("Name", "") or ""
            sharp  = _read_int(st, "SharpnessPoint_0")
            uid    = _read_int(st, "UniqueId_0")
            slot   = _slot_value(st)
            count, kind = _read_count(st)

            # Decide category: stackable vs build/non-stackable
            cat = self._category_for_ingame(canonical)
            is_build = _is_build(st)
            is_stackable = (cat in ("Consumables", "Materials")) and not is_build

            if is_stackable:
                if norm not in stackable_acc:
                    stackable_acc[norm] = e
                    stackable_totals[norm] = count
                    stackable_kind[norm] = kind
                    stackable_slot[norm] = slot
                    if norm not in seen_norms_in_order:
                        kept_in_order.append(e)
                        seen_norms_in_order.add(norm)
                else:
                    stackable_totals[norm] += count
                    if kind == "Int64":
                        stackable_kind[norm] = "Int64"
                    if stackable_slot[norm].endswith("E_NONE") and not slot.endswith("E_NONE"):
                        stackable_slot[norm] = slot
            else:
                ident = (_norm_code(canonical), _norm_code(second), int(sharp), int(uid))
                if ident in exact_seen:
                    continue
                exact_seen.add(ident)
                kept_in_order.append(e)

        # Second pass: materialize merged stackables (write back sums)
        for e in kept_in_order:
            st = e.get("Struct", {})
            raw_id = (st.get("FirstCodeName_0") or {}).get("Name", "") or ""
            norm = _norm_code(raw_id)
            if norm in stackable_acc and stackable_acc[norm] is e:
                _write_count(st, stackable_totals.get(norm, 0), stackable_kind.get(norm, "Int"))
                _set_slot_if_empty(st, stackable_slot.get(norm, "ELEquipSlotType::E_NONE"))

        # Replace underlying JSON list with the cleaned/merged list
        try:
            # refresh list via finder to ensure we update the live array
            live = self._ensure_items_array()
            live[:] = kept_in_order
            self.inv_list = live
        except Exception:
            self.inv_list = kept_in_order

    # ---------- global search ----------
    def _apply_global_search(self) -> None:
        text = (self.global_search.text() or "").strip().lower()
        scope_all = (self.cb_search_scope.currentText() == "All Tabs")

        for i in range(self.tabs.count()):
            w = self.tabs.widget(i)
            title = self.tabs.tabText(i)
            match title:
                case "Cosmetics":
                    self._filter_cosmetics_tree(w, text, hide_non_matches=bool(text), active=scope_all or self.tabs.currentIndex() == i)
                case "Equipped":
                    self._filter_table(self.tbl_equipped, text, hide_non_matches=bool(text), active=scope_all or self.tabs.currentIndex() == i)
                case "Missing":
                    if scope_all:
                        self._filter_missing_global(text)
                case _:
                    if isinstance(w, QTableWidget):
                        self._filter_table(w, text, hide_non_matches=bool(text), active=scope_all or self.tabs.currentIndex() == i)

    def _filter_table(self, tbl: QTableWidget, needle: str, *, hide_non_matches: bool, active: bool) -> None:
        if not active:
            if hide_non_matches:
                return
        for r in range(tbl.rowCount()):
            show = True
            if needle:
                text = (tbl.item(r, 0) or QTableWidgetItem("")).text().lower()
                show = needle in text
            tbl.setRowHidden(r, not show if hide_non_matches else False)

    def _filter_cosmetics_tree(self, tree: QWidget, needle: str, *, hide_non_matches: bool, active: bool) -> None:
        if not isinstance(tree, QTreeWidget) or not active:
            return
        top_count = tree.topLevelItemCount()
        for i in range(top_count):
            parent = tree.topLevelItem(i)
            parent_visible = False
            for j in range(parent.childCount()):
                ch = parent.child(j)
                if not needle:
                    ch.setHidden(False); parent_visible = True
                else:
                    line = " ".join((ch.text(0), ch.text(1), ch.text(2))).lower()
                    hit = needle in line
                    ch.setHidden(hide_non_matches and not hit)
                    parent_visible = parent_visible or hit
            parent.setHidden(hide_non_matches and not parent_visible)

    def _filter_missing_global(self, needle: str) -> None:
        for r in range(self.tbl_missing.rowCount()):
            namev = (self.tbl_missing.item(r, 0) or QTableWidgetItem("")).text().lower()
            self.tbl_missing.setRowHidden(r, False if not needle else (needle not in namev))

    # ---------- category / equipped / missing ----------

    def _category_for(self, code: str) -> str:
        if not code:
            return ""
        p = code.split("_", 1)[0].lower()
        if p in ("wp", "weapon", "slavearm"):
            return "Weapons"
        if p in ("mask", "costume", "hatcostume", "head", "gesture"):
            return "Cosmetics"
        return p.title()

    def _category_for_ingame(self, code: str) -> str:
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
        return self._category_for(code)

    def _series_of(self, code: str) -> Optional[str]:
        if not code:
            return None
        n = _norm_code(code)
        canon = self._canon_by_norm.get(n, code)
        m = _SERIES_RX.search(canon)
        if m:
            return f"CH{m.group(1)}"
        base = canon.split("_", 1)[-1].casefold() if "_" in canon else canon.casefold()
        if any(canon.startswith(p) for p in ("HatCostume_", "Costume_", "Head_", "Mask_", "Gesture_")):
            tail = base.replace("costume_", "").replace("hatcostume_", "").replace("head_", "").replace("gesture_", "")
            return tail[:24] or None
        return None

    def _rebuild_all_views(self) -> None:
        self._prev_tab_title = self.tabs.tabText(self.tabs.currentIndex()) if self.tabs.count() else "Missing"

        # keep permanent tabs; remove others
        for i in reversed(range(self.tabs.count())):
            w = self.tabs.widget(i)
            if w not in (self.missing_page, self.tbl_equipped):
                self.tabs.removeTab(i)
        self.entries_by_cat.clear()
        self.tables_by_cat.clear()

        self._build_consolidated_categories()
        self._build_cosmetics_tab()
        self._build_raw_all_tab()

        self._rebuild_equipped()
        self._rebuild_missing()
        self._restore_focus_if_any()
        self._apply_global_search()

    def _build_consolidated_categories(self) -> None:
        buckets = ["Weapons", "Consumables", "Materials", "Keys/Lore"]
        table_for: Dict[str, QTableWidget] = {}
        for b in buckets:
            tbl = QTableWidget(0, 2)
            tbl.setAlternatingRowColors(True)
            tbl.setHorizontalHeaderLabels(["Name", "Count"])
            tbl.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
            tbl.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
            tbl.itemSelectionChanged.connect(lambda _b=b, t=tbl: self._category_selected(_b, t))
            self.tabs.addTab(tbl, b)
            if b == "Weapons":
                self.tabs.addTab(self.weapon_db_page, "Database")
                self._rebuild_weapon_db_table()
            table_for[b] = tbl
            self.tables_by_cat[b] = tbl
            self.entries_by_cat[b] = []

        for entry in self.inv_list:
            st = entry.get("Struct", {})
            code_raw = st.get("FirstCodeName_0", {}).get("Name", "")
            cat = self._category_for_ingame(code_raw)
            if cat not in table_for:
                continue
            tbl = table_for[cat]
            self.entries_by_cat[cat].append(entry)
            r = tbl.rowCount()
            tbl.insertRow(r)
            disp = self.names.get(code_raw, _format_display(code_raw))
            tip = self.tips.get(code_raw, code_raw)
            it = QTableWidgetItem(disp)
            it.setToolTip(tip)
            it.setData(Qt.ItemDataRole.UserRole, r)
            it.setFlags(it.flags() & ~Qt.ItemFlag.ItemIsEditable)
            tbl.setItem(r, 0, it)
            cnt_it = QTableWidgetItem(str(_count_from_struct(st)))
            cnt_it.setFlags(cnt_it.flags() & ~Qt.ItemFlag.ItemIsEditable)
            cnt_it.setTextAlignment(int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter))
            tbl.setItem(r, 1, cnt_it)

    def _build_cosmetics_tab(self) -> None:
        cos_entries = []
        for e in self.inv_list:
            st = e.get("Struct", {})
            code = (st.get("FirstCodeName_0", {}) or {}).get("Name", "")
            if self._category_for_ingame(code) == "Cosmetics":
                cos_entries.append(e)

        groups: dict[str, list[dict]] = {}
        for e in cos_entries:
            st = e.get("Struct", {})
            code = (st.get("FirstCodeName_0", {}) or {}).get("Name", "")
            series = self._series_of(code) or "Misc"
            groups.setdefault(series, []).append(e)

        tree = QTreeWidget()
        tree.setColumnCount(3)
        tree.setHeaderLabels(["Set / Item", "Owned", "Slot"])
        tree.setAlternatingRowColors(True)
        tree.setSelectionMode(QTreeWidget.SelectionMode.SingleSelection)
        tree.setUniformRowHeights(True)

        self.cosmetics_tree = tree
        self.tabs.addTab(tree, "Cosmetics")

        for series, items in sorted(groups.items()):
            owned = sum(1 for e in items if _count_from_struct(e.get("Struct", {})) > 0)
            total = len(items)
            parent = QTreeWidgetItem([series, f"{owned}/{total}", ""])
            parent.setFirstColumnSpanned(True)
            tree.addTopLevelItem(parent)

            for e in items:
                st = e.get("Struct", {})
                code = (st.get("FirstCodeName_0", {}) or {}).get("Name", "")
                disp = self.names.get(code, _format_display(code))
                cnt = _count_from_struct(st)
                slot = ""
                for v in st.values():
                    if isinstance(v, dict) and isinstance(v.get("Enum"), str) and v["Enum"].startswith("ELEquipSlotType::"):
                        slot = (v["Enum"].split("::", 1)[1] or "").replace("E_", ""); break
                child = QTreeWidgetItem([disp, "Yes" if cnt > 0 else "No", slot])
                child.setData(0, Qt.ItemDataRole.UserRole, e)
                parent.addChild(child)

        tree.expandAll()
        tree.itemSelectionChanged.connect(self._on_cosmetics_selected)

    def _on_cosmetics_selected(self) -> None:
        if not getattr(self, "cosmetics_tree", None):
            return
        cur = self.cosmetics_tree.currentItem()
        if not cur:
            return
        entry = cur.data(0, Qt.ItemDataRole.UserRole)
        if isinstance(entry, dict):
            self._show_details(entry)

    def _refresh_selected_cosmetic_row(self) -> None:
        if not getattr(self, "cosmetics_tree", None):
            return
        cur = self.cosmetics_tree.currentItem()
        if not cur:
            return
        entry = cur.data(0, Qt.ItemDataRole.UserRole)
        if not isinstance(entry, dict):
            return

        st = entry.get("Struct", {})
        cnt = _count_from_struct(st)
        slot = ""
        for v in st.values():
            if isinstance(v, dict) and isinstance(v.get("Enum"), str) and v["Enum"].startswith("ELEquipSlotType::"):
                slot = (v["Enum"].split("::", 1)[1] or "").replace("E_", ""); break
        cur.setText(1, "Yes" if cnt > 0 else "No")
        cur.setText(2, slot)

        parent = cur.parent()
        if parent is not None:
            total = parent.childCount()
            owned = sum(1 for i in range(total) if parent.child(i).text(1).lower() == "yes")
            parent.setText(1, f"{owned}/{total}")

    def _build_raw_all_tab(self) -> None:
        tbl = QTableWidget(0, 2)
        tbl.setAlternatingRowColors(True)
        tbl.setHorizontalHeaderLabels(["Name", "Count"])
        tbl.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        tbl.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        tbl.itemSelectionChanged.connect(lambda t=tbl: self._category_selected("All (raw)", t))
        self.tabs.addTab(tbl, "All (raw)")
        self.tables_by_cat["All (raw)"] = tbl
        self.entries_by_cat["All (raw)"] = []

        for entry in self.inv_list:
            st = entry.get("Struct", {})
            code_raw = st.get("FirstCodeName_0", {}).get("Name", "")
            self.entries_by_cat["All (raw)"].append(entry)
            r = tbl.rowCount()
            tbl.insertRow(r)
            disp = self.names.get(code_raw, _format_display(code_raw))
            tip = self.tips.get(code_raw, code_raw)
            it = QTableWidgetItem(disp)
            it.setToolTip(tip)
            it.setData(Qt.ItemDataRole.UserRole, r)
            it.setFlags(it.flags() & ~Qt.ItemFlag.ItemIsEditable)
            tbl.setItem(r, 0, it)
            cnt_it = QTableWidgetItem(str(_count_from_struct(st)))
            cnt_it.setFlags(cnt_it.flags() & ~Qt.ItemFlag.ItemIsEditable)
            cnt_it.setTextAlignment(int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter))
            tbl.setItem(r, 1, cnt_it)

    def _rebuild_equipped(self) -> None:
        self.tbl_equipped.setRowCount(0)
        self.row_entry_map_equipped.clear()
        row = 0
        for entry in self.inv_list:
            st = entry.get("Struct", {})
            code_raw = st.get("FirstCodeName_0", {}).get("Name", "")
            slot = None
            for v in list(st.values()):
                if isinstance(v, dict) and "Enum" in v:
                    s = v["Enum"]
                    slot = _enum_slot_str(s) or slot
            if not slot:
                continue
            disp = self.names.get(code_raw, _format_display(code_raw))
            tip = self.tips.get(code_raw, code_raw)
            self.tbl_equipped.insertRow(row)
            n = QTableWidgetItem(disp); n.setToolTip(tip); n.setFlags(n.flags() & ~Qt.ItemFlag.ItemIsEditable)
            s = QTableWidgetItem(slot.replace("E_", "")); s.setFlags(s.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.tbl_equipped.setItem(row, 0, n)
            self.tbl_equipped.setItem(row, 1, s)
            self.row_entry_map_equipped[row] = entry
            row += 1

    def _rebuild_missing(self) -> None:
        # Build set of what we already have (canonicalized)
        have_codes = set()
        for e in self.inv_list:
            st = e.get("Struct", {})
            c_raw = (st.get("FirstCodeName_0") or {}).get("Name", "")
            canon = self._canon_by_norm.get(_norm_code(c_raw), c_raw)
            have_codes.add(_norm_code(canon))

        # Offer only categories the game really stores in PlayerItems_0
        ALLOWED = {"Consumables", "Materials", "Keys/Lore", "Cosmetics"}

        valid_csv_codes = [
            code for code in self.names.keys()
            if self._category_for_ingame(code) in ALLOWED
        ]
        missing = [code for code in valid_csv_codes if _norm_code(code) not in have_codes]

        self.tbl_missing.setRowCount(0)
        plus = self.style().standardIcon(QStyle.StandardPixmap.SP_DialogYesButton)
        for code in sorted(missing):
            r = self.tbl_missing.rowCount()
            self.tbl_missing.insertRow(r)
            nm = QTableWidgetItem(self.names.get(code, _format_display(code)))
            nm.setToolTip(self.tips.get(code, code))
            nm.setData(Qt.ItemDataRole.UserRole, code)
            nm.setFlags(nm.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.tbl_missing.setItem(r, 0, nm)

            add = QTableWidgetItem()
            add.setData(Qt.ItemDataRole.DecorationRole, plus)
            add.setData(Qt.ItemDataRole.UserRole, code)
            add.setFlags(Qt.ItemFlag.ItemIsEnabled)
            self.tbl_missing.setItem(r, 1, add)

        self._filter_missing()

    # --- Missing tab extras ---
    def _filter_missing(self) -> None:
        needle = (self.missing_filter.text() or "").strip().lower()
        for r in range(self.tbl_missing.rowCount()):
            namev = (self.tbl_missing.item(r, 0) or QTableWidgetItem("")).text().lower()
            self.tbl_missing.setRowHidden(r, False if not needle else (needle not in namev))

    def _add_all_missing_visible(self) -> None:
        codes: List[str] = []
        for r in range(self.tbl_missing.rowCount()):
            if self.tbl_missing.isRowHidden(r):
                continue
            code = self.tbl_missing.item(r, 0).data(Qt.ItemDataRole.UserRole)
            if code:
                codes.append(code)
        if not codes:
            return
        self._restore_tab_title = "Missing"
        self._restore_missing_row = 0
        self._add_items_batch(codes)

    # ---------- selection handlers ----------
    def _category_selected(self, cat: str, tbl: QTableWidget) -> None:
        sel = tbl.selectedIndexes()
        if not sel:
            return
        r = sel[0].row()
        if r < 0 or r >= len(self.entries_by_cat.get(cat, [])):
            return
        entry = self.entries_by_cat[cat][r]
        self._last_selected = (cat, r, tbl)
        self._show_details(entry)

    
    def _refresh_selected_table_count(self) -> None:
        """If the current tab is a table that includes a Count column, refresh it after Count_0 edits."""
        try:
            ctx = getattr(self, "_last_selected", None)
            if not ctx:
                return
            cat, row, tbl = ctx
            if not isinstance(tbl, QTableWidget):
                return
            if tbl.columnCount() < 2:
                return
            if row < 0 or row >= len(self.entries_by_cat.get(cat, [])):
                return
            entry = self.entries_by_cat[cat][row]
            st = entry.get("Struct", {})
            cnt = _count_from_struct(st)
            it = tbl.item(row, 1)
            if it is None:
                it = QTableWidgetItem(str(cnt))
                it.setFlags(it.flags() & ~Qt.ItemFlag.ItemIsEditable)
                it.setTextAlignment(int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter))
                tbl.setItem(row, 1, it)
            else:
                it.setText(str(cnt))
        except Exception:
            pass

    def _equipped_selected(self) -> None:
        rows = self.tbl_equipped.selectionModel().selectedRows()
        if not rows:
            return
        entry = self.row_entry_map_equipped.get(rows[0].row())
        if entry:
            self._show_details(entry)

    def _missing_clicked(self, row: int, col: int) -> None:
        if col not in (0, 1):
            return
        code = self.tbl_missing.item(row, 0).data(Qt.ItemDataRole.UserRole)
        if not code:
            return
        self._restore_tab_title = "Missing"
        self._restore_missing_row = row
        self._add_item(code)

    # ---------- details + editing ----------
    def _toggle_details(self, on: bool) -> None:
        self.details.setVisible(on)
        self.toggle.setIcon(self.style().standardIcon(
            QStyle.StandardPixmap.SP_ArrowDown if on else QStyle.StandardPixmap.SP_ArrowRight
        ))

    def _show_details(self, entry: Dict[str, Any]) -> None:
        while self.form.rowCount():
            self.form.removeRow(0)
        st = entry.get("Struct", {})
        items: List[Tuple[str, str, Any]] = []
        for k, v in st.items():
            if isinstance(v, dict):
                for u in UNION_KEYS:
                    if u in v:
                        val = v[u]; kind = u.lower()
                        items.append((k, kind, val)); break
        items.sort(key=lambda t: t[0].lower())

        for key, kind, val in items:
            label = QLabel(self._pretty(key))
            if kind in ("int", "int64"):
                maxv = 2_147_483_647 if kind == "int" else 9_223_372_036_854_775_807
                le = QLineEdit(str(val))
                le.setValidator(QIntValidator(INT32_MIN, INT32_MAX, self))
                le.editingFinished.connect(lambda a=key, e=le, k=kind: self._write_scalar(st, a, k, e.text()))
                self.form.addRow(label, le)
            elif kind == "bool":
                cb = QCheckBox(); cb.setChecked(bool(val))
                cb.stateChanged.connect(lambda _=None, a=key, c=cb: self._write_scalar(st, a, "bool", c.isChecked()))
                self.form.addRow(label, cb)
            elif kind == "enum":
                le = QLineEdit(str(val))
                le.editingFinished.connect(lambda a=key, e=le, k=kind: self._write_scalar(st, a, k, e.text()))
                self.form.addRow(label, le)
            else:  # str, name
                le = QLineEdit(str(val))
                le.editingFinished.connect(lambda a=key, e=le, k=kind: self._write_scalar(st, a, k, e.text()))
                self.form.addRow(label, le)

    def _pretty(self, attr: str) -> str:
        s = attr.replace("_0", "")
        return re.sub(r"(?<=[a-z])(?=[A-Z])", " ", s).replace("_", " ").title()

    def _write_scalar(self, struct: Dict[str, Any], key: str, kind: str, value: Any) -> None:
        node = struct.setdefault(key, {})
        node.clear()
        if kind == "int":
            node["Int"] = int(value) if str(value).strip() != "" else 0
            node["tag"] = {"data": {"Other": "IntProperty"}}
        elif kind == "int64":
            node["Int64"] = int(value) if str(value).strip() != "" else 0
            node["tag"] = {"data": {"Other": "Int64Property"}}
        elif kind == "bool":
            node["Bool"] = bool(value)
            node["tag"] = {"data": {"Other": "BoolProperty"}}
        elif kind == "name":
            node["Name"] = str(value)
            node["tag"] = {"data": {"Other": "NameProperty"}}
        elif kind == "enum":
            s = str(value)
            node["Enum"] = s
            etype = s.split("::", 1)[0] if "::" in s else ""
            node["tag"] = {"data": {"Enum": [etype, None]}}
        else:
            node["Str"] = str(value)
            node["tag"] = {"data": {"Other": "StrProperty"}}

        # Ensure the main window knows there are unsaved edits
        try:
            w = self.window()
            if w is not None and hasattr(w, "_mark_dirty"):
                w._mark_dirty(True)
        except Exception:
            pass

        # If the item identity changes (code name), the item may move categories.
        # Rebuild views so tabs/missing/equipped reflect the new state.
        if key in ("FirstCodeName_0", "SecondCodeName_0"):
            try:
                self._refresh_inv_list()
                self._rebuild_all_views()
            except Exception:
                pass

        if key.lower().startswith("elequipslottype") or (kind == "enum" and isinstance(value, str) and value.startswith("ELEquipSlotType::")):
            self._rebuild_equipped()
            self._refresh_selected_cosmetic_row()

        if key == "Count_0":
            self._refresh_selected_table_count()
            self._refresh_selected_cosmetic_row()

    # ---------- add item(s) ----------

    def _next_unique_id(self, items: List[Dict[str, Any]]) -> int:
        mx = 0
        for e in items:
            st = e.get("Struct", {})
            u = (st.get("UniqueId_0") or {}).get("Int", None)
            if isinstance(u, int):
                mx = max(mx, u)
        return mx + 1

    def _pick_template_entry(self, items: List[Dict[str, Any]], want_cat: str) -> Optional[Dict[str, Any]]:
        # Prefer an existing non-build entry in the same category (Keys/Lore, Cosmetics, etc.)
        for e in items:
            st = e.get("Struct", {})
            if self._is_build_struct(st):
                continue
            code0 = (st.get("FirstCodeName_0") or {}).get("Name", "") or ""
            if code0 and self._category_for_ingame(code0) == want_cat:
                return e
        # Fallback: any non-build entry
        for e in items:
            if not self._is_build_struct(e.get("Struct", {})):
                return e
        return None

    def _make_inventory_entry(self, items: List[Dict[str, Any]], code: str) -> Dict[str, Any]:
        """Create a new inventory entry by cloning an existing template row.

        This preserves any extra fields/tags the game or serializer expects, which improves
        reliability versus constructing a minimal struct from scratch.
        """
        norm = _norm_code(code)
        canonical = self._canonical_id_for(norm, code)

        want_cat = self._category_for_ingame(canonical)
        tmpl = self._pick_template_entry(items, want_cat)

        if tmpl is not None:
            entry = copy.deepcopy(tmpl)
            st = entry.setdefault("Struct", {})
        else:
            entry = {"Struct": {}}
            st = entry["Struct"]

        # FirstCodeName_0
        st.setdefault("FirstCodeName_0", {"tag": {"data": {"Other": "NameProperty"}}})
        st["FirstCodeName_0"]["Name"] = canonical
        st["FirstCodeName_0"].setdefault("tag", {"data": {"Other": "NameProperty"}})

        # Count_0: preserve template kind if possible
        cur, kind = self._read_count_and_kind(st)
        # If template had no Count_0, default to Int
        if kind not in ("Int", "Int64"):
            kind = "Int"
        self._write_count_with_kind(st, 1, kind)

        # Ensure equip slot enum exists and is NONE
        st.setdefault(
            "EquipItemSlotType_0",
            {"tag": {"data": {"Enum": ["ELEquipSlotType", None]}}, "Enum": "ELEquipSlotType::E_NONE"},
        )
        st["EquipItemSlotType_0"]["Enum"] = "ELEquipSlotType::E_NONE"
        st["EquipItemSlotType_0"]["tag"] = {"data": {"Enum": ["ELEquipSlotType", None]}}

        # If template uses UniqueId_0 for this struct shape, make it unique.
        if "UniqueId_0" in st and isinstance(st.get("UniqueId_0"), dict):
            st["UniqueId_0"].clear()
            st["UniqueId_0"]["Int"] = self._next_unique_id(items)
            st["UniqueId_0"]["tag"] = {"data": {"Other": "IntProperty"}}

        # This is not an assembled weapon/build
        if "bIsWeapon_0" in st and isinstance(st.get("bIsWeapon_0"), dict):
            st["bIsWeapon_0"].clear()
            st["bIsWeapon_0"]["Bool"] = False
            st["bIsWeapon_0"]["tag"] = {"data": {"Other": "BoolProperty"}}

        # Remove any second-code remnants from templates (builds)
        if "SecondCodeName_0" in st:
            # For normal inventory rows, we do not want a second code.
            try:
                del st["SecondCodeName_0"]
            except Exception:
                pass

        return entry
    def _canonical_id_for(self, norm: str, raw: str) -> str:
        return self._canon_by_norm.get(norm, raw)

    def _add_item(self, code: str) -> None:
        if not self.data:
            return
        cat = self._category_for_ingame(code)
        # Only create simple inventory entries here
        if cat not in ("Consumables", "Materials", "Keys/Lore", "Cosmetics"):
            QMessageBox.information(self, "Add Item",
                "This entry isn’t a normal inventory item and can’t be added here.")
            return

        norm = _norm_code(code)
        try:
            items = self._ensure_items_array()
        except Exception:
            QMessageBox.warning(self, "Add Item", "Could not access inventory list.")
            return

        # Merge if an identical non-build exists
        for e in items:
            code0 = _norm_code(e.get("Struct", {}).get("FirstCodeName_0", {}).get("Name", ""))
            if code0 == norm and not self._is_build_struct(e.get("Struct", {})):
                st_e = e["Struct"]
                cur, kind = self._read_count_and_kind(st_e)
                newv = (1 if int(cur) < 1 else int(cur) + 1)
                self._write_count_with_kind(st_e, newv, kind)
                self._refresh_inv_list(); self._dedupe_inventory_in_place(); self._rebuild_all_views()
                return

        canonical = self._canonical_id_for(norm, code)
        items.append(self._make_inventory_entry(items, canonical))
        self._refresh_inv_list(); self._dedupe_inventory_in_place(); self._rebuild_all_views()

    def _add_items_batch(self, codes: List[str]) -> None:
        if not self.data:
            return
        try:
            items = self._ensure_items_array()
        except Exception:
            QMessageBox.warning(self, "Add Items", "Could not access inventory list.")
            return

        have_norm = {_norm_code(e.get("Struct", {}).get("FirstCodeName_0", {}).get("Name", "")) for e in items if not self._is_build_struct(e.get("Struct", {}))}
        for code in codes:
            cat = self._category_for_ingame(code)
            if cat not in ("Consumables", "Materials", "Keys/Lore", "Cosmetics"):
                continue  # skip non-inventory tokens in bulk add
            n = _norm_code(code)
            if not n:
                continue
            if n in have_norm:
                for e in items:
                    if _norm_code(e.get("Struct", {}).get("FirstCodeName_0", {}).get("Name", "")) == n and not self._is_build_struct(e.get("Struct", {})):
                        st_e = e["Struct"]
                        cur, kind = self._read_count_and_kind(st_e)
                        newv = (1 if int(cur) < 1 else int(cur) + 1)
                        self._write_count_with_kind(st_e, newv, kind)
                        break
                continue
            canonical = self._canonical_id_for(n, code)
            items.append(self._make_inventory_entry(items, canonical))
            have_norm.add(n)
            self._refresh_inv_list(); self._dedupe_inventory_in_place(); self._rebuild_all_views()

    # ---------- raw access helpers (export/import) ----------
    def _iter_items(self):
        try:
            return self._ensure_items_array()
        except Exception:
            return []

    def _read_count_and_kind(self, st: Dict[str, Any]) -> tuple[int, str]:
        c = st.get("Count_0", {})
        if "Int64" in c:
            try: return int(c.get("Int64") or 0), "Int64"
            except Exception: return 0, "Int64"
        try: return int(c.get("Int") or 0), "Int"
        except Exception: return 0, "Int"

    def _slot_enum(self, st: Dict[str, Any]) -> str:
        for v in st.values():
            if isinstance(v, dict) and isinstance(v.get("Enum"), str) and v["Enum"].startswith("ELEquipSlotType::"):
                return v["Enum"]
        return "ELEquipSlotType::E_NONE"

    def _write_count_with_kind(self, st: Dict[str, Any], value: int, kind: str):
        node = st.setdefault("Count_0", {}); node.clear()
        if str(kind).lower() == "int64":
            node["Int64"] = int(value); node["tag"] = {"data": {"Other": "Int64Property"}}
        else:
            node["Int"] = int(value); node["tag"] = {"data": {"Other": "IntProperty"}}

    # ---------- Export (JSON only) ----------
    def _export_inventory_dialog(self):
        if not self.data:
            QMessageBox.warning(self, "Export", "No save loaded.")
        else:
            path, _ = QFileDialog.getSaveFileName(self, "Export Inventory JSON", "", "JSON (*.json)")
            if not path:
                return
            if not path.lower().endswith(".json"):
                path += ".json"
            self._export_inventory_json(path)

    def _export_inventory_json(self, path: str) -> None:
        out = []
        for e in self._iter_items():
            st = e.get("Struct", {})
            item = {
                "code": (st.get("FirstCodeName_0", {}) or {}).get("Name", ""),
                "second_code": (st.get("SecondCodeName_0", {}) or {}).get("Name", ""),
                "slot": self._slot_enum(st),
            }
            cnt, kind = self._read_count_and_kind(st)
            item["count"] = cnt
            item["count_type"] = kind
            out.append(item)
        payload = {"format": "lop-inventory-v1", "items": out}
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)

    # ---------- Import (JSON only) ----------
    def _import_inventory_dialog(self):
        if not self.data:
            QMessageBox.warning(self, "Import", "No save loaded.")
            return
        path, _ = QFileDialog.getOpenFileName(self, "Import Inventory JSON", "", "JSON (*.json)")
        if not path:
            return

        replace = QMessageBox.question(
            self, "Import Behavior",
            "Replace all current inventory with the imported items?\n\n"
            "Choose 'No' to merge & sum counts.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        ) == QMessageBox.StandardButton.Yes

        try:
            self._backup_current_save_if_possible()
            self._import_inventory_json(path, replace=replace)
            self._refresh_inv_list()
            self._dedupe_inventory_in_place()
            self._rebuild_all_views()
            QMessageBox.information(self, "Import", "Inventory imported successfully.")
        except Exception as e:
            QMessageBox.critical(self, "Import Failed", str(e))

    def _backup_current_save_if_possible(self):
        try:
            save_path = getattr(self.main_window, "current_save_path", None)
            if save_path and os.path.exists(save_path):
                import shutil
                shutil.copy2(save_path, save_path + ".bak")
        except Exception:
            pass

    def _import_inventory_json(self, path: str, *, replace: bool):
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        items = data.get("items", [])
        if not isinstance(items, list):
            raise ValueError("Invalid JSON: 'items' must be a list.")
        arr = self._ensure_items_array()
        if replace:
            arr[:] = []

        # Build an index of existing items
        by_key: Dict[tuple, Dict[str, Any]] = {}
        for e in arr:
            by_key[self._dedupe_key_for_entry(e)] = e

        for it in items:
            code = (it.get("code") or "").strip()
            if not code:
                continue
            ncode = _norm_code(code)
            canonical = self._canon_by_norm.get(ncode, code)
            second = (it.get("second_code") or "").strip()
            cnt = int(it.get("count") or 0)
            kind = (it.get("count_type") or "Int").strip()
            slot = (it.get("slot") or "ELEquipSlotType::E_NONE").strip()

            # Decide import key: if second_code present => treat as build
            if second:
                key = ("build", _norm_code(canonical), _norm_code(second), None)
            else:
                key = ("code", _norm_code(canonical))

            found = by_key.get(key)

            if found is None:
                # Create a new row
                st: Dict[str, Any] = {}
                st.setdefault("FirstCodeName_0", {"tag": {"data": {"Other": "NameProperty"}}})["Name"] = canonical
                if second:
                    st.setdefault("SecondCodeName_0", {"tag": {"data": {"Other": "NameProperty"}}})["Name"] = second
                    st.setdefault("bIsWeapon_0", {"tag": {"data": {"Other": "BoolProperty"}}})["Bool"] = True
                self._write_count_with_kind(st, cnt, kind)
                if slot and slot.startswith("ELEquipSlotType::"):
                    st.setdefault("EquipItemSlotType_0",
                        {"tag": {"data": {"Enum": ["ELEquipSlotType", None]}}, "Enum": "ELEquipSlotType::E_NONE"})["Enum"] = slot
                entry = {"Struct": st}
                arr.append(entry)
                by_key[key] = entry
            else:
                # Existing entry with same key → merge counts (preserve kind)
                st = found.get("Struct", {})
                cur, cur_kind = self._read_count_and_kind(st)
                newv = max(0, cur) + max(0, cnt)
                if cur_kind == "Int" and newv > 2_147_483_647:
                    cur_kind = "Int64"
                self._write_count_with_kind(st, newv, cur_kind)
                if slot.startswith("ELEquipSlotType::"):
                    existing_slot = self._slot_enum(st)
                    if existing_slot.endswith("E_NONE"):
                        st.setdefault("EquipItemSlotType_0",
                            {"tag": {"data": {"Enum": ["ELEquipSlotType", None]}}, "Enum": "ELEquipSlotType::E_NONE"})["Enum"] = slot

    # ---------- restore focus ----------
    def _restore_focus_if_any(self) -> None:
        title = self._restore_tab_title
        if not title:
            return
        for i in range(self.tabs.count()):
            if self.tabs.tabText(i) == title:
                self.tabs.setCurrentIndex(i)
                if title == "Missing" and isinstance(self._restore_missing_row, int):
                    r = min(max(self._restore_missing_row, 0), self.tbl_missing.rowCount() - 1)
                    if r >= 0:
                        self.tbl_missing.selectRow(r)
                break
        self._restore_tab_title = None
        self._restore_missing_row = None
