from __future__ import annotations
from typing import Iterable, Dict, Optional, Tuple
from PyQt6.QtCore import Qt, pyqtSignal, QPropertyAnimation
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QToolButton, QPushButton, QSizePolicy,
    QFrame, QSpacerItem
)

class SideNav(QWidget):
    """Collapsible left sidebar that emits `activated(key)` when a tab button is clicked."""
    activated = pyqtSignal(str)
    expandedChanged = pyqtSignal(bool)

    def __init__(
        self,
        items: Iterable[Tuple[str, str, str, Optional[QIcon]]],  # (key, full_text, short_text, icon)
        *,
        expanded_width: int = 196,
        collapsed_width: int = 0,  # fully closed leaves no gap
        parent: Optional[QWidget] = None
    ):
        super().__init__(parent)
        self.setObjectName("SideNav")
        self._expanded = True
        self._expanded_width = int(expanded_width)
        self._collapsed_width = int(collapsed_width)

        self.setMinimumWidth(self._collapsed_width)
        self.setMaximumWidth(self._expanded_width)

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 10, 8, 10)
        root.setSpacing(8)

        # Toggle (hamburger) visible while sidebar is open
        self.btn_toggle = QToolButton(self)
        self.btn_toggle.setObjectName("Hamburger")
        self.btn_toggle.setCheckable(True)
        self.btn_toggle.setChecked(True)
        self.btn_toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self.btn_toggle.setArrowType(Qt.ArrowType.NoArrow)
        self.btn_toggle.setText("☰")
        self.btn_toggle.clicked.connect(self._on_toggle)
        root.addWidget(self.btn_toggle, 0, Qt.AlignmentFlag.AlignLeft)

        # Divider
        div = QFrame(self)
        div.setObjectName("Divider")
        div.setFrameShape(QFrame.Shape.HLine)
        div.setFrameShadow(QFrame.Shadow.Sunken)
        root.addWidget(div)

        # Buttons
        self.container = QWidget(self)
        vbox = QVBoxLayout(self.container)
        vbox.setContentsMargins(0, 0, 0, 0)
        vbox.setSpacing(6)
        root.addWidget(self.container, 1)

        self._buttons: Dict[str, QPushButton] = {}
        self._labels: Dict[str, Tuple[str, str]] = {}

        for key, full_text, short_text, icon in items:
            b = QPushButton(full_text, self)
            b.setObjectName("NavButton")
            b.setProperty("locked", False)
            b.setProperty("active", False)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setFlat(True)
            b.setMinimumHeight(36)
            b.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            if icon:
                b.setIcon(icon)
            b.clicked.connect(lambda _=False, k=key: self._handle_click(k))
            b.setToolTip(full_text)
            self._buttons[key] = b
            self._labels[key] = (full_text, short_text)
            vbox.addWidget(b)

        vbox.addItem(QSpacerItem(0, 0, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding))

        # Width animations
        self._anim_max = QPropertyAnimation(self, b"maximumWidth", self); self._anim_max.setDuration(160)
        self._anim_min = QPropertyAnimation(self, b"minimumWidth", self); self._anim_min.setDuration(160)

        self.setStyleSheet(self._default_stylesheet())
        self._refresh_labels()

    # ---------- Public API ----------
    def set_locked(self, key: str, locked: bool) -> None:
        b = self._buttons.get(key)
        if not b:
            return
        b.setProperty("locked", bool(locked))
        b.setEnabled(not locked)
        b.style().unpolish(b); b.style().polish(b)

    def is_locked(self, key: str) -> bool:
        b = self._buttons.get(key)
        return bool(b and b.property("locked") is True)

    def set_all_locked(self, keys, locked: bool) -> None:
        for k in keys:
            self.set_locked(k, locked)

    def set_active(self, key: Optional[str]) -> None:
        for k, b in self._buttons.items():
            b.setProperty("active", bool(k == key))
            b.style().unpolish(b); b.style().polish(b)

    def expanded(self) -> bool:
        return self._expanded

    def set_expanded(self, expanded: bool) -> None:
        if self._expanded == expanded:
            return
        self._expanded = expanded
        self.btn_toggle.setChecked(expanded)
        self._animate_width(self._expanded_width if expanded else self._collapsed_width)
        self._refresh_labels()
        self.expandedChanged.emit(expanded)

    # ---------- Internals ----------
    def _handle_click(self, key: str) -> None:
        if self.is_locked(key):
            return
        self.activated.emit(key)

    def _refresh_labels(self) -> None:
        # keep full labels for readability (short labels weren’t fitting well visually)
        for key, b in self._buttons.items():
            full, _ = self._labels.get(key, (b.text(), ""))
            b.setText(full)

    def _on_toggle(self) -> None:
        self.set_expanded(not self._expanded)

    def _animate_width(self, target: int) -> None:
        for anim in (self._anim_max, self._anim_min):
            anim.stop()
            anim.setStartValue(self.width())
            anim.setEndValue(int(target))
            anim.start()

    def _default_stylesheet(self) -> str:
        return """
        QWidget#SideNav { background: #1c1f26; border-right: 1px solid #2a2f38; }
        QToolButton#Hamburger {
            font-size: 18px; color: #dfe6f0; background: transparent;
            border: 1px solid rgba(255,255,255,0.06); border-radius: 6px; padding: 4px 8px;
        }
        QToolButton#Hamburger:hover { background: rgba(255,255,255,0.08); }
        QFrame#Divider { color: #2a2f38; }
        QPushButton#NavButton {
            text-align: left; padding: 8px 10px; border-radius: 8px; font-size: 14px;
            color: #c9d3e1; background: transparent;
        }
        QPushButton#NavButton:hover { background: rgba(255,255,255,0.06); }
        QPushButton#NavButton[active="true"] { background: #2a62c9; color: white; }
        QPushButton#NavButton[active="true"]:hover { background: #2f6fe6; }
        QPushButton#NavButton[locked="true"] { color: #8d97a8; }
        QPushButton#NavButton[locked="true"]:hover { background: rgba(205,90,90,0.10); }
        """
