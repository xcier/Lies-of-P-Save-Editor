# app/ui/main_window.py
from __future__ import annotations
import os, re, sys, subprocess, json
from pathlib import Path
from typing import Optional, Dict, Any, Iterable, Callable

from PyQt6.QtCore import QThread, Qt
from PyQt6.QtGui import QAction, QIcon, QPalette, QColor
from PyQt6.QtWidgets import (
    QMainWindow, QTabWidget, QStatusBar, QFileDialog,
    QMessageBox, QMenuBar, QMenu, QApplication, QSplitter, QWidget, QToolButton,
    QGraphicsDropShadowEffect
)

from app.core.settings import Settings
from app.core.cheats import (
    auto_plat_achievements,
    insane_stats,
    godmode,
    max_currency,
    unlock_all_locations,
)
from app.core.file_manager import ensure_uesave_ok
from app.utils.resources import find_app_icon
from app.ui.sidenav import SideNav  # public API

from app.tabs.character_tab import CharacterTab
from app.tabs.stats_tab import StatsTab
from app.tabs.inventory_tab import InventoryTab
from app.tabs.builds_tab import BuildsTab
from app.tabs.json_tab import JsonTab
from app.tabs.mission_tab import MissionTab
from app.tabs.currency_tab import CurrencyTab
from app.tabs.fast_travel_tab import FastTravelTab
from app.tabs.about_tab import AboutTab
from app.tabs.slots_gear_tab import SlotsGearTab
from app.ui.workers import LoadWorker
from app.ui.async_save import SaveSavAsync

LOCKED_KEYS = ("character", "stats", "slots", "weapons", "currency", "inventory", "missions", "fasttravel")

# --------- robust marker finder ---------
_SLOT_PATTERNS = (
    re.compile(r"use\s*slot\s*data[_\-]?0\b", re.I),
    re.compile(r"slot\s*data[_\-]?0\b", re.I),
)

def _has_slot_marker(obj: Any, max_nodes: int = 500000) -> bool:
    stack = [obj]; seen = 0
    while stack:
        cur = stack.pop(); seen += 1
        if seen > max_nodes: break
        if isinstance(cur, dict):
            for k, v in cur.items():
                if isinstance(k, str) and any(p.search(k) for p in _SLOT_PATTERNS): return True
                if isinstance(v, (dict, list, tuple)): stack.append(v)
                elif isinstance(v, str) and any(p.search(v) for p in _SLOT_PATTERNS): return True
            name = cur.get("name") or cur.get("Name") or cur.get("key")
            if isinstance(name, str) and any(p.search(name) for p in _SLOT_PATTERNS): return True
        elif isinstance(cur, (list, tuple)):
            stack.extend(cur)
        elif isinstance(cur, str):
            if any(p.search(cur) for p in _SLOT_PATTERNS): return True
    return False
# ---------------------------------------


class MainWindow(QMainWindow):
    # ===== Settings helpers (tolerant .get/.set) =====
    def _sget(self, key: str, default=None):
        s = self.settings
        try:
            if hasattr(s, "get"):
                return s.get(key, default)
            if hasattr(s, "__getitem__"):
                try:
                    val = s[key]
                    return val() if callable(val) else val
                except Exception:
                    return default
            val = getattr(s, key, default)
            return val() if callable(val) else val
        except Exception:
            return default

    def _sset(self, key: str, value):
        s = self.settings
        try:
            if hasattr(s, "set"): s.set(key, value)
            elif hasattr(s, "__setitem__"): s[key] = value
            else: setattr(s, key, value)
            if hasattr(s, "save"): s.save()
        except Exception:
            pass

    # busy / actions
    def _init_busy(self, actions: Iterable[QAction] = ()):
        self._busy = False
        self._all_actions = list(actions)

    def _set_busy(self, busy: bool):
        if getattr(self, "_busy", False) == busy:
            return
        self._busy = busy
        for act in getattr(self, "_all_actions", []):
            try: act.setEnabled(not busy)
            except Exception: pass
        try:
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor if busy else Qt.CursorShape.ArrowCursor)
        except Exception:
            pass

    # worker runner
    def _run_worker(self, worker_obj, finished_cb: Callable, error_cb: Callable):
        t = QThread(self); w = worker_obj
        w.moveToThread(t)
        t.started.connect(w.run)
        w.finished.connect(finished_cb)
        w.error.connect(error_cb)
        w.finished.connect(t.quit); w.error.connect(t.quit)
        t.finished.connect(w.deleteLater); t.finished.connect(t.deleteLater)
        t.start()
        return t, w

    # recent files / last folder
    _recent_key = "recent_files"
    _last_dir_key = "last_dir"
    _default_template_key = "default_template_sav"

    def _init_recent_menu(self, menubar: QMenuBar, settings: Settings, max_items: int = 5):
        self._recent_max = max(1, int(max_items))
        self._recent_menu: QMenu = menubar.addMenu("&Recent")
        self._refresh_recent_menu()

    def _push_recent(self, path: str):
        rec = self._sget(self._recent_key, [])
        if callable(rec):
            try: rec = rec()
            except Exception: rec = []
        if not isinstance(rec, (list, tuple)):
            rec = []
        rec = list(rec)
        if path in rec: rec.remove(path)
        rec.insert(0, path)
        rec = rec[: self._recent_max]
        self._sset(self._recent_key, rec)
        self._sset(self._last_dir_key, os.path.dirname(path))
        self._refresh_recent_menu()

    def _refresh_recent_menu(self):
        self._recent_menu.clear()
        rec = self._sget(self._recent_key, [])
        if callable(rec):
            try: rec = rec()
            except Exception: rec = []
        if not isinstance(rec, (list, tuple)): rec = []
        if not rec:
            a = QAction("(Empty)", self); a.setEnabled(False)
            self._recent_menu.addAction(a); return
        for p in rec:
            a = QAction(str(p), self)
            a.triggered.connect(lambda _, x=p: self._open_path(x))
            self._recent_menu.addAction(a)

    def _choose_open_path(self) -> str:
        start = self._sget(self._last_dir_key, "") or ""
        path, _ = QFileDialog.getOpenFileName(self, "Open Save File", start, "Save Files (*.sav *.json)")
        if path: self._push_recent(path)
        return path

    def _choose_save_path(self, title: str, suggested: str, filt: str) -> str:
        start_dir = self._sget(self._last_dir_key, "") or ""
        start = os.path.join(start_dir, suggested) if start_dir else suggested
        path, _ = QFileDialog.getSaveFileName(self, title, start, filt)
        if path: self._sset(self._last_dir_key, os.path.dirname(path))
        return path

    # geometry persist
    def _restore_geometry(self):
        try:
            geo = self._sget("win_geo", None)
            if geo: self.restoreGeometry(geo)
            state = self._sget("win_state", None)
            if state: self.restoreState(state)
        except Exception:
            pass

    def _save_geometry(self):
        try:
            self._sset("win_geo", self.saveGeometry())
            self._sset("win_state", self.saveState())
        except Exception:
            pass

    # drag & drop
    def enable_drag_drop(self):
        self.setAcceptDrops(True)

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            for u in e.mimeData().urls():
                if u.toLocalFile().lower().endswith((".sav", ".json")):
                    e.acceptProposedAction(); return
        e.ignore()

    def dropEvent(self, e):
        for u in e.mimeData().urls():
            p = u.toLocalFile()
            if p.lower().endswith((".sav", ".json")):
                if self._dirty and not self._confirm_discard():
                    return
                self._open_path(p); break

    def __init__(self):
        super().__init__()
        # --- VERSION BUMPED TO V1.01 ---
        self.setWindowTitle("Lies of P Save Editor V1.01 Created by ProtoBuffers[*]")
        self.resize(1180, 760)

        # icon
        ico_path = find_app_icon()
        if ico_path and os.path.exists(ico_path):
            ico = QIcon(ico_path)
            self.setWindowIcon(ico)
            app = QApplication.instance()
            if app: app.setWindowIcon(ico)

        self.settings = Settings()

        # >>> THEME PREFERENCE AT STARTUP <<<
        # pull saved preference (default to True = dark mode by default)
        self._dark_mode_pref = bool(self._sget("dark_mode", True))
        # actually apply the palette so the whole UI starts in that mode
        self._apply_theme("dark" if self._dark_mode_pref else "light")

        # uesave preflight
        try:
            ensure_uesave_ok()
            self._uesave_hint = "uesave: OK"
        except Exception as e:
            self._uesave_hint = "uesave: MISSING"
            self._show_uesave_error(str(e))

        # tabs
        self.tabs = QTabWidget(self)
        self.tabs.setTabPosition(QTabWidget.TabPosition.North)
        try: self.tabs.tabBar().hide()
        except Exception: self.tabs.setTabBarAutoHide(True)

        self.character_tab   = CharacterTab(self)
        self.stats_tab       = StatsTab(self)
        self.slots_tab       = SlotsGearTab(self)
        self.build_tab       = BuildsTab(self)
        self.currency_tab    = CurrencyTab(self)
        self.inventory_tab   = InventoryTab(self)
        self.mission_tab     = MissionTab(self)
        self.fast_travel_tab = FastTravelTab(self)
        self.json_tab        = JsonTab(self)
        self.about_tab       = AboutTab(self)

        self._tab_index_by_key: Dict[str, int] = {}
        def add_page(key: str, widget: QWidget):
            idx = self.tabs.addTab(widget, key)
            self._tab_index_by_key[key] = idx

        add_page("character",   self.character_tab)
        add_page("stats",       self.stats_tab)
        add_page("slots",       self.slots_tab)
        add_page("weapons",     self.build_tab)
        add_page("currency",    self.currency_tab)
        add_page("inventory",   self.inventory_tab)
        add_page("missions",    self.mission_tab)
        add_page("fasttravel",  self.fast_travel_tab)
        add_page("json",        self.json_tab)
        add_page("about",       self.about_tab)

        # nav
        items = [
            ("character",  "Character",   "Cha", None),
            ("stats",      "Stats",       "Sta", None),
            ("slots",      "Slots",       "Slo", None),
            ("weapons",    "Weapons",     "Wea", None),
            ("currency",   "Currency",    "Cur", None),
            ("inventory",  "Inventory",   "Inv", None),
            ("missions",   "Missions",    "Mis", None),
            ("fasttravel", "Fast Travel", "Fas", None),
            ("json",       "JSON",        "JSO", None),
            ("about",      "About",       "Ab",  None),
        ]
        self._nav_expanded_width = 210
        self.nav = SideNav(items, expanded_width=self._nav_expanded_width, collapsed_width=0, parent=self)
        self.nav.activated.connect(self._on_nav_activated)
        self.nav.expandedChanged.connect(self._on_nav_expanded_changed)

        for key in LOCKED_KEYS:
            self.nav.set_locked(key, True)
        self.nav.set_active("about")
        self.tabs.setCurrentIndex(self._tab_index_by_key["about"])

        self.splitter = QSplitter(Qt.Orientation.Horizontal, self)
        self.splitter.addWidget(self.nav)
        self.splitter.addWidget(self.tabs)
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        self.setCentralWidget(self.splitter)

        # floating hamburger when nav hidden
        self.float_toggle = QToolButton(self.tabs)
        self.float_toggle.setObjectName("FloatHamburger")
        self.float_toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self.float_toggle.setArrowType(Qt.ArrowType.NoArrow)
        self.float_toggle.setText("☰")
        self.float_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self.float_toggle.setAutoRaise(True)
        self.float_toggle.clicked.connect(lambda: self.nav.set_expanded(True))
        self.float_toggle.setStyleSheet("""
            QToolButton#FloatHamburger {
                background: rgba(10,12,16,0.94);
                border: 1px solid rgba(255,255,255,0.18);
                border-radius: 10px;
                padding: 6px 10px;
                color: #eef3fb;
                font-size: 18px;
            }
            QToolButton#FloatHamburger:hover { background: rgba(25,28,34,0.96); }
        """)
        shadow = QGraphicsDropShadowEffect(self.float_toggle)
        shadow.setBlurRadius(18); shadow.setOffset(0, 2)
        shadow.setColor(QColor(0, 0, 0, 200))
        self.float_toggle.setGraphicsEffect(shadow)
        self.float_toggle.hide()
        self._position_float_button()

        # ---------- Menus ----------
        menubar: QMenuBar = self.menuBar()

        file_menu: QMenu = menubar.addMenu("&File")
        open_action          = QAction("&Open…", self)
        save_json_action     = QAction("Save &JSON As…", self)
        save_sav_action      = QAction("Save &Sav As…", self)
        set_template_action  = QAction("Set &Default Template .sav…", self)
        exit_action          = QAction("E&xit", self)

        file_menu.addAction(open_action)
        file_menu.addSeparator()
        file_menu.addAction(save_json_action)
        file_menu.addAction(save_sav_action)
        file_menu.addAction(set_template_action)
        file_menu.addSeparator()
        file_menu.addAction(exit_action)

        set_template_action.triggered.connect(self._choose_default_template_sav)

        cheats_menu: QMenu = menubar.addMenu("&Quick Cheats")
        self.act_auto_plat = QAction("Auto Plat/Achievements", self)
        self.act_auto_plat.triggered.connect(self._cheat_auto_plat)
        cheats_menu.addAction(self.act_auto_plat)

        self.act_insane = QAction("INSANE STATS", self)
        self.act_insane.triggered.connect(self._cheat_insane_stats)
        cheats_menu.addAction(self.act_insane)

        self.act_god = QAction("GODMODE", self)
        self.act_god.triggered.connect(self._cheat_godmode)
        cheats_menu.addAction(self.act_god)

        self.act_currency = QAction("MAX CURRENCY", self)
        self.act_currency.triggered.connect(self._cheat_max_currency)
        cheats_menu.addAction(self.act_currency)

        self.act_locations = QAction("ALL LOCATIONS", self)
        self.act_locations.triggered.connect(self._cheat_all_locations)
        cheats_menu.addAction(self.act_locations)

        # Status bar
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        if hasattr(self, "_uesave_hint"):
            self.status_bar.showMessage(self._uesave_hint, 4000)

        # >>> THEME TOGGLE BUTTON IN STATUS BAR <<<
        self.theme_btn = QToolButton(self)
        self.theme_btn.setObjectName("ThemeToggleBtn")
        self.theme_btn.setCheckable(True)
        self.theme_btn.setChecked(self._dark_mode_pref)
        self.theme_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.theme_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self.theme_btn.setText("🌙 Dark" if self._dark_mode_pref else "☀ Light")
        self.theme_btn.setToolTip("Toggle Dark / Light Mode")
        self.theme_btn.setStyleSheet("""
            QToolButton#ThemeToggleBtn {
                padding: 2px 8px;
                border-radius: 6px;
                font-weight: 500;
                border: 1px solid rgba(255,255,255,0.18);
            }
        """)
        self.theme_btn.clicked.connect(self._on_theme_button_clicked)
        # put it on the right side of the status bar so it's always visible
        self.status_bar.addPermanentWidget(self.theme_btn)

        # Wire actions
        open_action.triggered.connect(self.open_file)
        save_json_action.triggered.connect(self.save_json)
        save_sav_action.triggered.connect(self.save_sav)
        exit_action.triggered.connect(self.close)

        # Disable save until open; collect for busy state
        self.save_json_action = save_json_action
        self.save_sav_action  = save_sav_action
        save_json_action.setEnabled(False)
        save_sav_action.setEnabled(False)
        self._init_busy(actions=[
            open_action, save_json_action, save_sav_action,
            self.act_auto_plat, self.act_insane, self.act_god,
            self.act_currency, self.act_locations
        ])

        # shortcuts / tips / init
        self._init_recent_menu(menubar, self.settings, max_items=5)
        open_action.setShortcut("Ctrl+O")
        save_sav_action.setShortcut("Ctrl+S")
        save_json_action.setShortcut("Ctrl+Shift+S")
        exit_action.setShortcut("Alt+F4")
        open_action.setStatusTip("Open a .sav or .json")
        save_sav_action.setStatusTip("Write current data to .sav via uesave")
        save_json_action.setStatusTip("Export current data to JSON")
        set_template_action.setStatusTip("Remember a default .sav template to use when saving from JSON")
        self._restore_geometry()
        self.enable_drag_drop()

        # ---------- Apply theme to theme-aware children ----------
        try:
            if hasattr(self.fast_travel_tab, "apply_theme"):
                self.fast_travel_tab.apply_theme(self._dark_mode_pref)
        except Exception:
            pass

        try:
            if hasattr(self.about_tab, "apply_theme"):
                self.about_tab.apply_theme(self._dark_mode_pref)
        except Exception:
            pass

        try:
            if hasattr(self.nav, "apply_theme"):
                self.nav.apply_theme(self._dark_mode_pref)
        except Exception:
            pass

        # State
        self.data: Optional[Dict[str, Any]] = None
        self.current_file: Optional[str] = None
        self._dirty: bool = False
        self._thread: Optional[QThread] = None
        self._worker: Optional[object] = None

        # Dynamic title (alias + level)
        try:
            self.character_tab.level_spin.valueChanged.connect(lambda _: self._refresh_title())
            self.character_tab.alias_combo.currentTextChanged.connect(lambda _: self._refresh_title())
            self.character_tab.guid_edit.editingFinished.connect(self._refresh_title)
        except Exception:
            pass
        self._refresh_title()

    # ---------- layout helpers ----------
    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._position_float_button()

    def _position_float_button(self):
        margin = 12
        self.float_toggle.move(margin, margin)
        self.float_toggle.raise_()

    def _on_nav_expanded_changed(self, expanded: bool) -> None:
        if expanded:
            self.nav.setVisible(True)
            self.splitter.setSizes([self._nav_expanded_width, max(1, self.width() - self._nav_expanded_width)])
            self.float_toggle.hide()
        else:
            self.splitter.setSizes([0, 1])
            self.nav.setVisible(False)
            self.float_toggle.show()
            self._position_float_button()

    # ---------- SideNav handlers ----------
    def _on_nav_activated(self, key: str) -> None:
        if key in LOCKED_KEYS and self.nav.is_locked(key): return
        idx = self._tab_index_by_key.get(key)
        if idx is None: return
        self.tabs.setCurrentIndex(idx)
        self.nav.set_active(key)

    # ---------- File I/O ----------
    def open_file(self):
        if getattr(self, "_busy", False): return
        if self._dirty and not self._confirm_discard(): return
        path = self._choose_open_path()
        if path: self._open_path(path)

    def _open_path(self, path: str):
        if getattr(self, "_busy", False): return
        self.status_bar.showMessage("Loading…")
        self._set_busy(True)
        self._thread, self._worker = self._run_worker(
            LoadWorker(path),
            self._on_loaded_ok_wrap,
            self._on_loaded_error_wrap
        )
        try:
            self._worker.progress.connect(lambda pct, note: self.status_bar.showMessage(f"{note} ({pct}%)"))
        except Exception: pass

    def _on_loaded_ok_wrap(self, data: dict, path: str):
        try:
            self._on_loaded_ok(data, path)
            self._push_recent(path)
        finally:
            self._set_busy(False); self._worker = None; self._thread = None

    def _on_loaded_error_wrap(self, msg: str):
        try:
            self._on_loaded_error(msg)
        finally:
            self._set_busy(False); self._worker = None; self._thread = None

    def _on_loaded_ok(self, data: dict, path: str):
        self.data = data; self.current_file = path; self._mark_dirty(False)
        for tab in (
            self.character_tab, self.stats_tab, self.inventory_tab,
            self.mission_tab, self.currency_tab, self.fast_travel_tab,
            self.json_tab, self.slots_tab, self.build_tab
        ):
            try: tab.load_data(data)
            except Exception: pass
        self._update_lock_state()
        self.save_json_action.setEnabled(True)
        self.save_sav_action.setEnabled(True)
        self.status_bar.showMessage(f"Opened: {os.path.basename(path)}", 4000)
        self._refresh_title()

    def _on_loaded_error(self, msg: str):
        QMessageBox.critical(self, "Load Error", msg)

    def save_json(self):
        """
        Export current in-memory data as pretty-formatted JSON (indent=2, UTF-8).
        """
        if not self.data or getattr(self, "_busy", False):
            return

        default = os.path.splitext(os.path.basename(self.current_file or ""))[0] + ".json"
        target = self._choose_save_path("Save JSON As", default, "JSON Files (*.json)")
        if not target:
            return
        if not target.lower().endswith(".json"):
            target += ".json"

        try:
            with open(target, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
                f.write("\n")
            self.status_bar.showMessage(f"Saved: {target}", 4000)
            self._after_save()
        except Exception as e:
            QMessageBox.critical(self, "Save Error", f"Failed to save JSON:\n{e}")

    # ----- Template detection helpers -----
    def _resources_dir(self) -> Path:
        try:
            return Path(__file__).resolve().parents[1] / "resources"
        except Exception:
            return Path.cwd()

    def _choose_default_template_sav(self):
        start = self._sget(self._last_dir_key, "") or ""
        p, _ = QFileDialog.getOpenFileName(self, "Choose Default Template .sav", start, "Unreal Save (*.sav)")
        if p:
            self._sset(self._default_template_key, p)
            self._sset(self._last_dir_key, os.path.dirname(p))
            QMessageBox.information(self, "Template saved", f"Default template set:\n{p}")

    def _find_sav_template(self) -> Optional[str]:
        """
        Find a suitable .sav template to use when saving from JSON.
        Order:
          1) current file if it's a .sav
          2) data['_meta']['src_sav'] if present and exists
          3) sibling .sav with same stem as current .json
          4) settings: default_template_sav if exists
          5) app/resources/blank_template.sav if exists
          6) None (caller may prompt)
        """
        # 1) current file if .sav
        if self.current_file and str(self.current_file).lower().endswith(".sav"):
            return self.current_file

        # 2) meta hint
        try:
            src = (self.data or {}).get("_meta", {}).get("src_sav")
            if src and os.path.isfile(src):
                return src
        except Exception:
            pass

        # 3) sibling .sav with same stem
        if self.current_file and str(self.current_file).lower().endswith(".json"):
            stem = os.path.splitext(self.current_file)[0]
            sibling = stem + ".sav"
            if os.path.isfile(sibling):
                return sibling

        # 4) default template from settings
        templ = self._sget(self._default_template_key, "")
        if templ and os.path.isfile(templ):
            return templ

        # 5) resources fallback
        res = self._resources_dir() / "blank_template.sav"
        if res.is_file():
            return str(res)

        # 6) nothing found
        return None

    def save_sav(self):
        if not self.data or getattr(self, "_busy", False):
            return

        default = os.path.splitext(os.path.basename(self.current_file or ""))[0] + ".sav"
        target = self._choose_save_path("Save .sav As", default, "Unreal Save (*.sav)")
        if not target:
            return

        # Resolve a valid src .sav (GVAS template)
        src = self._find_sav_template()
        if not src:
            # prompt user as the last resort
            QMessageBox.information(
                self, "Select Source .sav",
                "I need a .sav template to write the binary save.\n"
                "Please select the original or a blank template .sav."
            )
            src, _ = QFileDialog.getOpenFileName(
                self, "Choose Source .sav (template)",
                self._sget(self._last_dir_key, "") or "", "Unreal Save (*.sav)"
            )
            if not src:
                QMessageBox.warning(self, "Canceled", "No source .sav was selected.")
                return
            self._sset(self._last_dir_key, os.path.dirname(src))

        # Guard against accidental JSON template
        if not str(src).lower().endswith(".sav"):
            QMessageBox.critical(
                self, "Invalid Template",
                f"The selected template isn't a .sav file:\n{src}"
            )
            return

        self._set_busy(True)
        self.status_bar.showMessage("Invoking uesave… (65%)")

        self._saver = SaveSavAsync(
            data=self.data,
            target_path=target,
            src_path=src,
            mode=os.environ.get("UESAVE_SAVE_MODE", "auto"),
            parent=self,
        )
        self._saver.progress.connect(lambda p, m: self.status_bar.showMessage(f"{m} ({p}%)"))
        self._saver.finished.connect(self._on_save_done)
        self._saver.error.connect(self._on_save_error)
        self._saver.canceled.connect(lambda: self._after_save())
        self._saver.start()

    def _on_save_done(self, path: str):
        self.status_bar.showMessage(f"Saved: {path}", 4000)
        self._after_save()

    def _on_save_error(self, msg: str):
        hint = ""
        if msg and ("GVAS" in msg or "non-standard magic" in msg):
            hint = (
                "\n\nTip: It looks like a JSON path was used as the source/template.\n"
                "Make sure the source path is a real .sav (GVAS) file."
            )
        QMessageBox.critical(self, "Save Error", (msg or "Unknown error") + hint)
        self._after_save()

    def _after_save(self):
        self._mark_dirty(False)
        self._set_busy(False)
        self._saver = None
        self._worker = None
        self._thread = None

    # ---------- Cheats ----------
    def _cheat_auto_plat(self):
        if not self.data:
            QMessageBox.information(self, "Auto Plat/Achievements", "Please load Account#"); return
        found, changed = auto_plat_achievements(self.data)
        if not found:
            QMessageBox.information(self, "Auto Plat/Achievements", "Please load Account#")
        elif changed > 0:
            self._mark_dirty(True)
            QMessageBox.information(self, "Auto Plat/Achievements", f"Cheat applied.\nSet {changed} flags to True.")
            self.status_bar.showMessage(f"Auto Plat/Achievements: set {changed} flags.", 6000)
            try: self.json_tab.load_data(self.data)
            except Exception: pass
        else:
            QMessageBox.information(self, "Auto Plat/Achievements", "Achievements found, nothing to update.")

    def _cheat_insane_stats(self):
        if not self.data:
            QMessageBox.information(self, "INSANE STATS", "Please load Account#"); return
        counters = insane_stats(self.data)
        total = sum(counters.values())
        if total > 0:
            self._mark_dirty(True)
            QMessageBox.information(
                self, "INSANE STATS",
                "Cheat applied.\n"
                f"Character: {counters['character']} fields\n"
                f"Lamp: {counters['lamp']} fields\n"
                f"Stats (primary): {counters['stats_primary']} fields\n"
                f"Stats (secondary): {counters['stats_secondary']} fields"
            )
            self.status_bar.showMessage(f"INSANE STATS: updated {total} fields.", 6000)
            for tab in (self.character_tab, self.stats_tab, self.json_tab):
                try: tab.load_data(self.data)
                except Exception: pass
        else:
            QMessageBox.information(self, "INSANE STATS", "No matching fields found.")

    def _cheat_godmode(self):
        if not self.data:
            QMessageBox.information(self, "GODMODE", "Please load Account#"); return
        changed = godmode(self.data)
        if changed > 0:
            self._mark_dirty(True)
            QMessageBox.information(self, "GODMODE", "Cheat applied.\nHealth set to max.")
            self.status_bar.showMessage(f"GODMODE: set {changed} slots to max.", 6000)
            for tab in (self.stats_tab, self.json_tab):
                try: tab.load_data(self.data)
                except Exception: pass
        else:
            QMessageBox.information(self, "GODMODE", "No health fields found to update.")

    def _cheat_max_currency(self):
        if not self.data:
            QMessageBox.information(self, "MAX CURRENCY", "Please load Account#"); return
        changed = max_currency(self.data, 999_999_999)
        if changed > 0:
            self._mark_dirty(True)
            QMessageBox.information(self, "MAX CURRENCY", f"Cheat applied.\nSet {changed} values.")
            self.status_bar.showMessage(f"MAX CURRENCY: set {changed} values.", 6000)
            for tab in (self.currency_tab, self.json_tab):
                try: tab.load_data(self.data)
                except Exception: pass
        else:
            QMessageBox.information(self, "MAX CURRENCY", "No currency-like values found.")

    def _cheat_all_locations(self):
        if not self.data:
            QMessageBox.information(self, "ALL LOCATIONS", "Please load Account#"); return
        changed = unlock_all_locations(self.data)
        if changed > 0:
            self._mark_dirty(True)
            QMessageBox.information(self, "ALL LOCATIONS", f"Cheat applied.\nUnlocked {changed} entries.")
            self.status_bar.showMessage(f"ALL LOCATIONS: unlocked {changed} entries.", 6000)
            for tab in (self.fast_travel_tab, self.json_tab):
                try: tab.load_data(self.data)
                except Exception: pass
        else:
            QMessageBox.information(self, "ALL LOCATIONS", "No stargazer/teleport entries found.")

    # ---------- Theme ----------
    def _apply_theme(self, mode: str) -> None:
        app = QApplication.instance()
        if app is None:
            return
        if mode.lower() == "dark":
            app.setStyle("Fusion")
            pal = QPalette()
            pal.setColor(QPalette.ColorRole.Window, QColor(34, 36, 41))
            pal.setColor(QPalette.ColorRole.Base, QColor(28, 29, 33))
            pal.setColor(QPalette.ColorRole.AlternateBase, QColor(38, 40, 46))
            pal.setColor(QPalette.ColorRole.WindowText, QColor(230, 230, 235))
            pal.setColor(QPalette.ColorRole.Text, QColor(230, 230, 235))
            pal.setColor(QPalette.ColorRole.ToolTipBase, QColor(255, 255, 220))
            pal.setColor(QPalette.ColorRole.ToolTipText, QColor(20, 20, 20))
            pal.setColor(QPalette.ColorRole.Button, QColor(44, 46, 54))
            pal.setColor(QPalette.ColorRole.ButtonText, QColor(230, 230, 235))
            pal.setColor(QPalette.ColorRole.Highlight, QColor(42, 98, 201))
            pal.setColor(QPalette.ColorRole.HighlightedText, QColor(255, 255, 255))
            pal.setColor(QPalette.ColorRole.BrightText, QColor(255, 64, 64))
            app.setPalette(pal)
        else:
            app.setStyle("Fusion")
            app.setPalette(QPalette())

    def _toggle_dark_mode(self, checked: bool) -> None:
        # True = dark, False = light
        self._apply_theme("dark" if checked else "light")
        try:
            self._sset("dark_mode", bool(checked))
        except Exception:
            pass

        # keep this around so children can read it later
        self._dark_mode_pref = bool(checked)

        # tell FastTravelTab to restyle itself live
        try:
            if hasattr(self, "fast_travel_tab") and self.fast_travel_tab is not None:
                self.fast_travel_tab.apply_theme(bool(checked))
        except Exception:
            pass

        # tell AboutTab so its QTextBrowser colors update
        try:
            if hasattr(self, "about_tab") and self.about_tab is not None and hasattr(self.about_tab, "apply_theme"):
                self.about_tab.apply_theme(bool(checked))
        except Exception:
            pass

        # tell SideNav so its background / text stay readable
        try:
            if hasattr(self, "nav") and self.nav is not None and hasattr(self.nav, "apply_theme"):
                self.nav.apply_theme(bool(checked))
        except Exception:
            pass

        # update the status bar button label
        try:
            if self.theme_btn:
                self.theme_btn.setText("🌙 Dark" if checked else "☀ Light")
        except Exception:
            pass

    def _on_theme_button_clicked(self, checked: bool) -> None:
        """
        Slot for the status bar theme toggle button.
        Updates palette, saves preference, and flips the emoji/text.
        """
        self._toggle_dark_mode(checked)
        try:
            if self.theme_btn:
                self.theme_btn.setText("🌙 Dark" if checked else "☀ Light")
        except Exception:
            pass

    # ---------- Lockout detection ----------
    def _update_lock_state(self) -> None:
        loaded = False
        try: loaded = _has_slot_marker(self.data)
        except Exception: loaded = False

        if not loaded and self.current_file:
            b = os.path.basename(self.current_file)
            loaded = any(p.search(b) for p in _SLOT_PATTERNS)

        for key in LOCKED_KEYS:
            self.nav.set_locked(key, not loaded)

        cur_key = next((k for k, i in self._tab_index_by_key.items() if i == self.tabs.currentIndex()), "about")
        if cur_key in LOCKED_KEYS and not loaded:
            self.tabs.setCurrentIndex(self._tab_index_by_key["about"])
            self.nav.set_active("about")

    # ---------- UESAVE helpers ----------
    def _recheck_uesave(self):
        # kept for startup check + error dialog flow; no menu entry
        try:
            ensure_uesave_ok()
            self.status_bar.showMessage("uesave: OK", 3000)
            QMessageBox.information(self, "UESAVE Ready", "The uesave tool is available.")
        except Exception as e:
            self.status_bar.showMessage("uesave: MISSING", 6000)
            self._show_uesave_error(str(e))

    def _show_uesave_error(self, msg: str) -> None:
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Critical)
        box.setWindowTitle("UESAVE Not Ready")
        box.setText("The uesave tool isn’t available or failed a self-check.")
        box.setInformativeText((msg or "").strip())

        btn_retry   = box.addButton("Retry", QMessageBox.ButtonRole.AcceptRole)
        btn_openres = box.addButton("Open resources folder", QMessageBox.ButtonRole.ActionRole)
        btn_close   = box.addButton("Close", QMessageBox.ButtonRole.RejectRole)
        box.exec()

        if box.clickedButton() is btn_openres:
            res = Path(__file__).resolve().parents[1] / "resources"
            try:
                res.mkdir(exist_ok=True)
                if sys.platform.startswith("win"):
                    os.startfile(str(res))
                elif sys.platform == "darwin":
                    subprocess.Popen(["open", str(res)])
                else:
                    subprocess.Popen(["xdg-open", str(res)])
            except Exception:
                pass
            return self._show_uesave_error(msg)

        if box.clickedButton() is btn_retry:
            try:
                ensure_uesave_ok()
                self.status_bar.showMessage("uesave: OK", 3000)
                QMessageBox.information(self, "UESAVE Ready", "The uesave tool is available.")
                return
            except Exception as e:
                return self._show_uesave_error(str(e))

    # ---------- Window lifecycle ----------
    def closeEvent(self, e):
        if getattr(self, "_busy", False):
            if QMessageBox.question(
                self, "Operation in progress",
                "A task is still running. Quit anyway?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            ) != QMessageBox.StandardButton.Yes:
                e.ignore(); return

        if self._dirty and not self._confirm_discard():
            e.ignore(); return

        self._save_geometry()
        super().closeEvent(e)

    # ---------- helpers ----------
    def _confirm_discard(self) -> bool:
        btn = QMessageBox.question(
            self, "Unsaved changes",
            "You have unsaved changes. Continue and discard them?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        return btn == QMessageBox.StandardButton.Yes

    def _mark_dirty(self, dirty: bool):
        self._dirty = bool(dirty)
        self.setWindowModified(self._dirty)
        self._refresh_title()

    def _refresh_title(self):
        # --- VERSION STRING UPDATED HERE TOO ---
        base = "Lies of P Save Editor V1.01 Created by ProtoBuffers"
        try:
            alias = (self.character_tab.alias_combo.currentText() or "").strip()
            if not alias:
                alias = (self.character_tab.guid_edit.text() or "").strip()
            lvl = self.character_tab.level_spin.value() if self.data else None
            extra = []
            if alias: extra.append(alias)
            if isinstance(lvl, int): extra.append(f"Lv {lvl}")
            if extra: base += " — " + " · ".join(extra)
        except Exception:
            pass
        base += "[*]"
        self.setWindowTitle(base)
