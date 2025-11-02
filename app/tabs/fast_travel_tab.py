from __future__ import annotations
from typing import Any, Dict, List, Optional, Union, Tuple, Set
import re

from PyQt6.QtCore import Qt, QTimer, QEvent
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QSplitter,
    QTableWidget, QTableWidgetItem, QHeaderView, QLineEdit, QLabel,
    QComboBox, QGroupBox, QFormLayout, QDoubleSpinBox, QSizePolicy,
    QPushButton, QCompleter, QScrollArea, QSpacerItem
)

JSON = Union[dict, list, str, int, float, bool, None]

# ---------------- tiny JSON helpers ----------------
def _lkeys(d: Dict[str, Any]) -> Dict[str, str]:
    return {k.lower(): k for k in d} if isinstance(d, dict) else {}

def _get(obj: JSON, path: List[Union[str, int]], default=None) -> JSON:
    cur = obj
    for p in path:
        if isinstance(cur, dict) and isinstance(p, str):
            cur = cur.get(p, default if p == path[-1] else None)
        elif isinstance(cur, list) and isinstance(p, int):
            if 0 <= p < len(cur):
                cur = cur[p]
            else:
                return default
        else:
            return default
        if cur is None:
            return default
    return cur

def _set(obj: JSON, path: List[Union[str, int]], val: Any) -> bool:
    if not path:
        return False
    cur = obj
    for p in path[:-1]:
        if isinstance(cur, dict) and isinstance(p, str):
            cur = cur.get(p)
        elif isinstance(cur, list) and isinstance(p, int):
            if 0 <= p < len(cur):
                cur = cur[p]
            else:
                return False
        else:
            return False
        if cur is None:
            return False
    last = path[-1]
    if isinstance(cur, dict) and isinstance(last, str):
        cur[last] = val
        return True
    if isinstance(cur, list) and isinstance(last, int) and 0 <= last < len(cur):
        cur[last] = val
        return True
    return False

def _unwrap(node: JSON, max_depth: int = 10) -> JSON:
    cur = node
    depth = 0
    while depth < max_depth and isinstance(cur, dict):
        if "Array" in cur and isinstance(cur["Array"], dict):
            a = cur["Array"]
            if isinstance(a.get("Struct"), dict) and isinstance(a["Struct"].get("value"), list):
                return a["Struct"]["value"]
            if isinstance(a.get("value"), list):
                return a["value"]
            cur = a
            depth += 1
            continue
        advanced = False
        for k in ("Struct", "value", "data", "tag"):
            lk = _lkeys(cur)
            if k.lower() in lk and isinstance(cur[lk[k.lower()]], (dict, list)):
                cur = cur[lk[k.lower()]]
                depth += 1
                advanced = True
                break
        if not advanced:
            break
    return cur

# ---------------- enum helpers ----------------
def _norm_enum(s: str) -> str:
    s = (s or "").strip()
    return s.replace("::","_").replace("-","_").replace(" ","_").upper()

def _retarget_enum_like(current_raw: Any, canonical_raw: Any) -> str:
    cur = _norm_enum("" if current_raw is None else str(current_raw))
    canon = _norm_enum("" if canonical_raw is None else str(canonical_raw))
    i = cur.find("E_")
    if i != -1:
        prefix = cur[:i]
        if prefix and not prefix.endswith("_"):
            prefix += "_"
        return prefix + canon
    return canon

def _friendly_state(raw: str) -> str:
    t = (raw or "").upper()
    if "E_NONE" in t:
        return "Locked"
    if "E_ACTIVE_IDLE" in t:
        return "Active (Idle)"
    if "E_ACTIVE" in t:
        return "Active"
    return raw or ""

FRIENDLY_TO_ENUM = {
    "Locked": "E_NONE",
    "Active (Idle)": "E_ACTIVE_IDLE",
    "Active": "E_ACTIVE",
}

# ---------------- labels ----------------
PREFIXES = ("LD_", "LV_")
def _pretty_code(code: str) -> str:
    s = (code or "").strip()
    for p in PREFIXES:
        if s.startswith(p):
            s = s[len(p):]
    s = s.replace("_", " ").strip()
    return re.sub(r"\s{2,}", " ", s)

class FastTravelTab(QWidget):
    """
    Teleport / Stargazer editor + player position/respawn editor.
    Has its own left table and right-side detail panel.
    """

    COL_NAME = 0
    COL_STATE = 1

    # --- Light/Dark styles ---------------------------------
    _DARK_QSS = """
        QGroupBox {
            border: 1px solid #3a3a3a;
            border-radius: 8px;
            margin-top: 8px;
        }
        QGroupBox::title {
            subcontrol-origin: margin;
            left: 10px;
            padding: 0px 4px;
        }
        QTableWidget {
            gridline-color: #444;
        }
        QComboBox, QLineEdit, QDoubleSpinBox {
            padding: 3px 6px;
        }
        QPushButton {
            padding: 6px 8px;
        }
    """

    _LIGHT_QSS = """
        QGroupBox {
            border: 1px solid #999;
            border-radius: 8px;
            margin-top: 8px;
        }
        QGroupBox::title {
            subcontrol-origin: margin;
            left: 10px;
            padding: 0px 4px;
        }
        QTableWidget {
            gridline-color: #bbb;
        }
        QComboBox, QLineEdit, QDoubleSpinBox {
            padding: 3px 6px;
        }
        QPushButton {
            padding: 6px 8px;
        }
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._data: Optional[Dict[str, Any]] = None
        self._rows: List[Dict[str, Any]] = []
        self._teleport_codes: List[str] = []
        self._all_levels: List[str] = []
        self._auto_loaded = False

        # --------- Root: splitter (big left, small right) ----------
        self.splitter = QSplitter(Qt.Orientation.Horizontal, self)
        left_panel  = QWidget()
        right_panel = QWidget()
        self.splitter.addWidget(left_panel)
        self.splitter.addWidget(right_panel)
        self.splitter.setChildrenCollapsible(False)

        outer = QHBoxLayout(self)
        outer.setContentsMargins(8,8,8,8)
        outer.addWidget(self.splitter)

        # ========== LEFT: Stargazers (dominant) ==========
        left_box = QGroupBox("Stargazers", left_panel)
        left_box.setMinimumWidth(580)  # wide & readable
        l_layout = QVBoxLayout(left_box)
        l_layout.setContentsMargins(10,8,10,8)

        self.filter_edit = QLineEdit(placeholderText="Filter by code or name…")
        l_layout.addWidget(self.filter_edit)

        self.table = QTableWidget(0, 2)
        self.table.setAlternatingRowColors(True)
        self.table.setHorizontalHeaderLabels(["Teleport / Stargazer", "State"])
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(self.COL_NAME,  QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(self.COL_STATE, QHeaderView.ResizeMode.ResizeToContents)
        self.table.setColumnWidth(self.COL_STATE, 140)
        self.table.verticalHeader().setDefaultSectionSize(30)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.ExtendedSelection)
        self.table.setTextElideMode(Qt.TextElideMode.ElideNone)
        self.table.setWordWrap(False)
        self.table.setHorizontalScrollMode(QTableWidget.ScrollMode.ScrollPerPixel)
        l_layout.addWidget(self.table, 1)

        lp_layout = QVBoxLayout(left_panel)
        lp_layout.setContentsMargins(0,0,0,0)
        lp_layout.addWidget(left_box)

        # ========== RIGHT: compact, scrollable editor ==========
        scroll = QScrollArea(right_panel)
        scroll.setWidgetResizable(True)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        editor = QWidget()
        editor.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        scroll.setWidget(editor)

        rp_layout = QVBoxLayout(right_panel)
        rp_layout.setContentsMargins(0,0,0,0)
        rp_layout.addWidget(scroll)

        editor_layout = QVBoxLayout(editor)
        editor_layout.setContentsMargins(6,6,6,6)
        editor_layout.setSpacing(8)

        # -- Player Location --
        box_loc = QGroupBox("Player Location")
        box_loc.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        form_loc = QFormLayout(box_loc)
        form_loc.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        self.cb_loc = QComboBox()
        self.cb_loc.setEditable(True)
        self._tune_combo(self.cb_loc)
        self.cb_lvl = QComboBox()
        self.cb_lvl.setEditable(True)
        self._tune_combo(self.cb_lvl)
        form_loc.addRow(QLabel("Latest Location"), self.cb_loc)
        form_loc.addRow(QLabel("Latest Level"),    self.cb_lvl)
        editor_layout.addWidget(box_loc)

        # -- Transform --
        box_tr  = QGroupBox("Transform")
        box_tr.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        form_tr = QFormLayout(box_tr)
        form_tr.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        form_tr.setHorizontalSpacing(10)
        form_tr.setVerticalSpacing(6)

        # compact spinboxes
        self.vx = self._num()
        self.vy = self._num()
        self.vz = self._num()
        self.qx = self._num()
        self.qy = self._num()
        self.qz = self._num()
        self.qw = self._num(default=1.0)
        for sp in (self.vx, self.vy, self.vz, self.qx, self.qy, self.qz, self.qw):
            sp.setMinimumWidth(120)
            sp.setMaximumWidth(160)

        # Position rows
        form_tr.addRow(QLabel("Position X"), self.vx)
        form_tr.addRow(QLabel("Position Y"), self.vy)
        form_tr.addRow(QLabel("Position Z"), self.vz)

        # Rotation rows
        form_tr.addRow(QLabel("Rotation Qx"), self.qx)
        form_tr.addRow(QLabel("Rotation Qy"), self.qy)
        form_tr.addRow(QLabel("Rotation Qz"), self.qz)
        form_tr.addRow(QLabel("Rotation Qw"), self.qw)

        editor_layout.addWidget(box_tr)

        # -- Respawn --
        box_rsp  = QGroupBox("Respawn")
        box_rsp.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        form_rsp = QFormLayout(box_rsp)
        form_rsp.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        self.cb_respawn = QComboBox()
        self.cb_respawn.setEditable(False)
        self._tune_combo(self.cb_respawn)
        self.cb_regist  = QComboBox()
        self.cb_regist.setEditable(False)
        self._tune_combo(self.cb_regist)
        self.btn_apply_pos        = QPushButton("Apply Position / Level")
        self.btn_apply_respawn    = QPushButton("Apply Respawn / Registered")
        self.btn_respawn_from_sel = QPushButton("Set Respawn to Selected Row")
        for b in (self.btn_apply_pos, self.btn_apply_respawn, self.btn_respawn_from_sel):
            b.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        form_rsp.addRow(QLabel("Respawn Stargazer"),    self.cb_respawn)
        form_rsp.addRow(QLabel("Registered Stargazer"), self.cb_regist)
        form_rsp.addRow(self.btn_apply_pos)
        form_rsp.addRow(self.btn_apply_respawn)
        form_rsp.addRow(self.btn_respawn_from_sel)
        editor_layout.addWidget(box_rsp)

        # spacer at bottom
        editor_layout.addItem(
            QSpacerItem(0, 0, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding)
        )

        # keep editor narrow + predictable; left gets the rest
        right_panel.setMinimumWidth(360)
        right_panel.setMaximumWidth(480)

        # ---------- THEME INIT ----------
        # try to inherit dark-mode pref from parent MainWindow
        parent_dark = True
        if parent is not None and hasattr(parent, "_dark_mode_pref"):
            try:
                parent_dark = bool(parent._dark_mode_pref)
            except Exception:
                pass
        self.apply_theme(parent_dark)

        # ---------- Signals ----------
        self.filter_edit.textChanged.connect(self._refilter)
        self.cb_loc.currentTextChanged.connect(lambda *_: self._apply_position())
        self.cb_lvl.currentTextChanged.connect(lambda *_: self._apply_position())
        self.cb_respawn.currentIndexChanged.connect(lambda *_: self._apply_respawn())
        self.cb_regist.currentIndexChanged.connect(lambda *_: self._apply_respawn())
        for sp in (self.vx, self.vy, self.vz, self.qx, self.qy, self.qz, self.qw):
            sp.valueChanged.connect(lambda _v, s=sp: self._apply_transform_live())
        self.btn_apply_pos.clicked.connect(self._apply_position)
        self.btn_apply_respawn.clicked.connect(self._apply_respawn)
        self.btn_respawn_from_sel.clicked.connect(self._respawn_from_selected)

        self.installEventFilter(self)

    # ---------- public: theme sync ----------
    def apply_theme(self, is_dark: bool) -> None:
        """
        Called at init AND when the main window toggles light/dark.
        """
        if is_dark:
            self.setStyleSheet(self._DARK_QSS)
        else:
            self.setStyleSheet(self._LIGHT_QSS)

    # ---------- widget helpers ----------
    def _num(self, default: float = 0.0) -> QDoubleSpinBox:
        sp = QDoubleSpinBox()
        sp.setDecimals(6)
        sp.setRange(-1e9, 1e9)
        sp.setSingleStep(10.0)
        sp.setValue(default)
        sp.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        return sp

    def _row3(self, a, b, c) -> QWidget:
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0,0,0,0)
        h.setSpacing(6)
        for x in (a,b,c):
            h.addWidget(x)
        return w

    def _row4(self, a, b, c, d) -> QWidget:
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0,0,0,0)
        h.setSpacing(6)
        for x in (a,b,c,d):
            h.addWidget(x)
        return w

    def _tune_combo(self, cb: QComboBox):
        cb.setMinimumWidth(220)
        cb.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        if cb.isEditable():
            comp = QCompleter()
            comp.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
            comp.setFilterMode(Qt.MatchFlag.MatchContains)
            comp.setCompletionMode(QCompleter.CompletionMode.UnfilteredPopupCompletion)
            cb.setCompleter(comp)

    # ---------- lifecycle ----------
    def set_data(self, json_data: Dict[str, Any]):
        self._data = json_data
        QTimer.singleShot(0, self._rebuild)

    def load_data(self, json_data: Dict[str, Any], *args, **kwargs):
        self.set_data(json_data)

    def eventFilter(self, obj, ev):
        if obj is self and ev.type() == QEvent.Type.Show and not self._auto_loaded:
            self._auto_loaded = True
            # set initial splitter sizes to favor the left (about 75/25)
            QTimer.singleShot(0, lambda: self.splitter.setSizes([3, 1]))
            QTimer.singleShot(0, self._rebuild)
        return super().eventFilter(obj, ev)

    # ---------- paths ----------
    @staticmethod
    def _char_base() -> List[Union[str, int]]:
        return ["root","properties","CharacterSaveData_0","Struct","Struct"]

    @staticmethod
    def _standard_teleport_path() -> List[Union[str, int]]:
        return ["root","properties","SpotSaveData_0","Struct","Struct",
                "TeleportObjectSpotList_0","Array","Struct","value"]

    def _find_teleport_list(self) -> Tuple[List[Any], List[Union[str, int]]]:
        """Robust: normal path, then deep-scan under SpotSaveData, then whole root."""
        lst = _get(self._data, self._standard_teleport_path(), None)
        if isinstance(lst, list):
            return lst, self._standard_teleport_path()

        base = ["root","properties","SpotSaveData_0"]
        spot = _get(self._data, base, None)

        best_path: List[Union[str,int]] = []
        best_list: List[Any] = []

        def looks_like_teleport_struct(d: dict) -> bool:
            lk = _lkeys(d)
            code_keys  = {"teleportobjectcodename_0", "spotcodename_0", "name", "spotuniqueid_0"}
            state_keys = {"stargazertype_0", "spottype_0", "state_0", "state"}
            return any(k in lk for k in code_keys) and any(k in lk for k in state_keys)

        def consider(node: JSON, path: List[Union[str,int]]):
            nonlocal best_list, best_path
            if isinstance(node, list) and node:
                u = _unwrap(node[0])
                if isinstance(u, dict) and looks_like_teleport_struct(u):
                    if len(node) > len(best_list):
                        best_list = node
                        best_path = path

        def walk(n: JSON, p: List[Union[str,int]]):
            consider(n, p)
            if isinstance(n, dict):
                for k, v in n.items():
                    walk(v, p+[k])
            elif isinstance(n, list):
                for i, v in enumerate(n):
                    walk(v, p+[i])

        if isinstance(spot, (dict, list)):
            walk(spot, base)
        if not best_list:
            root = _get(self._data, ["root"], None)
            if isinstance(root, (dict, list)):
                walk(root, ["root"])
        return best_list, best_path

    # ---------- build / refresh ----------
    def _rebuild(self):
        self._ensure_data()

        # preserve viewport & selection
        top_row = self.table.rowAt(0)
        selected_codes = {
            (self.table.item(i.row(), self.COL_NAME) or QTableWidgetItem("")).toolTip()
            for i in self.table.selectionModel().selectedRows()
        } if self.table.selectionModel() else set()

        self._rows.clear()
        self._teleport_codes.clear()
        self._all_levels.clear()
        self.table.setRowCount(0)

        if self._data:
            lst, path = self._find_teleport_list()
            for i, elem in enumerate(lst or []):
                node = _unwrap(elem)
                if not isinstance(node, dict):
                    continue
                lk = _lkeys(node)
                code_k  = (
                    lk.get("teleportobjectcodename_0")
                    or lk.get("spotcodename_0")
                    or lk.get("name")
                    or lk.get("spotuniqueid_0")
                )
                state_k = (
                    lk.get("stargazertype_0")
                    or lk.get("state_0")
                    or lk.get("state")
                    or lk.get("spottype_0")
                )

                # code can be direct string or wrapped in {"Name": "..."}
                raw_code = ""
                if code_k:
                    val = _get(node, [code_k])
                    if isinstance(val, dict):
                        raw_code = str(
                            _get(node, [code_k, "Name"])
                            or _get(node, [code_k, "name"])
                            or ""
                        )
                    else:
                        raw_code = str(val or "")

                # state could be enum wrapper or direct string
                raw_state = ""
                if state_k:
                    sv = _get(node, [state_k, "Enum"])
                    if sv is None:
                        sv = _get(node, [state_k, "Name"])
                    if sv is None:
                        sv = _get(node, [state_k])
                    raw_state = str(sv or "")

                # absolute path to the state leaf (prefer Enum subkey if present)
                state_abs = path + [i, state_k] if state_k else None
                if isinstance(_get(self._data, state_abs), dict):
                    lk2 = _lkeys(_get(self._data, state_abs))
                    if "enum" in lk2:
                        state_abs = state_abs + [lk2["enum"]]
                    elif "name" in lk2:
                        state_abs = state_abs + [lk2["name"]]

                pretty    = _pretty_code(raw_code)
                friendly  = _friendly_state(raw_state)

                self._rows.append({
                    "code": raw_code,
                    "state": raw_state,
                    "abs": path + [i],
                    "state_abs": state_abs,
                    "pretty": pretty
                })
                r = self.table.rowCount()
                self.table.insertRow(r)

                it_name = QTableWidgetItem(pretty)
                it_name.setToolTip(raw_code)
                it_name.setFlags(it_name.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.table.setItem(r, self.COL_NAME, it_name)

                combo = QComboBox(self.table)
                for label in ("Locked", "Active (Idle)", "Active"):
                    combo.addItem(label)
                combo.setCurrentText(friendly)
                combo.currentTextChanged.connect(
                    lambda text, rr=r: self._apply_state_change(rr, text)
                )
                self.table.setCellWidget(r, self.COL_STATE, combo)

                if raw_code:
                    self._teleport_codes.append(raw_code)

        self._fill_location_level_options()
        self._fill_respawn_registered()

        self._load_right_side()
        self._refilter()

        # restore selection & scroll
        if selected_codes:
            sm = self.table.selectionModel()
            for r in range(self.table.rowCount()):
                codev = (self.table.item(r, self.COL_NAME) or QTableWidgetItem("")).toolTip()
                if codev in selected_codes:
                    self.table.selectRow(r)
        if top_row >= 0 and self.table.rowCount():
            self.table.scrollToItem(
                self.table.item(min(top_row, self.table.rowCount()-1), self.COL_NAME)
            )

    def _fill_location_level_options(self):
        # Latest Location from stargazers
        opts_loc: List[Tuple[str,str]] = []
        seen: Set[str] = set()
        for c in self._teleport_codes:
            if c and c not in seen:
                seen.add(c)
                opts_loc.append((_pretty_code(c), c))
        opts_loc.sort(key=lambda t: t[0].lower())

        cur_loc_code = self.cb_loc.currentData()
        self.cb_loc.blockSignals(True)
        self.cb_loc.clear()
        for disp, code in opts_loc:
            self.cb_loc.addItem(disp, code)
            self.cb_loc.setItemData(
                self.cb_loc.count()-1,
                code,
                Qt.ItemDataRole.ToolTipRole
            )
        if cur_loc_code:
            ix = self.cb_loc.findData(cur_loc_code)
            if ix >= 0:
                self.cb_loc.setCurrentIndex(ix)
        self.cb_loc.blockSignals(False)

        # Latest Level: scan entire save for LV_* strings
        levels = set()
        def walk(n: JSON):
            if isinstance(n, dict):
                for v in n.values():
                    walk(v)
            elif isinstance(n, list):
                for v in n:
                    walk(v)
            elif isinstance(n, str):
                if n.startswith("LV_"):
                    levels.add(n)
        walk(self._data or {})
        self._all_levels = sorted(levels, key=str.lower)

        cur_lvl = self.cb_lvl.currentText().strip()
        self.cb_lvl.blockSignals(True)
        self.cb_lvl.clear()
        for lv in self._all_levels:
            self.cb_lvl.addItem(lv, lv)
        if cur_lvl:
            ix = self.cb_lvl.findText(cur_lvl)
            if ix >= 0:
                self.cb_lvl.setCurrentIndex(ix)
        self.cb_lvl.blockSignals(False)

    def _fill_respawn_registered(self):
        opts: List[Tuple[str,str]] = []
        seen: Set[str] = set()
        for c in self._teleport_codes:
            if c and c not in seen:
                seen.add(c)
                opts.append((_pretty_code(c), c))
        opts.sort(key=lambda t: t[0].lower())

        def fill(cb: QComboBox):
            cur_code = cb.currentData()
            cb.blockSignals(True)
            cb.clear()
            for disp, code in opts:
                cb.addItem(disp, code)
                cb.setItemData(
                    cb.count()-1,
                    code,
                    Qt.ItemDataRole.ToolTipRole
                )
            if cur_code:
                ix = cb.findData(cur_code)
                if ix >= 0:
                    cb.setCurrentIndex(ix)
            cb.blockSignals(False)

        fill(self.cb_respawn)
        fill(self.cb_regist)

    # ---------- misc ----------
    def _ensure_data(self):
        if self._data is None:
            p = self.parent()
            while p is not None and not hasattr(p, "data"):
                p = getattr(p, "parent", lambda: None)()
            if p is not None and getattr(p, "data", None) is not None:
                self._data = p.data

    # ---------- right panel load ----------
    def _load_right_side(self):
        base = self._char_base()
        # location / level
        cur_loc = str(_get(self._data, base + ["LatestLocationName_0", "Name"], "") or "")
        if self.cb_loc.count():
            ix = self.cb_loc.findData(cur_loc)
            if ix >= 0:
                self.cb_loc.setCurrentIndex(ix)
        cur_lvl = str(_get(self._data, base + ["LatestPersistentLevelName_0", "Name"], "") or "")
        if self.cb_lvl.count():
            ix = self.cb_lvl.findText(cur_lvl)
            if ix >= 0:
                self.cb_lvl.setCurrentIndex(ix)

        # translation vector
        vx = float(_get(self._data, base + ["LatestTransform_0","Struct","Struct","Translation_0","Struct","Vector","x"], 0.0))
        vy = float(_get(self._data, base + ["LatestTransform_0","Struct","Struct","Translation_0","Struct","Vector","y"], 0.0))
        vz = float(_get(self._data, base + ["LatestTransform_0","Struct","Struct","Translation_0","Struct","Vector","z"], 0.0))
        for sp, v in ((self.vx, vx), (self.vy, vy), (self.vz, vz)):
            sp.blockSignals(True)
            sp.setValue(v)
            sp.blockSignals(False)

        # rotation quat (x,y,z,w)
        qx = float(_get(self._data, base + ["LatestTransform_0","Struct","Struct","Rotation_0","Struct","tag","data","Quat","x"], 0.0))
        qy = float(_get(self._data, base + ["LatestTransform_0","Struct","Struct","Rotation_0","Struct","tag","data","Quat","y"], 0.0))
        qz = float(_get(self._data, base + ["LatestTransform_0","Struct","Struct","Rotation_0","Struct","tag","data","Quat","z"], 0.0))
        qw = float(_get(self._data, base + ["LatestTransform_0","Struct","Struct","Rotation_0","Struct","tag","data","Quat","w"], 1.0))
        for sp, v in ((self.qx, qx), (self.qy, qy), (self.qz, qz), (self.qw, qw)):
            sp.blockSignals(True)
            sp.setValue(v)
            sp.blockSignals(False)

        # respawn / registered
        resp = str(_get(self._data, base + ["RespawnTeleportObject_0","Name"], "") or "")
        reg  = str(_get(self._data, base + ["RegistTorsionCoilName_0","Name"], "") or "")
        if self.cb_respawn.count():
            ix = self.cb_respawn.findData(resp)
            if ix >= 0:
                self.cb_respawn.setCurrentIndex(ix)
        if self.cb_regist.count():
            ix = self.cb_regist.findData(reg)
            if ix >= 0:
                self.cb_regist.setCurrentIndex(ix)

    # ---------- filter ----------
    def _refilter(self):
        needle = (self.filter_edit.text() or "").strip().lower()
        for r in range(self.table.rowCount()):
            name_pretty = (self.table.item(r, self.COL_NAME) or QTableWidgetItem("")).text().lower()
            code_raw    = (self.table.item(r, self.COL_NAME) or QTableWidgetItem("")).toolTip().lower()
            hidden = bool(
                needle
                and (needle not in name_pretty and needle not in code_raw)
            )
            self.table.setRowHidden(r, hidden)

    # ---------- writers ----------
    def _apply_state_change(self, row_idx: int, friendly: str):
        if not (0 <= row_idx < len(self._rows)):
            return
        row = self._rows[row_idx]
        path = row.get("state_abs")
        if not path:
            return
        current = _get(self._data, path)
        target  = _retarget_enum_like(current, FRIENDLY_TO_ENUM.get(friendly, friendly))
        if _set(self._data, path, target):
            item = self.table.item(row_idx, self.COL_STATE)
            if item:
                item.setToolTip(target)

    def _apply_position(self):
        if not self._data:
            return
        base = self._char_base()
        loc_code = self.cb_loc.currentData() or self.cb_loc.currentText().strip()
        lvl_code = self.cb_lvl.currentText().strip()
        _set(self._data, base + ["LatestLocationName_0", "Name"], str(loc_code))
        _set(self._data, base + ["LatestPersistentLevelName_0", "Name"], str(lvl_code))
        self._apply_transform_live(refresh=False)
        self._rebuild()

    def _apply_transform_live(self, refresh: bool = True):
        if not self._data:
            return
        base = self._char_base()
        _set(self._data, base + ["LatestTransform_0","Struct","Struct","Translation_0","Struct","Vector","x"], float(self.vx.value()))
        _set(self._data, base + ["LatestTransform_0","Struct","Struct","Translation_0","Struct","Vector","y"], float(self.vy.value()))
        _set(self._data, base + ["LatestTransform_0","Struct","Struct","Translation_0","Struct","Vector","z"], float(self.vz.value()))
        _set(self._data, base + ["LatestTransform_0","Struct","Struct","Rotation_0","Struct","tag","data","Quat","x"], float(self.qx.value()))
        _set(self._data, base + ["LatestTransform_0","Struct","Struct","Rotation_0","Struct","tag","data","Quat","y"], float(self.qy.value()))
        _set(self._data, base + ["LatestTransform_0","Struct","Struct","Rotation_0","Struct","tag","data","Quat","z"], float(self.qz.value()))
        _set(self._data, base + ["LatestTransform_0","Struct","Struct","Rotation_0","Struct","tag","data","Quat","w"], float(self.qw.value()))
        if refresh:
            self._rebuild()

    def _apply_respawn(self):
        if not self._data:
            return
        base = self._char_base()
        resp_code = self.cb_respawn.currentData() or ""
        reg_code  = self.cb_regist.currentData() or ""
        _set(self._data, base + ["RespawnTeleportObject_0","Name"], str(resp_code))
        _set(self._data, base + ["RegistTorsionCoilName_0","Name"], str(reg_code))
        self._rebuild()

    def _respawn_from_selected(self):
        rows = sorted({ix.row() for ix in self.table.selectionModel().selectedRows()})
        if not rows:
            return
        code = (self.table.item(rows[0], self.COL_NAME) or QTableWidgetItem("")).toolTip()
        if not code:
            return
        ix1 = self.cb_respawn.findData(code)
        if ix1 >= 0:
            self.cb_respawn.setCurrentIndex(ix1)
        ix2 = self.cb_regist.findData(code)
        if ix2 >= 0:
            self.cb_regist.setCurrentIndex(ix2)
        self._apply_respawn()
