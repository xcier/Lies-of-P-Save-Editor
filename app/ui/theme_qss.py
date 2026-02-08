from __future__ import annotations

def qss_dark() -> str:
    # Modern dark QSS tuned for Fusion style (PyQt6).
    return r"""
    /* --- Base --- */
    QWidget {
        font-size: 12px;
    }

    QMainWindow, QWidget {
        background: #222429;
        color: #e6e8ee;
    }

    /* --- Tooltips --- */
    QToolTip {
        background: #f6f2c2;
        color: #141414;
        border: 1px solid rgba(0,0,0,0.25);
        padding: 6px 8px;
        border-radius: 6px;
    }

    /* --- Cards / panels --- */
    QFrame[panel="true"], QWidget[panel="true"] {
        background: #1c1d21;
        border: 1px solid rgba(255,255,255,0.08);
        border-radius: 12px;
    }

    /* --- Tabs --- */
    QTabWidget::pane {
        border: 1px solid rgba(255,255,255,0.10);
        border-radius: 12px;
        top: -1px;
        background: #1c1d21;
    }
    QTabBar::tab {
        background: transparent;
        border: 1px solid transparent;
        padding: 8px 12px;
        margin-right: 6px;
        border-radius: 10px;
        color: rgba(230,232,238,0.75);
        font-weight: 500;
    }
    QTabBar::tab:selected {
        background: rgba(42,98,201,0.22);
        border: 1px solid rgba(42,98,201,0.55);
        color: #e6e8ee;
    }
    QTabBar::tab:hover {
        background: rgba(255,255,255,0.06);
        color: #e6e8ee;
    }

    /* --- Inputs --- */
    QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox, QDoubleSpinBox, QComboBox {
        background: #181a1f;
        border: 1px solid rgba(255,255,255,0.12);
        border-radius: 10px;
        padding: 6px 10px;
        selection-background-color: rgba(42,98,201,0.55);
    }
    QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {
        border: 1px solid rgba(42,98,201,0.75);
    }
    QComboBox::drop-down {
        border: none;
        width: 24px;
    }
    QComboBox::down-arrow {
        width: 10px;
        height: 10px;
    }

    /* --- Buttons --- */
    QPushButton, QToolButton {
        background: rgba(255,255,255,0.06);
        border: 1px solid rgba(255,255,255,0.10);
        border-radius: 10px;
        padding: 7px 12px;
        color: #e6e8ee;
    }
    QPushButton:hover, QToolButton:hover {
        background: rgba(255,255,255,0.10);
        border-color: rgba(255,255,255,0.14);
    }
    QPushButton:pressed, QToolButton:pressed {
        background: rgba(42,98,201,0.22);
        border-color: rgba(42,98,201,0.45);
    }
    QPushButton:disabled, QToolButton:disabled {
        color: rgba(230,232,238,0.35);
        background: rgba(255,255,255,0.03);
        border-color: rgba(255,255,255,0.05);
    }
    QPushButton[primary="true"] {
        background: rgba(42,98,201,0.85);
        border-color: rgba(42,98,201,0.95);
        color: white;
    }
    QPushButton[primary="true"]:hover {
        background: rgba(42,98,201,0.95);
    }

    /* --- Checkboxes / radios --- */
    QCheckBox, QRadioButton { spacing: 8px; }
    QCheckBox::indicator, QRadioButton::indicator {
        width: 16px; height: 16px;
    }

    /* --- Tables --- */
    QTableView, QTableWidget {
        background: #181a1f;
        border: 1px solid rgba(255,255,255,0.10);
        border-radius: 12px;
        gridline-color: rgba(255,255,255,0.06);
        selection-background-color: rgba(42,98,201,0.35);
        selection-color: #ffffff;
        alternate-background-color: #1b1d23;
    }
    QHeaderView::section {
        background: #1c1d21;
        color: rgba(230,232,238,0.85);
        padding: 7px 10px;
        border: none;
        border-bottom: 1px solid rgba(255,255,255,0.10);
        font-weight: 600;
    }
    QTableCornerButton::section {
        background: #1c1d21;
        border: none;
    }

    /* --- GroupBox --- */
    QGroupBox {
        border: 1px solid rgba(255,255,255,0.10);
        border-radius: 12px;
        margin-top: 10px;
        padding: 10px;
    }
    QGroupBox::title {
        subcontrol-origin: margin;
        left: 12px;
        padding: 0 6px;
        color: rgba(230,232,238,0.75);
    }

    /* --- Scrollbar --- */
    QScrollBar:vertical {
        background: transparent;
        width: 12px;
        margin: 2px;
    }
    QScrollBar::handle:vertical {
        background: rgba(255,255,255,0.16);
        border-radius: 6px;
        min-height: 22px;
    }
    QScrollBar::handle:vertical:hover { background: rgba(255,255,255,0.22); }
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }

    /* --- Status bar --- */
    QStatusBar {
        background: #1c1d21;
        border-top: 1px solid rgba(255,255,255,0.08);
    }

    """


def qss_light() -> str:
    return r"""
    QWidget { font-size: 12px; }

    QMainWindow, QWidget {
        background: #f6f7fb;
        color: #1d2129;
    }

    QToolTip {
        background: #111318;
        color: #ffffff;
        border: 1px solid rgba(255,255,255,0.18);
        padding: 6px 8px;
        border-radius: 6px;
    }

    QFrame[panel="true"], QWidget[panel="true"] {
        background: #ffffff;
        border: 1px solid rgba(0,0,0,0.08);
        border-radius: 12px;
    }

    QTabWidget::pane {
        border: 1px solid rgba(0,0,0,0.10);
        border-radius: 12px;
        top: -1px;
        background: #ffffff;
    }
    QTabBar::tab {
        background: transparent;
        border: 1px solid transparent;
        padding: 8px 12px;
        margin-right: 6px;
        border-radius: 10px;
        color: rgba(29,33,41,0.65);
        font-weight: 500;
    }
    QTabBar::tab:selected {
        background: rgba(42,98,201,0.14);
        border: 1px solid rgba(42,98,201,0.30);
        color: #1d2129;
    }
    QTabBar::tab:hover {
        background: rgba(0,0,0,0.04);
        color: #1d2129;
    }

    QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox, QDoubleSpinBox, QComboBox {
        background: #ffffff;
        border: 1px solid rgba(0,0,0,0.12);
        border-radius: 10px;
        padding: 6px 10px;
        selection-background-color: rgba(42,98,201,0.25);
    }
    QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {
        border: 1px solid rgba(42,98,201,0.60);
    }
    QComboBox::drop-down { border: none; width: 24px; }

    QPushButton, QToolButton {
        background: rgba(0,0,0,0.03);
        border: 1px solid rgba(0,0,0,0.10);
        border-radius: 10px;
        padding: 7px 12px;
        color: #1d2129;
    }
    QPushButton:hover, QToolButton:hover {
        background: rgba(0,0,0,0.05);
        border-color: rgba(0,0,0,0.14);
    }
    QPushButton:pressed, QToolButton:pressed {
        background: rgba(42,98,201,0.16);
        border-color: rgba(42,98,201,0.30);
    }
    QPushButton:disabled, QToolButton:disabled {
        color: rgba(29,33,41,0.35);
        background: rgba(0,0,0,0.02);
        border-color: rgba(0,0,0,0.06);
    }
    QPushButton[primary="true"] {
        background: rgba(42,98,201,0.92);
        border-color: rgba(42,98,201,0.95);
        color: white;
    }
    QPushButton[primary="true"]:hover { background: rgba(42,98,201,0.98); }

    QTableView, QTableWidget {
        background: #ffffff;
        border: 1px solid rgba(0,0,0,0.10);
        border-radius: 12px;
        gridline-color: rgba(0,0,0,0.06);
        selection-background-color: rgba(42,98,201,0.20);
        selection-color: #111318;
        alternate-background-color: #f2f4f9;
    }
    QHeaderView::section {
        background: #f6f7fb;
        color: rgba(29,33,41,0.75);
        padding: 7px 10px;
        border: none;
        border-bottom: 1px solid rgba(0,0,0,0.10);
        font-weight: 600;
    }
    QTableCornerButton::section { background: #f6f7fb; border: none; }

    QGroupBox {
        border: 1px solid rgba(0,0,0,0.10);
        border-radius: 12px;
        margin-top: 10px;
        padding: 10px;
    }
    QGroupBox::title {
        subcontrol-origin: margin;
        left: 12px;
        padding: 0 6px;
        color: rgba(29,33,41,0.70);
    }

    QScrollBar:vertical { background: transparent; width: 12px; margin: 2px; }
    QScrollBar::handle:vertical {
        background: rgba(0,0,0,0.18);
        border-radius: 6px;
        min-height: 22px;
    }
    QScrollBar::handle:vertical:hover { background: rgba(0,0,0,0.24); }
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }

    QStatusBar {
        background: #ffffff;
        border-top: 1px solid rgba(0,0,0,0.08);
    }
    """
