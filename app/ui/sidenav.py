from __future__ import annotations
from typing import Iterable, Dict, Optional, Tuple

from PyQt6.QtCore import Qt, pyqtSignal, QPropertyAnimation
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QToolButton,
    QPushButton,
    QSizePolicy,
    QFrame,
    QSpacerItem,
)


class SideNav(QWidget):
    """
    Collapsible left sidebar that emits `activated(key)` when a tab button is clicked.
    """

    activated = pyqtSignal(str)
    expandedChanged = pyqtSignal(bool)

    def __init__(
        self,
        items: Iterable[Tuple[str, str, str, Optional[QIcon]]],
        *,
        expanded_width: int = 196,
        collapsed_width: int = 0,
        parent: Optional[QWidget] = None,
    ) -> None:
        """
        :param items: iterable of (key, full_label, short_label, icon)
        """
        super().__init__(parent)

        self.setObjectName("SideNav")

        self._expanded = True
        self._expanded_width = int(expanded_width)
        self._collapsed_width = int(collapsed_width)
        self._dark = True  # MainWindow will call apply_theme()

        self._buttons: Dict[str, QPushButton] = {}
        self._labels: Dict[str, Tuple[str, str]] = {}

        self.setMinimumWidth(self._collapsed_width)
        self.setMaximumWidth(self._expanded_width)

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 10, 8, 10)
        root.setSpacing(8)

        # --- Hamburger toggle ---
        self.btn_toggle = QToolButton(self)
        self.btn_toggle.setObjectName("Hamburger")
        self.btn_toggle.setCheckable(True)
        self.btn_toggle.setChecked(True)
        self.btn_toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self.btn_toggle.setArrowType(Qt.ArrowType.NoArrow)
        self.btn_toggle.setText("☰")
        self.btn_toggle.clicked.connect(self._on_toggle_clicked)
        root.addWidget(self.btn_toggle, 0, Qt.AlignmentFlag.AlignLeft)

        # Divider
        divider = QFrame(self)
        divider.setObjectName("Divider")
        divider.setFrameShape(QFrame.Shape.HLine)
        divider.setFrameShadow(QFrame.Shadow.Sunken)
        root.addWidget(divider)

        # Container for nav buttons
        self.container = QWidget(self)
        vbox = QVBoxLayout(self.container)
        vbox.setContentsMargins(0, 0, 0, 0)
        vbox.setSpacing(6)
        root.addWidget(self.container, 1)

        for key, full_text, short_text, icon in items:
            btn = QPushButton(full_text, self)
            btn.setObjectName("NavButton")
            btn.setFlat(True)
            btn.setCheckable(False)
            btn.setProperty("locked", False)
            btn.setProperty("active", False)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setMinimumHeight(36)
            btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            if icon:
                btn.setIcon(icon)
            btn.clicked.connect(lambda _=False, k=key: self._handle_click(k))
            btn.setToolTip(full_text)

            self._buttons[key] = btn
            self._labels[key] = (full_text, short_text)
            vbox.addWidget(btn)

        vbox.addItem(QSpacerItem(0, 0, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding))

        # Width animations
        self._anim_max = QPropertyAnimation(self, b"maximumWidth", self)
        self._anim_max.setDuration(160)
        self._anim_min = QPropertyAnimation(self, b"minimumWidth", self)
        self._anim_min.setDuration(160)

        # initial labels + theme
        self._refresh_labels()
        self.apply_theme(True)

    # ------------------------------------------------------------------ #
    # Public API                                                         #
    # ------------------------------------------------------------------ #
    def set_locked(self, key: str, locked: bool) -> None:
        btn = self._buttons.get(key)
        if not btn:
            return
        btn.setProperty("locked", bool(locked))
        btn.setEnabled(not locked)
        btn.style().unpolish(btn)
        btn.style().polish(btn)

    def is_locked(self, key: str) -> bool:
        btn = self._buttons.get(key)
        return bool(btn and btn.property("locked") is True)

    def set_all_locked(self, keys, locked: bool) -> None:
        for k in keys:
            self.set_locked(k, locked)

    def set_active(self, key: Optional[str]) -> None:
        for k, btn in self._buttons.items():
            btn.setProperty("active", bool(k == key))
            btn.style().unpolish(btn)
            btn.style().polish(btn)

    def expanded(self) -> bool:
        return self._expanded

    def set_expanded(self, expanded: bool) -> None:
        expanded = bool(expanded)
        if self._expanded == expanded:
            return
        self._expanded = expanded
        self.btn_toggle.setChecked(expanded)
        self._animate_width(self._expanded_width if expanded else self._collapsed_width)
        self._refresh_labels()
        self.expandedChanged.emit(expanded)

    def apply_theme(self, dark: bool) -> None:
        """
        Dark/light styling for the sidebar.
        """
        self._dark = bool(dark)
        if self._dark:
            self.setStyleSheet(self._stylesheet_dark())
        else:
            self.setStyleSheet(self._stylesheet_light())

    # ------------------------------------------------------------------ #
    # Internal helpers                                                   #
    # ------------------------------------------------------------------ #
    def _handle_click(self, key: str) -> None:
        if self.is_locked(key):
            return
        self.activated.emit(key)

    def _refresh_labels(self) -> None:
        """
        If you ever want short labels for collapsed mode, you can switch on
        `self._expanded` here. Right now we keep full labels for readability.
        """
        for key, btn in self._buttons.items():
            full, _short = self._labels.get(key, (btn.text(), ""))
            btn.setText(full)

    def _on_toggle_clicked(self) -> None:
        self.set_expanded(not self._expanded)

    def _animate_width(self, target: int) -> None:
        target = int(target)
        for anim in (self._anim_max, self._anim_min):
            anim.stop()
            anim.setStartValue(self.width())
            anim.setEndValue(target)
            anim.start()

    # ------------------------------------------------------------------ #
    # Stylesheets                                                        #
    # ------------------------------------------------------------------ #
    def _stylesheet_dark(self) -> str:
        return """
        QWidget#SideNav {
            background: #1c1f26;
            border-right: 1px solid #2a2f38;
        }
        QToolButton#Hamburger {
            font-size: 18px;
            color: #dfe6f0;
            background: transparent;
            border: 1px solid rgba(255,255,255,0.06);
            border-radius: 6px;
            padding: 4px 8px;
        }
        QToolButton#Hamburger:hover {
            background: rgba(255,255,255,0.08);
        }
        QFrame#Divider {
            color: #2a2f38;
        }
        QPushButton#NavButton {
            text-align: left;
            padding: 8px 10px;
            border-radius: 8px;
            font-size: 14px;
            color: #c9d3e1;
            background: transparent;
        }
        QPushButton#NavButton:hover {
            background: rgba(255,255,255,0.06);
        }
        QPushButton#NavButton[active="true"] {
            background: #2a62c9;
            color: white;
        }
        QPushButton#NavButton[active="true"]:hover {
            background: #2f6fe6;
        }
        QPushButton#NavButton[locked="true"] {
            color: #8d97a8;
        }
        QPushButton#NavButton[locked="true"]:hover {
            background: rgba(205,90,90,0.10);
        }
        """

    def _stylesheet_light(self) -> str:
        return """
        QWidget#SideNav {
            background: #f3f4f7;
            border-right: 1px solid #d1d4dd;
        }
        QToolButton#Hamburger {
            font-size: 18px;
            color: #22242a;
            background: #ffffff;
            border: 1px solid rgba(0,0,0,0.08);
            border-radius: 6px;
            padding: 4px 8px;
        }
        QToolButton#Hamburger:hover {
            background: #e6e9f0;
        }
        QFrame#Divider {
            color: #d1d4dd;
        }
        QPushButton#NavButton {
            text-align: left;
            padding: 8px 10px;
            border-radius: 8px;
            font-size: 14px;
            color: #202229;
            background: transparent;
        }
        QPushButton#NavButton:hover {
            background: #e1e5f0;
        }
        QPushButton#NavButton[active="true"] {
            background: #2a62c9;
            color: #ffffff;
        }
        QPushButton#NavButton[active="true"]:hover {
            background: #2f6fe6;
        }
        QPushButton#NavButton[locked="true"] {
            color: #9aa0b0;
        }
        QPushButton#NavButton[locked="true"]:hover {
            background: #f1d8dd;
        }
        """
