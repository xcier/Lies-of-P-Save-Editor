from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QTableWidget, QTableWidgetItem,
    QMessageBox, QLineEdit, QComboBox
)

from app.core.quartz import (
    find_quartz_struct,
    ensure_quartz_struct,
    get_effect_list,
    build_index_map,
    make_effect_struct,
    load_defaults_db,
    save_defaults_db,
    merge_defaults_db,
    derive_defaults_from_quartz,
)

def _pocket_sort_key(p: str) -> Tuple[int, str]:
    # QuartzPocket_12 -> (12, p)
    try:
        n = int(p.split("_")[-1])
        return (n, p)
    except Exception:
        return (10**9, p)

@dataclass
class QuartzRow:
    pocket: str
    slot: int
    effect: str
    in_save: bool

class QuartzTab(QWidget):
    """
    Behavior:
    - Load any save -> table shows a *full grid* based on defaults DB if present,
      otherwise based on pockets/slots observed in the save.
    - "Save Defaults" stores the currently-loaded save's quartz list into quartz_defaults.json
      (this is the 'golden save' workflow).
    - Load a fresh save -> table still shows full grid (from defaults DB), rows missing from save marked In Save = No.
    - "Add Missing Slots" writes ALL missing rows (that have a defaults effect) into the save JSON.
    - "Add Selected to Save" adds only selected missing rows.
    - "Remove Selected from Save" removes selected rows that are currently present in save.
    """

    def __init__(self, file_ctx, parent=None):
        super().__init__(parent)
        self.file_ctx = file_ctx
        self._rows: List[QuartzRow] = []
        self._defaults: Dict[str, Dict[str, str]] = {}
        self._filter_text: str = ""
        self._filter_mode: str = "All"  # All / In Save / Missing
        self._build_ui()

    # ---------------- UI ----------------

    def _build_ui(self):
        root = QVBoxLayout(self)
        header = QHBoxLayout()

        self.btn_refresh = QPushButton("Refresh from Save")
        self.btn_refresh.clicked.connect(self._refresh_from_save)

        self.btn_add_missing = QPushButton("Add Missing Slots")
        self.btn_add_missing.clicked.connect(self._add_missing_slots)

        self.btn_save_defaults = QPushButton("Save Defaults")
        self.btn_save_defaults.clicked.connect(self._save_defaults_from_current)

        self.btn_merge_defaults = QPushButton("Merge Defaults (Current Save)")
        self.btn_merge_defaults.clicked.connect(self._merge_defaults_from_current)

        self.btn_add_selected = QPushButton("Add Selected to Save")
        self.btn_add_selected.clicked.connect(self._add_selected)

        self.btn_remove_selected = QPushButton("Remove Selected from Save")
        self.btn_remove_selected.clicked.connect(self._remove_selected)

        header.addWidget(QLabel("Quartz"))

        # --- filters ---
        self.search = QLineEdit(self)
        self.search.setPlaceholderText("Search pocket / effect…")
        self.search.textChanged.connect(self._on_filter_changed)

        self.cmb_mode = QComboBox(self)
        self.cmb_mode.addItems(["All", "In Save", "Missing"])
        self.cmb_mode.currentTextChanged.connect(self._on_filter_changed)

        header.addStretch(1)
        header.addWidget(self.search)
        header.addWidget(self.cmb_mode)
        header.addWidget(self.btn_refresh)
        header.addStretch(1)
        header.addWidget(self.btn_add_missing)
        header.addWidget(self.btn_save_defaults)
        header.addWidget(self.btn_merge_defaults)
        header.addWidget(self.btn_add_selected)
        header.addWidget(self.btn_remove_selected)

        root.addLayout(header)

        self.tbl = QTableWidget(0, 4, self)
        self.tbl.setHorizontalHeaderLabels(["Pocket", "Slot", "Effect Code", "In Save"])
        self.tbl.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.tbl.setSelectionMode(QTableWidget.SelectionMode.ExtendedSelection)
        self.tbl.horizontalHeader().setStretchLastSection(True)
        self.tbl.itemDoubleClicked.connect(self._toggle_selected)
        root.addWidget(self.tbl, 1)

    # ---------------- Data plumbing ----------------

    def _load_root_json(self) -> Optional[Dict[str, Any]]:
        # file_ctx is your existing project context; it should provide a root json/dict
        # Most of your tabs use file_ctx.data or file_ctx.root; try a few common names.
        for attr in ("data", "root", "json", "parsed", "save_json"):
            obj = getattr(self.file_ctx, attr, None)
            if isinstance(obj, dict):
                return obj
        # maybe file_ctx has get_root_json()
        fn = getattr(self.file_ctx, "get_root_json", None)
        if callable(fn):
            try:
                v = fn()
                if isinstance(v, dict):
                    return v
            except Exception:
                pass
        return None

    def _set_status(self, msg: str):
        # optional: if your project has a status bar hook, this keeps it silent otherwise
        fn = getattr(self.parent(), "set_status", None)
        if callable(fn):
            try:
                fn(msg)
            except Exception:
                pass

    def _build_grid_spec(self, quartz_struct: Dict[str, Any], index: Dict[Tuple[str, int], Dict[str, Any]]) -> List[Tuple[str, int, str, bool]]:
        """
        Decide which pockets/slots should be displayed.
        Priority:
        1) defaults DB, if present -> show everything in defaults DB
        2) otherwise derive from current save -> show pockets and slot indices observed
        """
        spec: List[Tuple[str, int, str, bool]] = []

        if self._defaults:
            pockets = sorted(self._defaults.keys(), key=_pocket_sort_key)
            for p in pockets:
                slots = self._defaults.get(p, {})
                for s_str, eff in sorted(slots.items(), key=lambda kv: int(kv[0]) if str(kv[0]).isdigit() else 10**9):
                    try:
                        s = int(s_str)
                    except Exception:
                        continue
                    in_save = (p, s) in index
                    # show defaults effect if missing, else read from save
                    if in_save:
                        e = index[(p, s)]
                        eff_saved = (e.get("QuartzEffectCodename_0") or {}).get("Name", "")
                        eff = eff_saved if isinstance(eff_saved, str) else eff
                    spec.append((p, s, eff or "", in_save))
            return spec

        # no defaults -> build from save contents
        pockets = sorted({p for (p, _s) in index.keys()}, key=_pocket_sort_key)
        for p in pockets:
            slots = sorted({s for (pp, s) in index.keys() if pp == p})
            for s in slots:
                e = index[(p, s)]
                eff = (e.get("QuartzEffectCodename_0") or {}).get("Name", "")
                spec.append((p, s, eff if isinstance(eff, str) else "", True))
        return spec

    def _render(self):
        self.tbl.setRowCount(0)
        self.tbl.setRowCount(len(self._rows))
        for r, row in enumerate(self._rows):
            it_p = QTableWidgetItem(row.pocket)
            it_s = QTableWidgetItem(str(row.slot))
            it_e = QTableWidgetItem(row.effect)
            it_in = QTableWidgetItem("Yes" if row.in_save else "No")

            it_p.setFlags(it_p.flags() & ~Qt.ItemFlag.ItemIsEditable)
            it_s.setFlags(it_s.flags() & ~Qt.ItemFlag.ItemIsEditable)
            it_in.setFlags(it_in.flags() & ~Qt.ItemFlag.ItemIsEditable)

            # allow editing effect code only when it's NOT in save (so you can override before adding)
            if row.in_save:
                it_e.setFlags(it_e.flags() & ~Qt.ItemFlag.ItemIsEditable)

            self.tbl.setItem(r, 0, it_p)
            self.tbl.setItem(r, 1, it_s)
            self.tbl.setItem(r, 2, it_e)
            self.tbl.setItem(r, 3, it_in)

        self.tbl.resizeColumnsToContents()
        self._apply_filters()

    def _get_selected_row_idxs(self) -> List[int]:
        idxs = set()
        for it in self.tbl.selectedItems():
            idxs.add(it.row())
        return sorted(idxs)

    def _on_filter_changed(self, *_):
        self._filter_text = (self.search.text() or "").strip().lower() if hasattr(self, "search") else ""
        self._filter_mode = self.cmb_mode.currentText() if hasattr(self, "cmb_mode") else "All"
        self._apply_filters()

    def _apply_filters(self):
        ft = (self._filter_text or "").strip()
        mode = self._filter_mode or "All"

        for r, row in enumerate(self._rows):
            show = True

            if ft:
                hay = f"{row.pocket} {row.effect}".lower()
                if ft not in hay:
                    show = False

            if mode == "In Save" and not row.in_save:
                show = False
            elif mode == "Missing" and row.in_save:
                show = False

            self.tbl.setRowHidden(r, not show)


    
    def load_data(self, data: Dict[str, Any]):
        """Called by MainWindow after a save is loaded."""
        try:
            self._refresh_from_save(silent=True)
        except TypeError:
            self._refresh_from_save()

# ---------------- Actions ----------------

    def _refresh_from_save(self, silent: bool = False):
        root = self._load_root_json()
        if not root:
            QMessageBox.warning(self, "Quartz", "No save is loaded.")
            return

        # load defaults DB every refresh (so workflow: load golden, save defaults; load fresh, refresh)
        self._defaults = load_defaults_db(getattr(self.file_ctx, "app_dir", None))

        quartz_struct = find_quartz_struct(root)
        if not quartz_struct:
            # If QuartzData_0 is missing entirely, we still show the defaults grid (if exists)
            if self._defaults:
                self._rows = [QuartzRow(p, int(s), eff, False)
                              for p, slots in sorted(self._defaults.items(), key=lambda kv: _pocket_sort_key(kv[0]))
                              for s, eff in sorted(slots.items(), key=lambda kv: int(kv[0]))]
                self._render()
                return
            if not silent:
                QMessageBox.warning(self, "Quartz", "QuartzData_0 not found in this save.")
            return

        entries = get_effect_list(quartz_struct, create=False)
        index = build_index_map(entries)

        spec = self._build_grid_spec(quartz_struct, index)
        self._rows = [QuartzRow(p, s, eff, in_save) for (p, s, eff, in_save) in spec]
        self._render()
        self._set_status(f"Quartz loaded: {len(entries)} entries, grid rows: {len(self._rows)}")

    def _save_defaults_from_current(self):
        root = self._load_root_json()
        if not root:
            QMessageBox.warning(self, "Quartz", "No save is loaded.")
            return
        quartz_struct = find_quartz_struct(root)
        if not quartz_struct:
            # create the quartz struct if missing
            quartz_struct = ensure_quartz_struct(root)
        # Save ONLY what's present in the current save into the user-overlay DB.
        # The builtin defaults remain canonical and keep the UI grid complete.
        db = derive_defaults_from_quartz(quartz_struct)
        path = save_defaults_db(db, getattr(self.file_ctx, "app_dir", None))
        self._defaults = load_defaults_db(getattr(self.file_ctx, "app_dir", None))
        QMessageBox.information(self, "Quartz", f"Defaults saved:\n{path}")
        self._refresh_from_save()

    def _merge_defaults_from_current(self):
        """Merge current save's quartz list into the defaults DB (non-destructive)."""
        root = self._load_root_json()
        if not root:
            QMessageBox.warning(self, "Quartz", "No save is loaded.")
            return

        quartz_struct = find_quartz_struct(root)
        if not quartz_struct:
            QMessageBox.warning(self, "Quartz", "QuartzData_0 not found in this save.")
            return

        app_dir = getattr(self.file_ctx, "app_dir", None)
        existing = load_defaults_db(app_dir)
        incoming = derive_defaults_from_quartz(quartz_struct)
        merged = merge_defaults_db(existing, incoming)
        # Persist merged overlay; builtin defaults remain canonical.
        path = save_defaults_db(merged, app_dir)
        self._defaults = load_defaults_db(app_dir)

        # Refresh view so merged defaults apply immediately.
        self._refresh_from_save()
        QMessageBox.information(self, "Quartz", f"Defaults merged and saved:\n{path}")

    def _add_missing_slots(self):
        # add ALL missing rows that have an effect code (prefer defaults; allow edited cell)
        self._apply_add(rows=self._missing_row_indices())

    def _missing_row_indices(self) -> List[int]:
        return [i for i, r in enumerate(self._rows) if not r.in_save and (r.effect or self._defaults.get(r.pocket, {}).get(str(r.slot), ""))]

    def _add_selected(self):
        idxs = self._get_selected_row_idxs()
        self._apply_add(rows=idxs)

    def _apply_add(self, rows: List[int]):
        root = self._load_root_json()
        if not root:
            QMessageBox.warning(self, "Quartz", "No save is loaded.")
            return
        quartz_struct = find_quartz_struct(root)
        if not quartz_struct:
            # create the quartz struct if missing
            quartz_struct = ensure_quartz_struct(root)

        # ensure effect list exists
        entries = get_effect_list(quartz_struct, create=True)
        index = build_index_map(entries)

        added = 0
        for i in rows:
            if i < 0 or i >= len(self._rows):
                continue
            row = self._rows[i]
            if row.in_save:
                continue

            # read effect from table first (user may have edited), else from defaults db
            it = self.tbl.item(i, 2)
            eff = it.text().strip() if it else ""
            if not eff:
                eff = (self._defaults.get(row.pocket, {}) or {}).get(str(row.slot), "").strip()
            if not eff:
                continue

            if (row.pocket, row.slot) in index:
                # already there (stale UI)
                row.in_save = True
                continue

            new_struct = make_effect_struct(row.pocket, row.slot, eff)
            # append as {"Struct": {...}} to match UE Save JSON layout
            wrap = {"Struct": new_struct}
            # write into underlying JSON list
            key = None
            # locate list node (create=True ensured it exists)
            k = "EffectSaveDataList_0"
            # find actual tail key if different
            for kk in quartz_struct.keys():
                if kk.split(".")[-1] == "EffectSaveDataList_0":
                    k = kk
                    break
            value_list = quartz_struct[k]["Array"]["Struct"]["value"]
            value_list.append(wrap)
            index[(row.pocket, row.slot)] = new_struct
            row.effect = eff
            row.in_save = True
            added += 1

        self._render()
        QMessageBox.information(self, "Quartz", f"Added {added} quartz slots to the save.\n(Write/save the file to persist changes.)")

    def _remove_selected(self):
        root = self._load_root_json()
        if not root:
            QMessageBox.warning(self, "Quartz", "No save is loaded.")
            return
        quartz_struct = find_quartz_struct(root)
        if not quartz_struct:
            # create the quartz struct if missing
            quartz_struct = ensure_quartz_struct(root)

        idxs = self._get_selected_row_idxs()
        if not idxs:
            return

        # pull underlying value list
        k = "EffectSaveDataList_0"
        for kk in quartz_struct.keys():
            if kk.split(".")[-1] == "EffectSaveDataList_0":
                k = kk
                break
        value_list = quartz_struct.get(k, {}).get("Array", {}).get("Struct", {}).get("value", [])
        if not isinstance(value_list, list):
            QMessageBox.warning(self, "Quartz", "Effect list is not a list in this save.")
            return

        # build a set of targets
        targets = {(self._rows[i].pocket, self._rows[i].slot) for i in idxs if 0 <= i < len(self._rows)}

        new_list = []
        removed = 0
        for it in value_list:
            st = it.get("Struct") if isinstance(it, dict) else None
            if not isinstance(st, dict):
                new_list.append(it)
                continue
            pocket = (st.get("QuartzPocketCodeName_0") or {}).get("Name")
            slot = (st.get("SlotIndex_0") or {}).get("Int")
            if isinstance(pocket, str) and isinstance(slot, int) and (pocket, slot) in targets:
                removed += 1
                continue
            new_list.append(it)

        quartz_struct[k]["Array"]["Struct"]["value"] = new_list

        # update rows UI
        for i in idxs:
            if 0 <= i < len(self._rows):
                self._rows[i].in_save = False
        self._render()
        QMessageBox.information(self, "Quartz", f"Removed {removed} quartz slots from the save.\n(Write/save the file to persist changes.)")

    def _toggle_selected(self, *_):
        """Double-click helper: toggle selected rows in/out of the save."""
        idxs = self._get_selected_row_idxs()
        if not idxs:
            return

        to_add = [i for i in idxs if 0 <= i < len(self._rows) and not self._rows[i].in_save]
        to_remove = [i for i in idxs if 0 <= i < len(self._rows) and self._rows[i].in_save]

        # Remove present entries first, then add missing ones.
        if to_remove:
            # Temporarily select only the rows we want to remove so we can reuse _remove_selected
            self.tbl.clearSelection()
            for i in to_remove:
                self.tbl.selectRow(i)
            self._remove_selected()

        if to_add:
            self._apply_add(rows=to_add)
