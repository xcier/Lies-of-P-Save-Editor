from __future__ import annotations
from typing import Dict, Any, Optional

from PyQt6.QtCore import QSettings, Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QFormLayout, QLabel,
    QLineEdit, QSpinBox, QComboBox, QPushButton, QMessageBox, QDoubleSpinBox, QCheckBox
)

# ---------- helpers ----------
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
def _get_intlike(node: Any, default: int = 0) -> int:
    if not isinstance(node, dict):
        return int(default)
    if "Int64" in node:
        try:
            return int(node.get("Int64", default))
        except Exception:
            return int(default)
    if "Int" in node:
        try:
            return int(node.get("Int", default))
        except Exception:
            return int(default)
    return int(default)

def _ensure_intlike(parent: Dict[str, Any], key: str, value: int) -> Dict[str, Any]:
    """Ensure key exists and write an int preserving Int vs Int64 when possible."""
    node = parent.get(key)
    if not isinstance(node, dict):
        node = {}
        parent[key] = node

    tag_other = (((node.get("tag") or {}).get("data") or {}).get("Other"))
    prefer_i64 = ("Int64" in node) or (isinstance(tag_other, str) and "Int64" in tag_other)

    tag = node.setdefault("tag", {}).setdefault("data", {})
    tag["Other"] = "Int64Property" if prefer_i64 else "IntProperty"

    if prefer_i64:
        node.pop("Int", None)
        node["Int64"] = int(value)
    else:
        node.pop("Int64", None)
        node["Int"] = int(value)
    return node



class CharacterTab(QWidget):
    """General tab with Playthrough Info and core stats (no currency)."""
    SKILL_CHOICES = ["balance", "dexterity", "strength"]

    def __init__(self, main_window):
        super().__init__(main_window)
        self.main_window = main_window
        self.settings = QSettings("MyCompany", "LiesOfPSaveEditor")

        # anchors into the loaded save (mutated in place)
        self._root_props: Optional[Dict[str, Any]] = None
        self._char_struct: Optional[Dict[str, Any]] = None
        self._slot_node: Optional[Dict[str, Any]] = None

        self.setFont(QFont("Segoe UI", 10))

        main = QVBoxLayout(self)
        main.setContentsMargins(16, 16, 16, 16)
        main.setSpacing(20)

        # ----------------- Slot / Path -----------------
        grp_slot = QGroupBox("Slot Alias & Path")
        grp_slot.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        form_slot = QFormLayout()
        form_slot.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form_slot.setContentsMargins(8, 8, 8, 8)
        form_slot.setSpacing(12)

        self.alias_combo = QComboBox()
        self.alias_combo.addItem("")
        self._load_aliases()
        self.alias_combo.currentTextChanged.connect(self._on_alias_selected)
        form_slot.addRow(QLabel("Saved Aliases:"), self.alias_combo)

        alias_line = QHBoxLayout()
        self.alias_edit = QLineEdit()
        self.alias_edit.setPlaceholderText("New alias name")
        alias_line.addWidget(self.alias_edit)
        self.save_alias_btn = QPushButton("Save Alias")
        self.save_alias_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.save_alias_btn.clicked.connect(self._on_save_alias)
        alias_line.addWidget(self.save_alias_btn)
        form_slot.addRow(QLabel("Alias:"), alias_line)

        self.guid_edit = QLineEdit()
        self.guid_edit.setPlaceholderText("GUID (numeric)")
        self.guid_edit.setMinimumWidth(240)
        form_slot.addRow(QLabel("GUID:"), self.guid_edit)

        self.slot_edit = QLineEdit()
        self.slot_edit.setPlaceholderText("Character Slot (e.g. SaveData-1_Character_1)")
        self.slot_edit.setMinimumWidth(240)
        form_slot.addRow(QLabel("Character Slot:"), self.slot_edit)   # renamed from Suffix

        grp_slot.setLayout(form_slot)
        main.addWidget(grp_slot)

        # ----------------- Playthrough Info -----------------
        grp_stats = QGroupBox("Playthrough Info")
        grp_stats.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        form_stats = QFormLayout()
        form_stats.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form_stats.setContentsMargins(8, 8, 8, 8)
        form_stats.setSpacing(12)

        self.playtime_spin = QDoubleSpinBox()
        self.playtime_spin.setDecimals(3)
        self.playtime_spin.setRange(0.0, 9_999_999.0)
        self.playtime_spin.setSingleStep(1.0)
        form_stats.addRow(QLabel("Play Time (s):"), self.playtime_spin)

        self.death_spin = QSpinBox()
        self.death_spin.setRange(0, 999_999_999)
        form_stats.addRow(QLabel("Deaths:"), self.death_spin)

        self.ng_label = QLabel("NG+ Round:")
        self.ng_spin = QSpinBox()
        self.ng_spin.setRange(0, 999_999_999)  # expanded max
        form_stats.addRow(self.ng_label, self.ng_spin)

        # Character Level (PlayerLevel_0)
        self.level_spin = QSpinBox()
        self.level_spin.setRange(0, 999_999_999)
        form_stats.addRow(QLabel("Character Level:"), self.level_spin)

        # Ergo (kept here until Currency tab is ready)
        self.ergo_spin = QSpinBox()
        self.ergo_spin.setRange(0, 999_999_999)
        form_stats.addRow(QLabel("Ergo:"), self.ergo_spin)  # AcquisitionSoul_0

        self.ergo_needed_spin = QSpinBox()
        self.ergo_needed_spin.setRange(0, 999_999_999)
        form_stats.addRow(QLabel("Ergo Needed to Level:"), self.ergo_needed_spin)  # NextLevelUpRequireSoul_0

        # Humanity
        self.humanity_level_spin = QSpinBox()
        self.humanity_level_spin.setRange(0, 99)
        form_stats.addRow(QLabel("Humanity Level:"), self.humanity_level_spin)  # HumanityLevel_0

        self.humanity_spin = QSpinBox()
        self.humanity_spin.setRange(0, 999_999_999)
        form_stats.addRow(QLabel("Humanity:"), self.humanity_spin)  # AcquisitionHumanity_0

        # skill dropdown (DefaultStatCodeName_0.Name)
        self.skill_combo = QComboBox()
        self.skill_combo.addItems(self.SKILL_CHOICES)
        form_stats.addRow(QLabel("Skill:"), self.skill_combo)

        # NEW: Total Damage Taken (TotalReceiveDamage_0.Int)
        self.total_damage_spin = QSpinBox()
        self.total_damage_spin.setRange(0, 2_147_483_647)
        form_stats.addRow(QLabel("Total Damage Taken:"), self.total_damage_spin)

        # NEW: Lamp Attached toggle (bAttachedPCLamp_0.Bool)
        self.lamp_cb = QCheckBox("Attached")
        form_stats.addRow(QLabel("Lamp:"), self.lamp_cb)

        grp_stats.setLayout(form_stats)
        main.addWidget(grp_stats)

        # Signals
        self.guid_edit.editingFinished.connect(self._on_slot_changed)
        self.slot_edit.editingFinished.connect(self._on_slot_changed)

        self.playtime_spin.valueChanged.connect(self._on_playtime_changed)
        self.death_spin.valueChanged.connect(self._on_death_changed)
        self.ng_spin.valueChanged.connect(self._on_ng_changed)
        self.level_spin.valueChanged.connect(self._on_level_changed)
        self.ergo_spin.valueChanged.connect(self._on_ergo_changed)
        self.ergo_needed_spin.valueChanged.connect(self._on_ergo_needed_changed)
        self.humanity_level_spin.valueChanged.connect(self._on_humanity_level_changed)
        self.humanity_spin.valueChanged.connect(self._on_humanity_changed)
        self.skill_combo.currentTextChanged.connect(self._on_skill_changed)

        self.total_damage_spin.valueChanged.connect(self._on_total_damage_changed)
        self.lamp_cb.stateChanged.connect(self._on_lamp_changed)

    # ---------- aliases ----------
    def _load_aliases(self):
        self.alias_combo.blockSignals(True)
        self.alias_combo.clear()
        self.alias_combo.addItem("")
        self.settings.beginGroup("SlotNameAliases")
        for alias in self.settings.childKeys():
            self.alias_combo.addItem(alias)
        self.settings.endGroup()
        self.alias_combo.blockSignals(False)

    def _on_save_alias(self):
        alias = self.alias_edit.text().strip()
        guid = self.guid_edit.text().strip()
        if not alias or not guid:
            QMessageBox.warning(self, "Invalid Alias", "Alias and GUID must be provided.")
            return
        self.settings.beginGroup("SlotNameAliases")
        self.settings.setValue(alias, guid)
        self.settings.endGroup()
        self._load_aliases()
        self.alias_combo.setCurrentText(alias)

    def _on_alias_selected(self, alias: str):
        if not alias:
            return
        self.settings.beginGroup("SlotNameAliases")
        guid = self.settings.value(alias, "")
        self.settings.endGroup()
        if guid:
            self.guid_edit.setText(guid)
            self._on_slot_changed()

    # ---------- data I/O ----------
    def load_data(self, data: Dict[str, Any]):
        """Populate all fields from the save dict (write-through)."""
        self._root_props  = _g(data, "root", "properties", default={})
        self._slot_node   = _g(self._root_props, "SlotName_0", default={})
        self._char_struct = _g(self._root_props, "CharacterSaveData_0", "Struct", "Struct", default={})

        # slot path → /GUID/CharacterSlot
        slot_str = self._slot_node.get("Str", "") if isinstance(self._slot_node, dict) else ""
        parts = slot_str.strip("/").split("/", 1)
        guid = parts[0] if parts else ""
        slot = parts[1] if len(parts) > 1 else ""

        # block signals while populating inputs
        self.guid_edit.blockSignals(True)
        self.slot_edit.blockSignals(True)
        self.guid_edit.setText(guid)
        self.slot_edit.setText(slot)
        self.guid_edit.blockSignals(False)
        self.slot_edit.blockSignals(False)

        # select alias if exists
        self.settings.beginGroup("SlotNameAliases")
        matched = False
        for alias in self.settings.childKeys():
            if str(self.settings.value(alias)) == guid:
                self.alias_combo.setCurrentText(alias)
                matched = True
                break
        if not matched:
            self.alias_combo.setCurrentText("")
        self.settings.endGroup()

        # play time
        pt = _g(self._char_struct, "CharacterPlayTime_0", default={}).get("Double", 0.0)
        try:
            pt_val = float(pt)
        except Exception:
            pt_val = 0.0
        self.playtime_spin.blockSignals(True); self.playtime_spin.setValue(pt_val); self.playtime_spin.blockSignals(False)

        # deaths
        deaths_node = _g(self._char_struct, "YouDieCount_0", default={})
        deaths_val = _get_intlike(deaths_node, 0)
        self.death_spin.blockSignals(True); self.death_spin.setValue(int(deaths_val)); self.death_spin.blockSignals(False)

        # NG+
        ng_node = _g(self._char_struct, "NewGamePlus_Round_0", default={})
        ng_val = _get_intlike(ng_node, 0)
        self.ng_spin.blockSignals(True); self.ng_spin.setValue(int(ng_val)); self.ng_spin.blockSignals(False)
        self.ng_label.show(); self.ng_spin.show()

        # Character Level
        lvl_node = _g(self._char_struct, "PlayerLevel_0", default={})
        lvl_val = _get_intlike(lvl_node, 0)
        self.level_spin.blockSignals(True); self.level_spin.setValue(int(lvl_val)); self.level_spin.blockSignals(False)

        # Ergo (AcquisitionSoul_0)
        ergo_node = _g(self._char_struct, "AcquisitionSoul_0", default={})
        ergo_val = _get_intlike(ergo_node, 0)
        self.ergo_spin.blockSignals(True); self.ergo_spin.setValue(int(ergo_val)); self.ergo_spin.blockSignals(False)

        # Ergo Needed to Level (NextLevelUpRequireSoul_0)
        need_node = _g(self._char_struct, "NextLevelUpRequireSoul_0", default={})
        need_val = _get_intlike(need_node, 0)
        self.ergo_needed_spin.blockSignals(True); self.ergo_needed_spin.setValue(int(need_val)); self.ergo_needed_spin.blockSignals(False)

        # Humanity Level
        hlevel_node = _g(self._char_struct, "HumanityLevel_0", default={})
        hlevel_val = _get_intlike(hlevel_node, 0)
        self.humanity_level_spin.blockSignals(True); self.humanity_level_spin.setValue(int(hlevel_val)); self.humanity_level_spin.blockSignals(False)

        # Humanity
        h_node = _g(self._char_struct, "AcquisitionHumanity_0", default={})
        h_val = _get_intlike(h_node, 0)
        self.humanity_spin.blockSignals(True); self.humanity_spin.setValue(int(h_val)); self.humanity_spin.blockSignals(False)

        # Skill (DefaultStatCodeName_0.Name)
        name_node = _g(self._char_struct, "DefaultStatCodeName_0", default={})
        current_skill = ""
        if isinstance(name_node, dict):
            cur = name_node.get("Name")
            if isinstance(cur, str):
                current_skill = cur
        if current_skill not in self.SKILL_CHOICES and self.SKILL_CHOICES:
            current_skill = self.SKILL_CHOICES[0]
        self.skill_combo.blockSignals(True)
        self.skill_combo.setCurrentText(current_skill)
        self.skill_combo.blockSignals(False)

        # NEW: Total Damage Taken
        t_node = _g(self._char_struct, "TotalReceiveDamage_0", default={})
        t_val = _get_intlike(t_node, 0)
        self.total_damage_spin.blockSignals(True); self.total_damage_spin.setValue(int(t_val)); self.total_damage_spin.blockSignals(False)

        # NEW: Lamp toggle
        lamp_node = _g(self._char_struct, "bAttachedPCLamp_0", default={})
        lamp_val = bool(lamp_node.get("Bool", False)) if isinstance(lamp_node, dict) else False
        self.lamp_cb.blockSignals(True); self.lamp_cb.setChecked(lamp_val); self.lamp_cb.blockSignals(False)

    # ---------- writers ----------
    def _on_slot_changed(self):
        if not isinstance(self._slot_node, dict):
            return
        guid = self.guid_edit.text().strip()
        slot = self.slot_edit.text().strip()
        self._slot_node["Str"] = f"/{guid}/{slot}".replace("//", "/")

    def _on_playtime_changed(self, value: float):
        if not isinstance(self._char_struct, dict): return
        node = _ensure_dict(self._char_struct, "CharacterPlayTime_0")
        node["Double"] = float(value)

    def _on_death_changed(self, value: int):
        if not isinstance(self._char_struct, dict): return
        node = _ensure_intlike(self._char_struct, "YouDieCount_0", int(value))

    def _on_ng_changed(self, value: int):
        if not isinstance(self._char_struct, dict): return
        node = _ensure_intlike(self._char_struct, "NewGamePlus_Round_0", int(value))

    def _on_level_changed(self, value: int):
        if not isinstance(self._char_struct, dict): return
        node = _ensure_intlike(self._char_struct, "PlayerLevel_0", int(value))

    def _on_ergo_changed(self, value: int):
        if not isinstance(self._char_struct, dict): return
        node = _ensure_intlike(self._char_struct, "AcquisitionSoul_0", int(value))

    def _on_ergo_needed_changed(self, value: int):
        if not isinstance(self._char_struct, dict): return
        node = _ensure_intlike(self._char_struct, "NextLevelUpRequireSoul_0", int(value))

    def _on_humanity_level_changed(self, value: int):
        if not isinstance(self._char_struct, dict): return
        node = _ensure_intlike(self._char_struct, "HumanityLevel_0", int(value))

    def _on_humanity_changed(self, value: int):
        if not isinstance(self._char_struct, dict): return
        node = _ensure_intlike(self._char_struct, "AcquisitionHumanity_0", int(value))

    def _on_skill_changed(self, name: str):
        if not isinstance(self._char_struct, dict): return
        node = _ensure_dict(self._char_struct, "DefaultStatCodeName_0")
        # Ensure a minimal NameProperty wrapper when missing
        tag = node.setdefault("tag", {}).setdefault("data", {})
        tag.setdefault("Other", "NameProperty")
        node["Name"] = str(name)

    def _on_total_damage_changed(self, value: int):
        if not isinstance(self._char_struct, dict): return
        node = _ensure_intlike(self._char_struct, "TotalReceiveDamage_0", int(value))

    def _on_lamp_changed(self, state: int):
        if not isinstance(self._char_struct, dict): return
        node = _ensure_dict(self._char_struct, "bAttachedPCLamp_0")
        node["Bool"] = bool(state)