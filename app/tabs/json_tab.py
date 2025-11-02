from __future__ import annotations
from typing import Any, List, Union

from PyQt6.QtCore import Qt, QModelIndex
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QTreeView, QHBoxLayout, QLineEdit, QPushButton,
    QLabel, QMenu, QApplication, QAbstractItemView
)
try:
    from app.ui.json_lazy_model import LazyJsonModel
except ModuleNotFoundError:
    # fallback if running without the package root on sys.path
    from ui.json_lazy_model import LazyJsonModel

JSON = Union[dict, list, str, int, float, bool, None]

class JsonTab(QWidget):
    """
    Lazy JSON tree with search + inline editing for scalar values.
    Right-click for copy key/value/path.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self._model: LazyJsonModel | None = None
        self._data: JSON | None = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)

        # --- Search bar ---
        bar = QHBoxLayout()
        self.search_edit = QLineEdit(self); self.search_edit.setPlaceholderText("Search key or value…")
        self.search_prev = QPushButton("Prev", self)
        self.search_next = QPushButton("Next", self)
        self.search_count = QLabel("", self)

        bar.addWidget(QLabel("Find:", self))
        bar.addWidget(self.search_edit, 1)
        bar.addWidget(self.search_prev)
        bar.addWidget(self.search_next)
        bar.addWidget(self.search_count)
        outer.addLayout(bar)

        # --- Tree ---
        self.tree = QTreeView(self)
        self.tree.setUniformRowHeights(True)
        self.tree.setAnimated(False)
        self.tree.setSortingEnabled(False)
        self.tree.setAlternatingRowColors(True)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._on_context_menu)

        # enable editing interactions (PyQt6 scoped enums)
        self.tree.setEditTriggers(
            QAbstractItemView.EditTrigger.EditKeyPressed
            | QAbstractItemView.EditTrigger.DoubleClicked
            | QAbstractItemView.EditTrigger.SelectedClicked
        )

        outer.addWidget(self.tree, 1)

        # Search results state
        self._matches: List[List[str]] = []
        self._match_idx: int = -1

        # Wire actions
        self.search_edit.returnPressed.connect(self._start_search)
        self.search_next.clicked.connect(lambda: self._advance(+1))
        self.search_prev.clicked.connect(lambda: self._advance(-1))

    # ---------------- Public API ----------------

    def load_data(self, data: Any):
        """Maintains your original API name."""
        self._data = data

        self.tree.setUpdatesEnabled(False)
        try:
            self._model = LazyJsonModel(self._data, self)
            self.tree.setModel(self._model)
            # nicer defaults
            self.tree.expand(self._model.index(0, 0, QModelIndex()))
            self.tree.header().setStretchLastSection(True)
            self.tree.header().setDefaultSectionSize(260)
            self._clear_search()
        finally:
            self.tree.setUpdatesEnabled(True)

    # ---------------- Search ----------------

    def _clear_search(self):
        self._matches = []
        self._match_idx = -1
        self.search_count.setText("")

    def _start_search(self):
        text = self.search_edit.text().strip()
        self._clear_search()
        if not text or self._data is None:
            return
        self._matches = []
        self._gather_matches(self._data, [], text.lower())
        if not self._matches:
            self.search_count.setText("0 results")
            return
        self.search_count.setText(f"{len(self._matches)} results")
        self._match_idx = 0
        self._reveal_path(self._matches[0], focus=True)

    def _advance(self, delta: int):
        if not self._matches:
            self._start_search()
            return
        self._match_idx = (self._match_idx + delta) % len(self._matches)
        self._reveal_path(self._matches[self._match_idx], focus=True)

    def _gather_matches(self, node: JSON, path: List[str], needle: str):
        # Match keys or scalar values via substring (case-insensitive)
        if isinstance(node, dict):
            for k, v in node.items():
                if needle in str(k).lower():
                    self._matches.append(path + [str(k)])
                self._gather_matches(v, path + [str(k)], needle)
        elif isinstance(node, list):
            for i, v in enumerate(node):
                self._gather_matches(v, path + [str(i)], needle)
        else:
            if needle in str(node).lower():
                self._matches.append(path)

    # ---------------- Tree helpers ----------------

    def _reveal_path(self, path: List[str], focus: bool = False):
        """Expand the tree along 'path' (list of key/index strings) and select the final node."""
        if self._model is None or not path:
            return

        index = QModelIndex()  # root
        for component in path:
            # Find child row whose column 0 text == component
            found = None
            rows = self._model.rowCount(index)
            for r in range(rows):
                child_idx = self._model.index(r, 0, index)
                if not child_idx.isValid():
                    continue
                key = self._model.data(child_idx, Qt.ItemDataRole.DisplayRole)
                if key == component:
                    found = child_idx
                    break
            if found is None:
                return  # path not found in current materialization
            self.tree.expand(found)
            index = found

        sel_idx = index.siblingAtColumn(1)  # focus value column for quick editing
        self.tree.setCurrentIndex(sel_idx)
        self.tree.scrollTo(sel_idx, QAbstractItemView.ScrollHint.PositionAtCenter)
        if focus:
            self.tree.setFocus(Qt.FocusReason.OtherFocusReason)

    # ---------------- Context menu ----------------

    def _on_context_menu(self, pos):
        idx = self.tree.indexAt(pos)
        if not idx.isValid():
            return
        path = self._path_for_index(idx)

        menu = QMenu(self)
        act_copy_key = menu.addAction("Copy Key")
        act_copy_val = menu.addAction("Copy Value")
        act_copy_path = menu.addAction("Copy JSON Path")

        action = menu.exec(self.tree.viewport().mapToGlobal(pos))
        if action is None:
            return

        if action == act_copy_key:
            key = self._model.data(idx.siblingAtColumn(0), Qt.ItemDataRole.DisplayRole)
            QApplication.clipboard().setText(str(key))
        elif action == act_copy_val:
            val = self._model.data(idx.siblingAtColumn(1), Qt.ItemDataRole.DisplayRole)
            QApplication.clipboard().setText(str(val))
        elif action == act_copy_path and path:
            QApplication.clipboard().setText(self._path_to_string(path))

    def _path_for_index(self, idx):
        path: List[str] = []
        cur = idx.siblingAtColumn(0)
        while cur.isValid():
            key = self._model.data(cur, Qt.ItemDataRole.DisplayRole)
            parent = cur.parent()
            if not parent.isValid():
                break
            path.insert(0, str(key))
            cur = parent
        return path

    @staticmethod
    def _path_to_string(path: List[str]) -> str:
        # Turn ["root", "properties", "arr", "3", "key"] into properties.arr[3].key
        parts: List[str] = []
        for comp in path:
            if comp.isdigit() and parts:
                parts[-1] = f"{parts[-1]}[{comp}]"
            else:
                parts.append(comp if not parts else "." + comp)
        return "".join(parts)
