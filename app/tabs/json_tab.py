from __future__ import annotations
from typing import Any, List, Union, Optional
import os
import json
import copy
import re

from PyQt6.QtCore import Qt, QModelIndex
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QTreeView,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QLabel,
    QMenu,
    QApplication,
    QAbstractItemView,
    QSplitter,
    QFileDialog,
    QMessageBox,
)

try:
    from app.ui.json_lazy_model import LazyJsonModel
except ModuleNotFoundError:
    # fallback if running without the package root on sys.path
    from ui.json_lazy_model import LazyJsonModel

try:
    from app.core.file_manager import FileManager
except ModuleNotFoundError:
    FileManager = None  # type: ignore[misc]

JSON = Union[dict, list, str, int, float, bool, None]


def _parse_list_index(label: str) -> Optional[int]:
    """
    Be tolerant about how list indices are shown in the tree.

    Accepts:
      "0"
      "[0]"
      "#0"
      "0: something"
      "[12] foo"
      etc.

    Returns int index or None if no usable number is found.
    """
    s = label.strip()
    # plain digit
    if s.isdigit():
        return int(s)

    # [123]
    m = re.fullmatch(r"\[(\d+)\]", s)
    if m:
        return int(m.group(1))

    # first number in the string (e.g. "0:", "#1", "1 - item")
    m = re.search(r"(\d+)", s)
    if m:
        return int(m.group(1))

    return None


class JsonTab(QWidget):
    """
    Lazy JSON tree with search + inline scalar editing for the main save.

    Features:
      - Left side: main save JSON.
      - Right side: optional compare save JSON (.json or .sav via FileManager).
      - Search (main tree only) with next/prev navigation.
      - Main tree context menu: copy key / value / JSON path.
      - Compare tree context menu:
          * Copy subtree as JSON (to clipboard).
          * Copy subtree into main (replace current node selection).
    """

    def __init__(self, parent=None):
        super().__init__(parent)

        # Data / models
        self._data: JSON | None = None
        self._model: LazyJsonModel | None = None

        self._compare_data: JSON | None = None
        self._compare_model: LazyJsonModel | None = None
        self._compare_path: str | None = None

        # --- Top-level layout ---
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(6)

        # --- Search bar (main tree) ---
        search_row = QHBoxLayout()
        search_row.setContentsMargins(0, 0, 0, 0)
        search_row.setSpacing(4)

        self.search_edit = QLineEdit(self)
        self.search_edit.setPlaceholderText("Search key or value in main JSON…")

        self.search_prev = QPushButton("Prev", self)
        self.search_next = QPushButton("Next", self)
        self.search_count = QLabel("", self)

        search_row.addWidget(QLabel("Find:", self))
        search_row.addWidget(self.search_edit, 1)
        search_row.addWidget(self.search_prev)
        search_row.addWidget(self.search_next)
        search_row.addWidget(self.search_count)

        outer.addLayout(search_row)

        # --- Compare header ---
        compare_row = QHBoxLayout()
        compare_row.setContentsMargins(0, 0, 0, 0)
        compare_row.setSpacing(6)

        self.btn_load_compare = QPushButton("Load Compare Save…", self)
        self.lbl_compare = QLabel("Compare: none", self)
        self.lbl_compare.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )

        compare_row.addWidget(self.btn_load_compare)
        compare_row.addWidget(self.lbl_compare, 1)
        outer.addLayout(compare_row)

        # --- Splitter with main + compare trees ---
        splitter = QSplitter(Qt.Orientation.Horizontal, self)

        # Main tree
        self.tree = QTreeView(self)
        self.tree.setUniformRowHeights(True)
        self.tree.setAlternatingRowColors(True)
        self.tree.setSortingEnabled(False)
        self.tree.setAnimated(False)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.setEditTriggers(
            QAbstractItemView.EditTrigger.EditKeyPressed
            | QAbstractItemView.EditTrigger.DoubleClicked
            | QAbstractItemView.EditTrigger.SelectedClicked
        )
        self.tree.customContextMenuRequested.connect(self._on_context_menu_main)

        splitter.addWidget(self.tree)

        # Compare tree
        self.compare_tree = QTreeView(self)
        self.compare_tree.setUniformRowHeights(True)
        self.compare_tree.setAlternatingRowColors(True)
        self.compare_tree.setSortingEnabled(False)
        self.compare_tree.setAnimated(False)
        self.compare_tree.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu
        )
        self.compare_tree.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.compare_tree.customContextMenuRequested.connect(
            self._on_context_menu_compare
        )

        splitter.addWidget(self.compare_tree)

        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)

        outer.addWidget(splitter, 1)

        # --- Search state ---
        self._matches: List[List[str]] = []
        self._match_idx: int = -1

        # --- Wire signals ---
        self.search_edit.returnPressed.connect(self._start_search)
        self.search_next.clicked.connect(lambda: self._advance_match(+1))
        self.search_prev.clicked.connect(lambda: self._advance_match(-1))
        self.btn_load_compare.clicked.connect(self._load_compare_dialog)

    # ------------------------------------------------------------------
    # Public API (used by MainWindow)
    # ------------------------------------------------------------------
    def load_data(self, data: Any):
        """
        Called by MainWindow when a new save is opened.
        'data' is the parsed JSON structure for the main save.
        """
        self._data = data
        self._rebuild_main_model()
        self._clear_search()

    # ------------------------------------------------------------------
    # Compare loading
    # ------------------------------------------------------------------
    def _load_compare_dialog(self):
        """
        Open a second save/JSON for comparison in the right-hand tree.
        """
        start = ""
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Open Compare Save or JSON",
            start,
            "Saves / JSON (*.sav *.json);;All Files (*)",
        )
        if not path:
            return

        try:
            data = self._load_json_from_path(path)
        except Exception as exc:
            QMessageBox.critical(
                self,
                "Failed to Load Compare Save",
                f"Could not load compare file:\n{path}\n\n{exc}",
            )
            return

        self._compare_data = data
        self._compare_path = path

        self.compare_tree.setUpdatesEnabled(False)
        try:
            self._compare_model = LazyJsonModel(self._compare_data, self)
            self.compare_tree.setModel(self._compare_model)
            if self._compare_model.rowCount(QModelIndex()) > 0:
                self.compare_tree.expand(
                    self._compare_model.index(0, 0, QModelIndex())
                )
            self.compare_tree.header().setStretchLastSection(True)
            self.compare_tree.header().setDefaultSectionSize(260)
        finally:
            self.compare_tree.setUpdatesEnabled(True)

        base = os.path.basename(path) if path else "loaded"
        self.lbl_compare.setText(f"Compare: {base}")

    def _load_json_from_path(self, path: str) -> JSON:
        """
        Load JSON-ish data from a file.

        - If FileManager is available, we use it so .sav behaves like the main
          app (GVAS → JSON).
        - Otherwise, we only support .json here.
        """
        if FileManager is not None:
            return FileManager.load_file(path)

        # Fallback: only raw JSON
        if not path.lower().endswith(".json"):
            raise RuntimeError(
                "Can only open .json here when FileManager is not available."
            )
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    # ------------------------------------------------------------------
    # Main model / UI rebuild
    # ------------------------------------------------------------------
    def _rebuild_main_model(self):
        if self._data is None:
            self._model = None
            self.tree.setModel(None)
            return

        self.tree.setUpdatesEnabled(False)
        try:
            self._model = LazyJsonModel(self._data, self)
            self.tree.setModel(self._model)
            if self._model.rowCount(QModelIndex()) > 0:
                self.tree.expand(self._model.index(0, 0, QModelIndex()))
            self.tree.header().setStretchLastSection(True)
            self.tree.header().setDefaultSectionSize(260)
        finally:
            self.tree.setUpdatesEnabled(True)

    # ------------------------------------------------------------------
    # Search in main JSON
    # ------------------------------------------------------------------
    def _clear_search(self):
        self._matches = []
        self._match_idx = -1
        self.search_count.setText("")

    def _start_search(self):
        text = self.search_edit.text().strip()
        self._clear_search()
        if not text or self._data is None:
            return

        needle = text.lower()
        self._matches = []
        self._gather_matches(self._data, [], needle)

        if not self._matches:
            self.search_count.setText("0 results")
            return

        self.search_count.setText(f"{len(self._matches)} results")
        self._match_idx = 0
        self._reveal_path_main(self._matches[0], focus=True)

    def _advance_match(self, delta: int):
        if not self._matches:
            self._start_search()
            return
        self._match_idx = (self._match_idx + delta) % len(self._matches)
        self._reveal_path_main(self._matches[self._match_idx], focus=True)

    def _gather_matches(self, node: JSON, path: List[str], needle: str):
        # Match keys or scalar values via case-insensitive substring
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

    def _reveal_path_main(self, path: List[str], focus: bool = False):
        """
        Expand the main tree along 'path' and select the final node.
        """
        if self._model is None or not path:
            return

        index = QModelIndex()  # root
        for component in path:
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
                return  # path no longer exists
            self.tree.expand(found)
            index = found

        sel_idx = index.siblingAtColumn(1)
        self.tree.setCurrentIndex(sel_idx)
        self.tree.scrollTo(sel_idx, QAbstractItemView.ScrollHint.PositionAtCenter)
        if focus:
            self.tree.setFocus(Qt.FocusReason.OtherFocusReason)

    # ------------------------------------------------------------------
    # Context menu: MAIN tree
    # ------------------------------------------------------------------
    def _on_context_menu_main(self, pos):
        idx = self.tree.indexAt(pos)
        if not idx.isValid() or self._model is None:
            return

        path = self._path_for_index(idx, self._model)

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

    # ------------------------------------------------------------------
    # Context menu: COMPARE tree
    # ------------------------------------------------------------------
    def _on_context_menu_compare(self, pos):
        idx = self.compare_tree.indexAt(pos)
        if (
            not idx.isValid()
            or self._compare_model is None
            or self._compare_data is None
        ):
            return

        src_path = self._path_for_index(idx, self._compare_model)

        menu = QMenu(self)
        act_copy_json = menu.addAction("Copy Subtree as JSON")
        act_copy_into_main = menu.addAction(
            "Copy Subtree into Main (replace current node)"
        )

        action = menu.exec(self.compare_tree.viewport().mapToGlobal(pos))
        if action is None:
            return

        # Resolve source node
        try:
            src_node = self._resolve_path(self._compare_data, src_path)
        except Exception:
            QMessageBox.warning(
                self, "Copy Failed", "Could not resolve source subtree."
            )
            return

        if action == act_copy_json:
            # Just copy the subtree JSON to clipboard
            try:
                txt = json.dumps(src_node, indent=2, ensure_ascii=False)
            except TypeError:
                txt = str(src_node)
            QApplication.clipboard().setText(txt)
            return

        if action == act_copy_into_main:
            # Need a destination selection in main tree
            dest_idx = self.tree.currentIndex()
            if not dest_idx.isValid() or self._model is None or self._data is None:
                QMessageBox.information(
                    self,
                    "Select Destination",
                    "Select a node in the main JSON tree first, then try again.",
                )
                return

            dest_path = self._path_for_index(dest_idx, self._model)
            if not dest_path:
                QMessageBox.warning(
                    self,
                    "Copy Failed",
                    "Destination path is empty or invalid.",
                )
                return

            try:
                parent, key = self._get_parent_and_key(self._data, dest_path)
            except Exception as exc:
                QMessageBox.warning(
                    self,
                    "Copy Failed",
                    f"Could not resolve destination in main save:\n{exc}",
                )
                return

            try:
                parent[key] = copy.deepcopy(src_node)  # type: ignore[index]
            except Exception as exc:
                QMessageBox.warning(
                    self,
                    "Copy Failed",
                    f"Failed to write into main save:\n{exc}",
                )
                return

            # Rebuild the main model to reflect the change
            self._rebuild_main_model()

    # ------------------------------------------------------------------
    # Path helpers
    # ------------------------------------------------------------------
    def _path_for_index(
        self, idx: QModelIndex, model: LazyJsonModel | None
    ) -> List[str]:
        """
        Build a path of key/index strings for a given index + model.

        FIXED: now includes the top-level key as well.
        """
        if model is None:
            return []

        path: List[str] = []
        cur = idx.siblingAtColumn(0)

        while cur.isValid():
            key = model.data(cur, Qt.ItemDataRole.DisplayRole)
            path.insert(0, str(key))
            parent = cur.parent()
            if not parent.isValid():
                break
            cur = parent

        return path

    @staticmethod
    def _path_to_string(path: List[str]) -> str:
        """
        Turn ["root", "properties", "arr", "3", "key"] into:
            properties.arr[3].key
        (We intentionally skip a top-level "root" label.)
        """
        parts: List[str] = []
        for i, comp in enumerate(path):
            # Skip a leading 'root' label for readability
            if i == 0 and comp == "root":
                continue

            if comp.isdigit() and parts:
                parts[-1] = f"{parts[-1]}[{comp}]"
            else:
                parts.append(comp if not parts else "." + comp)
        return "".join(parts)

    @staticmethod
    def _resolve_path(root: JSON, path: List[str]) -> JSON:
        """
        Follow a path (list of key/index strings taken from the tree) into
        a real JSON structure.

        More tolerant than the first version:
          - Handles labels for list items like "[0]", "#0", "0: item" etc.
          - Ignores a synthetic 'root' label if the real dict doesn't have it.
        """
        node: JSON = root

        for idx, comp in enumerate(path):
            if isinstance(node, dict):
                # First try direct key
                if comp in node:
                    node = node[comp]  # type: ignore[index]
                    continue

                # If the dict has a 'root' key and comp == 'root', descend there
                if comp == "root" and "root" in node:
                    node = node["root"]  # type: ignore[index]
                    continue

                # If this is the first component and dictionary only has one key,
                # treat 'root' as "skip the label" and just go into that single child.
                if comp == "root" and idx == 0 and len(node) == 1:
                    node = next(iter(node.values()))
                    continue

                # No matching key
                raise KeyError(f"Key {comp!r} not found in object")

            elif isinstance(node, list):
                ix = _parse_list_index(comp)
                if ix is None or ix < 0 or ix >= len(node):
                    raise KeyError(f"List index for {comp!r} invalid or out of range")
                node = node[ix]

            else:
                # primitive - cannot descend further
                raise KeyError(
                    f"Cannot descend into primitive {type(node).__name__} with {comp!r}"
                )

        return node

    @staticmethod
    def _get_parent_and_key(root: JSON, path: List[str]):
        """
        For a full path, return (parent_container, last_key_or_index).

        Example:
          root = {"a": {"b": [10, 20]}}
          path = ["a", "b", "1"]
          -> returns (list_ref_for_b, 1)
        """
        if not path:
            raise ValueError("Path is empty; cannot get parent for root.")

        parent_path = path[:-1]
        leaf = path[-1]

        parent = JsonTab._resolve_path(root, parent_path) if parent_path else root

        if isinstance(parent, dict):
            key: Any = leaf
        elif isinstance(parent, list):
            ix = _parse_list_index(leaf)
            if ix is None or ix < 0 or ix >= len(parent):
                raise KeyError(f"List index for {leaf!r} invalid or out of range")
            key = ix
        else:
            raise TypeError(f"Parent is not indexable by {leaf!r}")

        return parent, key
