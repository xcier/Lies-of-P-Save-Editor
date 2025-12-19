from __future__ import annotations
from typing import Any, Dict, List, Set, Optional
import json, datetime

from PyQt6.QtCore import Qt, QTimer, QEvent
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLineEdit, QPushButton,
    QTableWidget, QTableWidgetItem, QComboBox, QMessageBox, QLabel,
    QHeaderView, QSpinBox, QFileDialog
)

from app.core.mission import (
    discover_quests, apply_quest_edit, QUEST_STATES,
    replace_quest_by_name_smart
)

# ---------- state labels ----------
ENUM_TO_FRIENDLY = {
    "E_COMPLETE_SUCCESS": "Complete Success",
    "E_COMPLETE_FAIL":    "Complete Fail",
    "E_IN_PROGRESS":      "In Progress",
    "E_INACTIVE":         "Inactive",
}
FRIENDLY_TO_ENUM = {
    "complete success": "E_COMPLETE_SUCCESS",
    "complete fail":    "E_COMPLETE_FAIL",
    "in progress":      "E_IN_PROGRESS",
    "inactive":         "E_INACTIVE",
}


def _normalize_enum(s: str) -> str:
    s = (s or "").strip()
    return s.replace("::", "_").replace("-", "_").replace(" ", "_").upper()


def _to_friendly_label(raw: str) -> str:
    s = _normalize_enum(raw)
    for key, friendly in ENUM_TO_FRIENDLY.items():
        if s == key or s.endswith("_" + key) or s.endswith(key):
            return friendly
    return raw




def _to_save_state(existing_raw: str, enum_code: str) -> str:
    # Convert enum suffix like 'E_IN_PROGRESS' into the same on-disk style the save already uses.
    # Common styles seen:
    #   - 'ELQuestState::E_IN_PROGRESS'   (UE enum string)
    #   - 'E_IN_PROGRESS'                (suffix only)
    #   - 'ELQUESTSTATE_E_IN_PROGRESS'   (normalized/legacy)
    raw = (existing_raw or "").strip()
    enum_code = (enum_code or "").strip()
    if not enum_code:
        return raw

    # Prefer preserving UE-style prefix if present.
    if "::" in raw:
        prefix = raw.split("::", 1)[0].strip() or "ELQuestState"
        return f"{prefix}::{enum_code}"

    # If it looks like a normalized enum, restore to UE-style.
    upper = raw.upper()
    if upper.startswith("ELQUESTSTATE_") or "ELQUESTSTATE" in upper:
        return f"ELQuestState::{enum_code}"

    # Otherwise, keep suffix-only.
    return enum_code


class MissionTab(QWidget):
    COL_NAME = 0
    COL_STATE = 1
    COL_PROGRESS = 2

    def __init__(self, parent=None):
        super().__init__(parent)
        self._data: Optional[Dict[str, Any]] = None
        self._rows: List[Dict[str, Any]] = []
        self._auto_scanned_once = False  # run when the tab first becomes visible
        self._state_display: List[str] = list(QUEST_STATES)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)

        # Controls
        controls = QHBoxLayout()
        self.filter_edit = QLineEdit(self)
        self.filter_edit.setPlaceholderText("Filter…")
        self.btn_rescan = QPushButton("Rescan", self)
        self.btn_inprog = QPushButton("Mark In Progress", self)
        self.btn_done = QPushButton("Mark Completed", self)
        self.btn_export = QPushButton("Export Quest Data", self)
        self.btn_import = QPushButton("Import Quest Data", self)
        self.count_lbl = QLabel("0 quests", self)
        self.count_lbl.setMinimumWidth(120)

        for w in (
            self.filter_edit,
            self.btn_rescan,
            self.btn_inprog,
            self.btn_done,
            self.btn_export,
            self.btn_import,
            self.count_lbl,
        ):
            controls.addWidget(w)
        outer.addLayout(controls)

        # Table
        self.table = QTableWidget(self)
        self.table.setAlternatingRowColors(True)
        self.table.setColumnCount(3)
        self.table.setHorizontalHeaderLabels(["Name", "State", "Progress Objects / Value"])
        self.table.horizontalHeader().setSectionResizeMode(self.COL_NAME, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(self.COL_STATE, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(self.COL_PROGRESS, QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.ExtendedSelection)
        outer.addWidget(self.table)

        # Signals
        self.filter_edit.textChanged.connect(self._refilter)
        self.btn_rescan.clicked.connect(self._rescan)
        self.btn_inprog.clicked.connect(lambda: self._bulk_set_state_selected("In Progress"))
        self.btn_done.clicked.connect(lambda: self._bulk_set_state_selected("Complete Success"))
        self.btn_export.clicked.connect(self._export_quests)
        self.btn_import.clicked.connect(self._import_quests)
        # Lazy-create progress editors on demand
        self.table.cellDoubleClicked.connect(self._on_cell_double_clicked)

        # Auto-scan on first show
        self.installEventFilter(self)

    # ---------------- Public API ----------------
    def set_data(self, json_data: Dict[str, Any]):
        """
        Called when a new save is loaded.

        We just store the data and reset our 'auto scanned' flag.
        The actual scan happens lazily when the tab is first shown
        (eventFilter), or when the user presses 'Rescan'.
        """
        self._data = json_data
        self._rows = []
        self._auto_scanned_once = False
        self.count_lbl.setText("0 quests")
        self.table.clearContents()
        self.table.setRowCount(0)

    def load_data(self, json_data: Dict[str, Any], *args, **kwargs):
        self.set_data(json_data)

    # Trigger an automatic scan the first time the tab becomes visible
    def eventFilter(self, obj, ev):
        if (
            obj is self
            and ev.type() == QEvent.Type.Show
            and self._data
            and not self._auto_scanned_once
        ):
            self._auto_scanned_once = True
            # Slight delay so the UI paints before the scan
            QTimer.singleShot(0, self._rescan)
        return super().eventFilter(obj, ev)

    # ---------------- Internal helpers ----------------
    def _rescan(self):
        if not self._data:
            return

        # preserve viewport & selection
        top_row = self.table.rowAt(0)
        selected_names: Set[str] = set()
        if self.table.selectionModel():
            for idx in self.table.selectionModel().selectedRows():
                item = self.table.item(idx.row(), self.COL_NAME)
                selected_names.add((item or QTableWidgetItem("")).text())

        self.table.setUpdatesEnabled(False)
        try:
            rows, meta = discover_quests(self._data)
            self._rows = rows
            extra = f"  (source: {meta[0][0]})" if meta else ""
            self.count_lbl.setText(f"{len(rows)} quests{extra}")

            # Build unique friendly state list (for combos)
            enums_seen: Set[str] = set()
            for r in rows:
                friendly = _to_friendly_label(str(r.get("state") or ""))
                enums_seen.add(friendly)
            display = [
                s
                for s in ["In Progress", "Complete Success", "Complete Fail", "Inactive"]
                if s in enums_seen
            ]
            if not display:
                display = list(QUEST_STATES)
            self._state_display = display

            # Rebuild table quickly
            self.table.clearContents()
            self.table.setRowCount(len(rows))

            for r, row in enumerate(rows):
                # Mark that this row does not yet have a heavy progress editor
                row["_has_editor"] = False

                # Name
                name_item = QTableWidgetItem(row.get("name") or "")
                self.table.setItem(r, self.COL_NAME, name_item)

                # State combo
                state_combo = QComboBox(self)
                for s in self._state_display:
                    state_combo.addItem(s)
                state_combo.setCurrentText(_to_friendly_label(str(row.get("state") or "")))
                # Capture row index via default arg
                state_combo.currentTextChanged.connect(
                    lambda friendly, rr=r: self._apply_state_change(rr, friendly)
                )
                self.table.setCellWidget(r, self.COL_STATE, state_combo)

                # Progress (lazy — only build widgets when user opens it)
                progress_objects = row.get("progress_objects") or []
                if not progress_objects:
                    msg = QTableWidgetItem("No numeric progress values")
                    msg.setFlags(msg.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    self.table.setItem(r, self.COL_PROGRESS, msg)
                else:
                    placeholder = QTableWidgetItem(
                        f"{len(progress_objects)} progress entrie(s) — double-click to edit"
                    )
                    placeholder.setFlags(placeholder.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    self.table.setItem(r, self.COL_PROGRESS, placeholder)

            self._refilter()

            # restore selection & scroll
            if selected_names:
                sm = self.table.selectionModel()
                for r in range(self.table.rowCount()):
                    namev = (self.table.item(r, self.COL_NAME) or QTableWidgetItem("")).text()
                    if namev in selected_names:
                        self.table.selectRow(r)
            if top_row >= 0 and self.table.rowCount() > 0:
                self.table.scrollToItem(
                    self.table.item(min(top_row, self.table.rowCount() - 1), self.COL_NAME)
                )
        finally:
            self.table.setUpdatesEnabled(True)

    def _ensure_progress_editor(self, row_idx: int):
        """
        Create the heavy progress editor (combo + spinbox) for a row the first
        time the user opens it. Subsequent calls are cheap no-ops.
        """
        if not (0 <= row_idx < len(self._rows)):
            return
        row = self._rows[row_idx]

        # Already has a widget?
        if row.get("_has_editor"):
            return
        if self.table.cellWidget(row_idx, self.COL_PROGRESS) is not None:
            row["_has_editor"] = True
            return

        progress_objects = row.get("progress_objects") or []
        if not progress_objects:
            return

        container = QWidget(self)
        hl = QHBoxLayout(container)
        hl.setContentsMargins(0, 0, 0, 0)

        obj_combo = QComboBox(container)
        val_spin = QSpinBox(container)
        val_spin.setMinimum(-2_147_483_648)
        val_spin.setMaximum(2_147_483_647)

        for obj in progress_objects:
            obj_combo.addItem(str(obj.get("label", "")), obj)

        def sync_spin(ix: int, rr=row_idx, combo=obj_combo, spin=val_spin):
            d = combo.itemData(ix)
            if isinstance(d, dict):
                try:
                    spin.blockSignals(True)
                    spin.setValue(int(d.get("value", 0)))
                finally:
                    spin.blockSignals(False)

        obj_combo.currentIndexChanged.connect(sync_spin)

        def on_spin_changed(_val: int, rr=row_idx, combo=obj_combo, spin=val_spin):
            d = combo.currentData()
            if isinstance(d, dict) and d.get("path_abs") is not None:
                apply_quest_edit(
                    self._data,
                    self._rows[rr],
                    new_state=None,
                    new_progress=int(spin.value()),
                    progress_path_override=d["path_abs"],
                )
                d["value"] = int(spin.value())

        val_spin.valueChanged.connect(on_spin_changed)

        if obj_combo.count() > 0:
            obj_combo.setCurrentIndex(0)
            sync_spin(0)
        else:
            obj_combo.setEnabled(False)
            val_spin.setEnabled(False)
            obj_combo.setToolTip("No int values found in arrays for this quest.")

        hl.addWidget(obj_combo, 2)
        hl.addWidget(val_spin, 1)
        container.setLayout(hl)
        self.table.setCellWidget(row_idx, self.COL_PROGRESS, container)

        # Clear the placeholder item
        self.table.takeItem(row_idx, self.COL_PROGRESS)
        row["_has_editor"] = True

    def _on_cell_double_clicked(self, row: int, col: int):
        if col == self.COL_PROGRESS:
            self._ensure_progress_editor(row)

    def _refilter(self):
        needle = self.filter_edit.text().strip().lower()
        if not needle:
            for r in range(self.table.rowCount()):
                self.table.setRowHidden(r, False)
            return

        for r in range(self.table.rowCount()):
            item = self.table.item(r, self.COL_NAME)
            namev = (item or QTableWidgetItem("")).text().lower()
            self.table.setRowHidden(r, needle not in namev)

    # ---------- Write-through helpers ----------
    def _apply_state_change(self, row_idx: int, friendly_label: str):
        if not (0 <= row_idx < len(self._rows)):
            return
        # Map friendly -> enum suffix
        enum_suffix = FRIENDLY_TO_ENUM.get(friendly_label.lower(), friendly_label)
        # Preserve whatever enum string style the save already uses for this row
        existing_raw = str(self._rows[row_idx].get("state") or "")
        new_state = _to_save_state(existing_raw, enum_suffix)
        apply_quest_edit(self._data, self._rows[row_idx], new_state=new_state)
        self._rows[row_idx]["state"] = new_state

    def _selected_rows(self) -> List[int]:
        if not self.table.selectionModel():
            return []
        return sorted({ix.row() for ix in self.table.selectionModel().selectedRows()})

    def _bulk_set_state_selected(self, friendly_label: str):
        # Just drive the combos; they will call _apply_state_change.
        for r in self._selected_rows():
            combo = self.table.cellWidget(r, self.COL_STATE)
            if isinstance(combo, QComboBox) and combo.currentText() != friendly_label:
                combo.setCurrentText(friendly_label)

    # ---------- Export / Import ----------
    def _export_quests(self):
        if not self._rows:
            QMessageBox.information(self, "Export Quest Data", "No quests to export.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Quest Data",
            "quest_export.json",
            "JSON Files (*.json)",
        )
        if not path:
            return
        payload = {
            "version": 5,
            "mode": "match_by_name_smart",
            "exported_at": datetime.datetime.now().isoformat(timespec="seconds"),
            "rows": [],
        }
        for row in self._rows:
            row_out = {
                "name": row.get("name") or "",
                "state": _normalize_enum(str(row.get("state") or "")),
                "progress": [],
            }
            for obj in (row.get("progress_objects") or []):
                row_out["progress"].append(
                    {
                        "label": str(obj.get("label", "")),
                        "value": int(obj.get("value", 0)),
                        "path_abs": obj.get("path_abs"),
                        "sig": str(obj.get("sig", "")),
                    }
                )
            payload["rows"].append(row_out)
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2, ensure_ascii=False)
            QMessageBox.information(
                self, "Export Quest Data", f"Exported {len(self._rows)} quests to:\n{path}"
            )
        except Exception as e:
            QMessageBox.critical(self, "Export Quest Data", f"Failed to export:\n{e}")

    def _import_quests(self):
        if not self._data:
            QMessageBox.information(self, "Import Quest Data", "No save is loaded.")
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "Import Quest Data", "", "JSON Files (*.json)"
        )
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                payload = json.load(f)
        except Exception as e:
            QMessageBox.critical(self, "Import Quest Data", f"Failed to read file:\n{e}")
            return

        rows_in = payload.get("rows", [])
        if not isinstance(rows_in, list) or not rows_in:
            QMessageBox.information(
                self, "Import Quest Data", "No rows found in the import file."
            )
            return

        applied_rows, applied_progress = replace_quest_by_name_smart(self._data, rows_in)

        # Immediately refresh UI so values are visible without pressing Rescan
        self._rescan()

        QMessageBox.information(
            self,
            "Import Quest Data",
            f"Updated quests by name.\nRows updated: {applied_rows}\n"
            f"Progress values set: {applied_progress}",
        )
