from __future__ import annotations
from typing import Any, Optional, List, Union
from PyQt6.QtCore import QAbstractItemModel, QModelIndex, Qt, QVariant

JSON = Union[dict, list, str, int, float, bool, None]

class _JsonNode:
    __slots__ = ("key", "value", "parent", "_children")
    def __init__(self, key: str, value: JSON, parent: Optional["_JsonNode"] = None):
        self.key = key
        self.value = value
        self.parent = parent
        self._children: Optional[List[_JsonNode]] = None  # lazy

    def is_container(self) -> bool:
        return isinstance(self.value, (dict, list))

    def ensure_children(self):
        if self._children is not None:
            return
        self._children = []
        v = self.value
        if isinstance(v, dict):
            # Keep insertion order; Python 3.7+ dicts preserve it
            for k, val in v.items():
                self._children.append(_JsonNode(str(k), val, self))
        elif isinstance(v, list):
            for i, val in enumerate(v):
                self._children.append(_JsonNode(str(i), val, self))

    def child_count(self) -> int:
        if not self.is_container():
            return 0
        self.ensure_children()
        return len(self._children) if self._children else 0

    def child(self, row: int) -> Optional["_JsonNode"]:
        self.ensure_children()
        if not self._children:
            return None
        if 0 <= row < len(self._children):
            return self._children[row]
        return None

    def row_in_parent(self) -> int:
        if not self.parent:
            return 0
        self.parent.ensure_children()
        return self.parent._children.index(self)  # small, safe linear scan


class LazyJsonModel(QAbstractItemModel):
    """
    Columns: [Key | Value]
    - Value column is editable for scalars (str/int/float/bool/null).
    - Updates write through to the original dict/list.
    """
    def __init__(self, root_data: JSON, parent=None):
        super().__init__(parent)
        self._root = _JsonNode("root", root_data, None)

    # ---- boilerplate ----
    def columnCount(self, parent=QModelIndex()) -> int:
        return 2

    def rowCount(self, parent=QModelIndex()) -> int:
        node = self._node(parent)
        return node.child_count()

    def index(self, row: int, column: int, parent=QModelIndex()) -> QModelIndex:
        if not self.hasIndex(row, column, parent):
            return QModelIndex()
        parent_node = self._node(parent)
        child = parent_node.child(row)
        if child is None:
            return QModelIndex()
        return self.createIndex(row, column, child)

    def parent(self, index: QModelIndex) -> QModelIndex:
        if not index.isValid():
            return QModelIndex()
        node: _JsonNode = index.internalPointer()
        if not node or not node.parent or node.parent is self._root:
            return QModelIndex()
        p = node.parent
        return self.createIndex(p.row_in_parent(), 0, p)

    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        node: _JsonNode = index.internalPointer()

        if role == Qt.ItemDataRole.DisplayRole:
            if index.column() == 0:
                return node.key
            v = node.value
            if isinstance(v, dict):
                return f"<object> ({len(v)})"
            if isinstance(v, list):
                return f"<array> ({len(v)})"
            return self._scalar_to_str(v)

        if role == Qt.ItemDataRole.EditRole and index.column() == 1 and not node.is_container():
            # Provide raw (string) text for the editor
            return self._scalar_to_str(node.value)

        return None

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Horizontal:
            return ["Key", "Value"][section]
        return None

    # ---- editing ----
    def flags(self, index: QModelIndex):
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        node: _JsonNode = index.internalPointer()
        base = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        if index.column() == 1 and not node.is_container():
            base |= Qt.ItemFlag.ItemIsEditable
        return base

    def setData(self, index: QModelIndex, value: Any, role=Qt.ItemDataRole.EditRole) -> bool:
        if role != Qt.ItemDataRole.EditRole or not index.isValid():
            return False
        if index.column() != 1:
            return False

        node: _JsonNode = index.internalPointer()
        if node.is_container():
            return False  # containers not edited inline

        # Parse text -> JSON scalar (bool/int/float/null or keep as string)
        text = str(value)
        new_val = self._parse_scalar(text)

        # Write-through into the backing container
        parent = node.parent
        if not parent:
            return False

        was_container = node.is_container()
        if isinstance(parent.value, dict):
            parent.value[node.key] = new_val
        elif isinstance(parent.value, list):
            try:
                idx = int(node.key)
            except ValueError:
                return False
            if 0 <= idx < len(parent.value):
                parent.value[idx] = new_val
            else:
                return False
        else:
            return False

        # Update node & clear cached children in case the type changed
        node.value = new_val
        node._children = None

        # Notify view
        self.dataChanged.emit(index, index, [Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole])

        # If node flipped container-ness (e.g., "[]" or "{}"), refresh layout so children show/hide correctly
        is_container_now = node.is_container()
        if was_container != is_container_now:
            # safest reset for this branch
            self.layoutChanged.emit()

        return True

    # ---- helpers ----
    def _node(self, index: QModelIndex) -> _JsonNode:
        return index.internalPointer() if index.isValid() else self._root

    @staticmethod
    def _scalar_to_str(v: JSON) -> str:
        if isinstance(v, bool):
            return "true" if v else "false"
        if v is None:
            return "null"
        return str(v)

    @staticmethod
    def _parse_scalar(text: str) -> JSON:
        s = text.strip()
        # Booleans / null
        low = s.lower()
        if low == "true":  return True
        if low == "false": return False
        if low == "null":  return None
        # Int
        try:
            if s and (s.isdigit() or (s[0] in "+-" and s[1:].isdigit())):
                return int(s, 10)
        except Exception:
            pass
        # Float
        try:
            # Avoid interpreting bare "." or "-" as float
            if any(ch.isdigit() for ch in s):
                return float(s)
        except Exception:
            pass
        # JSON containers (allow editing into [] / {})
        if (s.startswith("{") and s.endswith("}")) or (s.startswith("[") and s.endswith("]")):
            import json as _json
            try:
                return _json.loads(s)
            except Exception:
                # fall back to string if invalid JSON
                return text
        # Default to string
        return text
